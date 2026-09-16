"""Opt-in SSH transport owned by the Nexuss core; no remote command executor."""
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from threading import Event, Lock, Thread


def settings_path():
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return root / "Nexuss" / "bridge" / "tunnel.json"


def load_settings(path):
    if not path.exists():
        return None
    if path.stat().st_size > 4096:
        raise ValueError("Invalid tunnel settings")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or set(value) != {"enabled", "host", "user", "identity_file"}:
        raise ValueError("Invalid tunnel settings")
    if type(value["enabled"]) is not bool:
        raise ValueError("Invalid enabled flag")
    if not value["enabled"]:
        return None
    ipaddress.IPv4Address(value["host"])
    if not isinstance(value["user"], str) or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", value["user"]):
        raise ValueError("Invalid SSH user")
    identity = value["identity_file"]
    if not isinstance(identity, str) or any(c in identity for c in "\r\n\x00") or not Path(identity).is_absolute() or not Path(identity).is_file():
        raise ValueError("SSH identity file unavailable")
    return value


def command(ssh, settings):
    return [ssh, "-F", "none", "-N", "-T", "-n",
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
            "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no",
            "-i", settings["identity_file"],
            "-L", "127.0.0.1:8300:127.0.0.1:8300", "-l", settings["user"], settings["host"]]


def port_open():
    try:
        with socket.create_connection(("127.0.0.1", 8300), timeout=0.3):
            return True
    except OSError:
        return False


class ManagedTunnel:
    def __init__(self, path=None, *, probe=port_open, launch=subprocess.Popen, find_ssh=shutil.which):
        self.path = path
        self.probe, self.launch, self.find_ssh = probe, launch, find_ssh
        self._stop = Event()
        self._lock = Lock()
        self._thread = None
        self._process = None
        self._state = "disabled"
        self._attempts = 0
        self._settings = None
        self._ssh = None

    def status(self):
        with self._lock:
            return {"state": self._state, "attempts": self._attempts,
                    "managed": self._process is not None,
                    "authenticated_bridge_verified": False,
                    "scope": "transport only; use signed TAS health to verify the bridge"}

    def _set(self, state):
        with self._lock:
            self._state = state

    def configure(self):
        try:
            self._settings = load_settings(self.path or settings_path())
            if self._settings is None:
                self._set("disabled")
                return False
            self._ssh = self.find_ssh("ssh")
            if not self._ssh:
                self._set("ssh_unavailable")
                return False
            self._set("starting")
            return True
        except (OSError, ValueError, TypeError):
            self._set("configuration_invalid")
            return False

    def tick(self):
        """One bounded supervisor iteration. It never terminates an external listener."""
        if self._process is not None:
            if self._process.poll() is None:
                self._set("forwarding" if self.probe() else "connecting")
                return 2
            self._process.wait()
            self._process = None
            self._set("retry_wait")
            return min(60, 2 ** min(self._attempts, 6))
        if self.probe():
            self._set("external_listener")
            return 2
        options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                   "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        with self._lock:
            self._attempts += 1
        try:
            self._process = self.launch(command(self._ssh, self._settings), **options)
            self._set("connecting")
            return 2
        except OSError:
            self._set("launch_failed")
            return 30

    def _run(self):
        while not self._stop.is_set():
            try:
                delay = self.tick()
            except Exception:
                self._set("supervisor_error")
                delay = 30
            self._stop.wait(delay)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.configure():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="nexuss-tas-transport", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        process = self._process
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            self._process = None
        self._set("stopped")


managed_tunnel = ManagedTunnel()
