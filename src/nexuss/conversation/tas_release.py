"""Exact-commit dashboard release with independent CI and owner approval."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import time
from pathlib import Path
from uuid import UUID, uuid4

from nexuss.interactions.progress import emit

REPOSITORY = "kexyz254/trading-analysis-platform"
REQUIRED_CI = frozenset({"Python Tests", "Docker Build",
                         "Fuzz Build Smoke Test", "P6.31 TAS BTC Price Call Results"})
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def validate_ci(commit, plane_factory=None):
    if not COMMIT.fullmatch(commit):
        raise ValueError("Invalid commit")
    if plane_factory is None:
        from nexuss.connectors.github.workspace_control import GitHubWorkspaceControlPlane
        plane_factory = GitHubWorkspaceControlPlane.from_environment
    report = plane_factory().inspect_actions(REPOSITORY)
    matching = {run.name: run for run in report.runs if run.head_sha == commit
                and run.name in REQUIRED_CI and run.status == "completed"
                and run.conclusion == "success"}
    if not REQUIRED_CI <= set(matching):
        raise ValueError("Exact commit does not have all required passing TAS checks")
    return {name: matching[name].run_id for name in sorted(REQUIRED_CI)}


def sign_owner_approval(rid, commit, digest):
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
    key_path = Path(os.getenv("NEXUSS_TAS_APPROVAL_KEY_FILE") or
                    root / "Nexuss" / "release" / "approval.key")
    secret = key_path.read_bytes().strip()
    if len(secret) < 32:
        raise ValueError("Dashboard release approval key is not configured")
    message = f"approved-release-v1\n{rid}\n{commit}\n{digest}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


class ReleaseStore:
    def __init__(self, path=None, *, now=time.time):
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
        self.path = str(path or root / "Nexuss" / "tas-releases.sqlite3")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.now = now
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS releases (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, commit_sha TEXT NOT NULL,
                digest TEXT NOT NULL, base_image TEXT NOT NULL,
                created INTEGER NOT NULL, status TEXT NOT NULL
            )""")

    def save(self, owner, receipt):
        rid, commit, digest, base = (receipt[k] for k in
            ("release_id", "commit", "digest", "base_image"))
        if (not re.fullmatch(r"[0-9a-f]{32}", rid) or not COMMIT.fullmatch(commit)
                or not DIGEST.fullmatch(digest)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", base)
                or not isinstance(receipt.get("file_hashes"), dict)
                or set(receipt["file_hashes"]) != {
                    "webapp/price_call_results.py", "webapp/nexuss_account_overlay.py"}
                or any(not isinstance(value, str) or not DIGEST.fullmatch(value)
                       for value in receipt["file_hashes"].values())
                or receipt.get("status") != "prepared"):
            raise ValueError("Invalid release preparation receipt")
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO releases VALUES (?, ?, ?, ?, ?, ?, 'prepared')",
                       (rid, owner, commit, digest, base, int(self.now())))
        return rid

    def get(self, owner, rid, digest):
        if not re.fullmatch(r"[0-9a-f]{32}", rid) or not DIGEST.fullmatch(digest):
            raise ValueError("Invalid approval identity")
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT commit_sha,digest,base_image,created,status FROM releases "
                             "WHERE id=? AND owner=?", (rid, owner)).fetchone()
        if not row or row[1] != digest or row[4] not in {"prepared", "applying"}:
            raise ValueError("Release is not awaiting this owner's exact approval")
        if int(self.now()) - row[3] > 1800:
            raise ValueError("Release approval window expired")
        return {"commit": row[0], "digest": row[1], "base_image": row[2]}

    def set_status(self, owner, rid, current, target):
        with sqlite3.connect(self.path) as db:
            result = db.execute("UPDATE releases SET status=? WHERE id=? AND owner=? AND status=?",
                                (target, rid, owner, current))
            return result.rowcount == 1


def prepare_release(owner, commit, client_factory, *, store=None, plane_factory=None):
    if not owner or not COMMIT.fullmatch(commit):
        raise ValueError("Authenticated owner and exact source commit required")
    emit("workflow_step", "running", "Validation: checking four CI workflows on the exact TAS commit.")
    checks = validate_ci(commit, plane_factory)
    emit("workflow_step", "running", "Maintenance: checking the host image and fixed source files.")
    store = store or ReleaseStore()
    rid = uuid4()
    receipt = client_factory().release("prepare", rid, commit, "0" * 64)
    if receipt.get("release_id") != rid.hex or receipt.get("commit") != commit:
        raise ValueError("Release identity mismatch")
    store.save(owner, receipt)
    emit("workflow_step", "completed", "Release prepared; waiting for exact owner approval.")
    return (f"TAS dashboard release {rid.hex} is prepared from commit {commit}.\n"
            f"Review commit: https://github.com/{REPOSITORY}/commit/{commit}.\n"
            f"Manifest SHA-256: {receipt['digest']}.\n"
            f"Current dashboard image: {receipt['base_image']}.\n"
            "Fixed source files: " + ", ".join(
                f"{path} ({receipt['file_hashes'][path]})"
                for path in sorted(receipt["file_hashes"])) + ".\n"
            "Passing CI: " + ", ".join(sorted(checks)) + ".\n"
            "Scope: build a small dashboard overlay, replace only the dashboard, "
            "verify readiness and BTC outcomes, and roll back on failure. The engine, "
            "breaker and trades are not targeted.\n"
            f"To authorize this exact release in this authenticated chat, say: "
            f"approve TAS dashboard release {rid.hex} {receipt['digest']}\n"
            "Approval expires in 30 minutes. No build or deployment has occurred.")


def apply_release(owner, rid, digest, client_factory, *, store=None, plane_factory=None):
    if not owner:
        raise ValueError("Authenticated owner required")
    store = store or ReleaseStore()
    item = store.get(owner, rid, digest)
    emit("workflow_step", "running", "Validation: reconfirming CI for the approved commit.")
    validate_ci(item["commit"], plane_factory)
    approval = sign_owner_approval(rid, item["commit"], digest)
    if not store.set_status(owner, rid, "prepared", "applying"):
        # Replaying exactly the same release ID can recover the host receipt,
        # but cannot authorize a different payload or a second deployment.
        store.get(owner, rid, digest)
    emit("workflow_step", "running", "Engineering: building the fixed overlay from pinned source blobs.")
    receipt = client_factory().release("apply", UUID(hex=rid), item["commit"], digest,
                                       approval_signature=approval)
    if (receipt.get("release_id") != rid or receipt.get("commit") != item["commit"]
            or receipt.get("digest") != digest):
        raise ValueError("Release receipt mismatch")
    status = receipt.get("status")
    if status not in {"deployed_verified", "rolled_back", "rollback_unverified",
                      "build_failed", "precondition_changed", "outcome_unverified", "reserved"}:
        raise ValueError("Unknown release outcome")
    store.set_status(owner, rid, "applying", status)
    if status == "deployed_verified" and receipt.get("verified") is True:
        emit("workflow_step", "completed", "Dashboard release verified against live BTC outcomes.")
        return (f"TAS dashboard release {rid} deployed and verified. Commit: {item['commit']}. "
                "The dashboard and BTC 5m/15m tracker are ready. The engine, breaker and "
                "trade execution were not targeted."), False
    emit("workflow_step", "blocked", "Release did not achieve a verified deployment.")
    return (f"TAS dashboard release {rid} ended as {status}. "
            "No successful deployment is claimed. If rollback is unverified, inspect "
            "the dashboard locally before another attempt."), True
