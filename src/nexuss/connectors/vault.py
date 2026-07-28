"""Secret-vault implementations for Nexuss connectors."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
from ctypes import wintypes
from pathlib import Path
from threading import RLock
from typing import Protocol

from nexuss.connectors.errors import ConnectorError


class SecretVault(Protocol):
    def put_json(self, secret_id: str, payload: dict[str, object]) -> None: ...

    def get_json(self, secret_id: str) -> dict[str, object] | None: ...

    def delete(self, secret_id: str) -> None: ...

    def exists(self, secret_id: str) -> bool: ...


class InMemorySecretVault:
    """Test-only vault with the same contract as the encrypted vault."""

    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}
        self._lock = RLock()

    def put_json(self, secret_id: str, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        with self._lock:
            self._items[secret_id] = encoded

    def get_json(self, secret_id: str) -> dict[str, object] | None:
        with self._lock:
            encoded = self._items.get(secret_id)
        if encoded is None:
            return None
        result = json.loads(encoded.decode())
        if not isinstance(result, dict):
            raise ConnectorError(
                "CONNECTOR_VAULT_RECORD_INVALID",
                "The secret-vault record was not an object.",
            )
        return result

    def delete(self, secret_id: str) -> None:
        with self._lock:
            self._items.pop(secret_id, None)

    def exists(self, secret_id: str) -> bool:
        with self._lock:
            return secret_id in self._items


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class DpapiSecretVault:
    """Windows user-scoped DPAPI vault with atomic encrypted files."""

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1
    _ENTROPY = b"NexussConnectorVault:v1"

    def __init__(self, root: Path | None = None) -> None:
        if platform.system() != "Windows":
            raise ConnectorError(
                "CONNECTOR_VAULT_PLATFORM_UNSUPPORTED",
                "DPAPI secret storage requires Windows.",
            )

        local_app_data = os.getenv("LOCALAPPDATA")
        if root is None and not local_app_data:
            raise ConnectorError(
                "CONNECTOR_VAULT_PATH_UNAVAILABLE",
                "LOCALAPPDATA is unavailable.",
            )

        self._root = root or Path(str(local_app_data)) / "Nexuss" / "connector-vault"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL

    def put_json(self, secret_id: str, payload: dict[str, object]) -> None:
        envelope = {"secret_id": secret_id, "payload": payload, "format_version": 1}
        plaintext = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        encrypted = self._protect(plaintext)
        path = self._path(secret_id)
        temporary = path.with_suffix(".tmp")
        with self._lock:
            with temporary.open("wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)

    def get_json(self, secret_id: str) -> dict[str, object] | None:
        path = self._path(secret_id)
        with self._lock:
            if not path.exists():
                return None
            encrypted = path.read_bytes()
        try:
            envelope = json.loads(self._unprotect(encrypted).decode())
        except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            raise ConnectorError(
                "CONNECTOR_VAULT_DECRYPT_FAILED",
                "The encrypted connector record could not be read.",
            ) from exc
        if (
            not isinstance(envelope, dict)
            or envelope.get("secret_id") != secret_id
            or not isinstance(envelope.get("payload"), dict)
        ):
            raise ConnectorError(
                "CONNECTOR_VAULT_RECORD_INVALID",
                "The connector vault record failed validation.",
            )
        return dict(envelope["payload"])

    def delete(self, secret_id: str) -> None:
        with self._lock:
            try:
                self._path(secret_id).unlink()
            except FileNotFoundError:
                return

    def exists(self, secret_id: str) -> bool:
        return self._path(secret_id).exists()

    def _path(self, secret_id: str) -> Path:
        digest = hashlib.sha256(secret_id.encode()).hexdigest()
        return self._root / f"{digest}.nexuss-secret"

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def _protect(self, plaintext: bytes) -> bytes:
        source, source_buffer = self._blob(plaintext)
        entropy, entropy_buffer = self._blob(self._ENTROPY)
        output = _DataBlob()
        _ = source_buffer, entropy_buffer
        succeeded = self._crypt32.CryptProtectData(
            ctypes.byref(source),
            "Nexuss Connector Secret",
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        if not succeeded:
            raise ConnectorError(
                "CONNECTOR_VAULT_ENCRYPT_FAILED",
                "Windows DPAPI could not encrypt the connector secret.",
            )
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def _unprotect(self, encrypted: bytes) -> bytes:
        source, source_buffer = self._blob(encrypted)
        entropy, entropy_buffer = self._blob(self._ENTROPY)
        output = _DataBlob()
        description = wintypes.LPWSTR()
        _ = source_buffer, entropy_buffer
        succeeded = self._crypt32.CryptUnprotectData(
            ctypes.byref(source),
            ctypes.byref(description),
            ctypes.byref(entropy),
            None,
            None,
            self._CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(output),
        )
        if not succeeded:
            raise ConnectorError(
                "CONNECTOR_VAULT_DECRYPT_FAILED",
                "Windows DPAPI could not decrypt the connector secret.",
            )
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            if output.pbData:
                self._kernel32.LocalFree(output.pbData)
            if description:
                self._kernel32.LocalFree(description)
