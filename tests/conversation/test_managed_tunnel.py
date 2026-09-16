import json
import subprocess

import pytest

from nexuss.connectors.trading_tunnel import ManagedTunnel, command, load_settings


def configured(tmp_path, **kwargs):
    identity = tmp_path / "test_identity"
    identity.write_text("test fixture only")
    path = tmp_path / "tunnel.json"
    path.write_text(json.dumps({"enabled": True, "host": "192.0.2.1", "user": "tunnel",
                                "identity_file": str(identity)}))
    return ManagedTunnel(path, find_ssh=lambda name: "/usr/bin/ssh", **kwargs)


class Process:
    exited = False
    terminated = False
    def poll(self):
        return 1 if self.exited else None
    def wait(self, **kwargs):
        return 1
    def terminate(self):
        self.terminated = True
        self.exited = True


def test_owned_process_reconnects_and_stops(tmp_path):
    children = []
    def launch(args, **kwargs):
        assert "shell" not in kwargs
        assert kwargs["stdin"] == subprocess.DEVNULL
        child = Process()
        children.append(child)
        return child
    manager = configured(tmp_path, probe=lambda: False, launch=launch)
    assert manager.configure()
    manager.tick()
    assert manager.status()["state"] == "connecting"
    children[0].exited = True
    delay = manager.tick()
    assert 2 <= delay <= 60
    assert manager.status()["state"] == "retry_wait"
    manager.tick()
    assert len(children) == 2
    manager.stop()
    assert children[1].terminated
    assert manager.status()["state"] == "stopped"


def test_external_listener_is_not_owned_or_terminated(tmp_path):
    manager = configured(tmp_path, probe=lambda: True, launch=lambda *a, **k: pytest.fail("Cannot take over listener"))
    assert manager.configure()
    manager.tick()
    assert manager.status()["state"] == "external_listener"
    assert manager.status()["managed"] is False
    assert manager.status()["authenticated_bridge_verified"] is False
    manager.stop()


def test_fixed_transport_has_no_remote_command_and_no_password_prompt(tmp_path):
    manager = configured(tmp_path)
    assert manager.configure()
    args = command("ssh", manager._settings)
    assert args[-1] == "192.0.2.1"
    assert args[args.index("-L") + 1] == "127.0.0.1:8300:127.0.0.1:8300"
    assert {"-N", "BatchMode=yes", "StrictHostKeyChecking=yes", "ForwardAgent=no"} <= set(args)
    assert args[1:3] == ["-F", "none"]


def test_disabled_and_invalid_configuration_do_not_launch(tmp_path):
    manager = ManagedTunnel(tmp_path / "missing")
    assert manager.configure() is False
    assert manager.status()["state"] == "disabled"
    bad = tmp_path / "invalid"
    bad.write_text('{"enabled":true,"command":"shell"}')
    manager = ManagedTunnel(bad)
    assert manager.configure() is False
    assert manager.status()["state"] == "configuration_invalid"


def test_options_cannot_be_injected_through_host(tmp_path):
    manager = configured(tmp_path)
    settings = json.loads(manager.path.read_text())
    settings["host"] = "-oProxyCommand=anything"
    manager.path.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        load_settings(manager.path)


def test_core_lifecycle_owns_transport(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from nexuss.connectors.trading import register_trading_routes
    import nexuss.connectors.trading_tunnel as module
    events = []
    fake = SimpleNamespace(start=lambda: events.append("start"), stop=lambda: events.append("stop"),
                           status=lambda: {"state": "disabled"})
    monkeypatch.setattr(module, "managed_tunnel", fake)
    app = FastAPI()
    register_trading_routes(app, lambda request: events.append("authorized"))
    with TestClient(app) as client:
        assert events == ["start"]
        assert client.get("/v1/trading/transport/status").json() == {"state": "disabled"}
    assert events == ["start", "authorized", "stop"]
