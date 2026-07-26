"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nexuss.device.models import DeviceCommandEnvelope
from nexuss.device.signing import sign_payload
from nexuss.device_node import app as node_module
from nexuss.device_node.executor import WindowsNotepadExecutor
from tests.fakes import FakeRunner

SECRET = "s" * 48
client = TestClient(node_module.app)


def _envelope(nonce: str) -> DeviceCommandEnvelope:
    now = datetime.now(UTC)
    return DeviceCommandEnvelope(
        command_id=UUID("00000000-0000-0000-0000-000000000781"),
        task_id=UUID("00000000-0000-0000-0000-000000000780"),
        capability_id="device.launch_notepad",
        target_node_id="windows-primary",
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        nonce=nonce,
        parameters={},
    )


def test_signed_command_executes_once_and_replay_is_rejected(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executable = (
        tmp_path / "Windows" / "System32" / "notepad.exe"
    ).resolve()

    monkeypatch.setenv("NEXUSS_DEVICE_NODE_SECRET", SECRET)
    monkeypatch.setattr(
        node_module,
        "executor",
        WindowsNotepadExecutor(
            node_id="windows-primary",
            executable=executable,
            runner=runner,
        ),
    )

    node_module.reset_nonce_cache()
    envelope = _envelope("n" * 40)
    signature = sign_payload(envelope, SECRET)

    response = client.post(
        "/v1/commands",
        json=envelope.model_dump(mode="json"),
        headers={"X-Nexuss-Node-Signature": signature},
    )

    assert response.status_code == 200, response.text
    assert response.json()["verified_running"] is True
    assert runner.executables == [executable]

    replay = client.post(
        "/v1/commands",
        json=envelope.model_dump(mode="json"),
        headers={"X-Nexuss-Node-Signature": signature},
    )

    assert replay.status_code == 409, replay.text
    assert "DEVICE_NONCE_REPLAYED" in replay.text


def test_tampered_signature_is_rejected(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEXUSS_DEVICE_NODE_SECRET", SECRET)
    node_module.reset_nonce_cache()
    envelope = _envelope("t" * 40)

    response = client.post(
        "/v1/commands",
        json=envelope.model_dump(mode="json"),
        headers={"X-Nexuss-Node-Signature": "0" * 64},
    )

    assert response.status_code == 401, response.text
    assert "DEVICE_NODE_SIGNATURE_INVALID" in response.text
