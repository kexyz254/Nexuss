from types import SimpleNamespace
from typing import ClassVar
from uuid import UUID

import pytest

from nexuss.conversation import tas_release
from nexuss.conversation.trading import handle_trading_chat

COMMIT = "a" * 40
IMAGE = "sha256:" + "b" * 64
DIGEST = "c" * 64


class Client:
    calls: ClassVar[list[tuple[str, str, str, str]]] = []

    def release(self, operation, rid, commit, digest, approval_signature=""):
        self.calls.append((operation, rid.hex, commit, digest))
        if operation == "prepare":
            return {"release_id": rid.hex, "commit": commit, "digest": DIGEST,
                    "base_image": IMAGE, "status": "prepared",
                    "file_hashes": {"webapp/price_call_results.py": "d" * 64,
                                    "webapp/nexuss_account_overlay.py": "e" * 64}}
        return {"release_id": rid.hex, "commit": commit, "digest": digest,
                "status": "deployed_verified", "verified": True}


def test_exact_ci_required_for_commit():
    class Plane:
        def inspect_actions(self, repository):
            assert repository == tas_release.REPOSITORY
            return SimpleNamespace(runs=[SimpleNamespace(name=name, head_sha=COMMIT,
                    status="completed", conclusion="success", run_id=i)
                    for i, name in enumerate(tas_release.REQUIRED_CI, start=1)])
    assert set(tas_release.validate_ci(COMMIT, lambda: Plane())) == tas_release.REQUIRED_CI

    class Missing:
        def inspect_actions(self, repository):
            return SimpleNamespace(runs=[])
    with pytest.raises(ValueError):
        tas_release.validate_ci(COMMIT, lambda: Missing())


def test_owner_prepares_approves_and_cannot_reapprove(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    key = tmp_path / "Nexuss" / "release" / "approval.key"
    key.parent.mkdir(parents=True)
    key.write_bytes(b"test-only-owner-approval-key-1234567890")
    monkeypatch.setattr(tas_release, "validate_ci", lambda commit, plane_factory=None:
                        {name: i for i, name in enumerate(tas_release.REQUIRED_CI)})
    Client.calls = []
    reply = handle_trading_chat(f"Prepare TAS dashboard release from commit {COMMIT}",
                                owner="owner", client_factory=Client)
    assert reply.workflow and not reply.blocked and "No build or deployment" in reply.text
    assert len(Client.calls) == 1 and Client.calls[0][0] == "prepare"
    rid = Client.calls[0][1]
    reply = handle_trading_chat(f"approve TAS dashboard release {rid} {DIGEST}",
                                owner="owner", client_factory=Client)
    assert reply.workflow and not reply.blocked and "deployed and verified" in reply.text
    assert [item[0] for item in Client.calls] == ["prepare", "apply"]
    # A repeated approval cannot trigger a new release operation.
    reply = handle_trading_chat(f"approve TAS dashboard release {rid} {DIGEST}",
                                owner="owner", client_factory=Client)
    assert reply.blocked and len(Client.calls) == 2


def test_other_owner_and_wrong_digest_cannot_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(tas_release, "validate_ci", lambda commit, plane_factory=None:
                        {"Python Tests": 1})
    Client.calls = []
    tas_release.prepare_release("owner", COMMIT, Client)
    rid = Client.calls[0][1]
    for owner, digest in (("attacker", DIGEST), ("owner", "f" * 64)):
        reply = handle_trading_chat(f"approve TAS dashboard release {rid} {digest}",
                                    owner=owner, client_factory=Client)
        assert reply.blocked
    assert len(Client.calls) == 1


def test_expired_approval_blocked(tmp_path):
    now = [1000]
    store = tas_release.ReleaseStore(tmp_path / "releases.sqlite3", now=lambda: now[0])
    receipt = Client().release("prepare", UUID(int=9), COMMIT, "0" * 64)
    store.save("owner", receipt)
    now[0] = 3001
    with pytest.raises(ValueError, match="expired"):
        store.get("owner", UUID(int=9).hex, DIGEST)
