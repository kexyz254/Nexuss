from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from nexuss.connectors.contracts import (
    ConnectorHealth,
    ConnectorIdentity,
    ConnectorStatus,
)
from nexuss.connectors.github.models import (
    GitHubRepository,
    GitHubRepositoryInventory,
    PreparedRepositoryCreate,
    VerifiedRepositoryCreate,
)
from nexuss.core.executor import execute_step
from nexuss.core.intents import classify_intent
from nexuss.core.planner import build_plan
from nexuss.core.policy import evaluate_step
from nexuss.core.registry import get_capability
from nexuss.domain.models import (
    ApprovalChannel,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalStatus,
    IntentKind,
    PolicyOutcome,
    RiskTier,
    StepStatus,
)


def repository() -> GitHubRepository:
    return GitHubRepository(
        repository_id=101,
        node_id="R_example",
        name="Nexuss-AI",
        full_name="kexyz254/Nexuss-AI",
        owner_login="kexyz254",
        private=True,
        html_url="https://github.com/kexyz254/Nexuss-AI",
        api_url="https://api.github.com/repos/kexyz254/Nexuss-AI",
    )


class FakeConnector:
    def health(self, *, now=None):
        observed = now or datetime.now(UTC)
        return ConnectorHealth(
            connector_id="github",
            status=ConnectorStatus.CONNECTED,
            configured=True,
            identity=ConnectorIdentity(
                connector_id="github",
                external_account_id="158442432",
                account_label="kexyz254",
                account_type="User",
                verified=True,
                observed_at=observed,
            ),
            detail="verified",
            checked_at=observed,
        )

    def list_repositories(self, *, now=None):
        return GitHubRepositoryInventory(
            account_login="kexyz254",
            total=1,
            private_count=1,
            public_count=0,
            archived_count=0,
            disabled_count=0,
            fork_count=0,
            repositories=(repository(),),
            observed_at=now or datetime.now(UTC),
        )

    def prepare_private_repository(self, requested_name, *, description="", now=None):
        import hashlib
        import json

        payload = {
            "name": "Nexuss-AI",
            "private": True,
            "auto_init": False,
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return PreparedRepositoryCreate(
            owner_login="kexyz254",
            requested_name=requested_name,
            repository_name="Nexuss-AI",
            payload=payload,
            payload_sha256=digest,
            prepared_at=now or datetime.now(UTC),
        )

    def create_private_repository(self, prepared, approval, *, now=None):
        return VerifiedRepositoryCreate(
            request_id=prepared.request_id,
            approval_id=approval.approval_id,
            payload_sha256=prepared.payload_sha256,
            repository=repository(),
            private_verified=True,
            empty_repository_verified=True,
            owner_verified=True,
            name_verified=True,
            verified_at=now or datetime.now(UTC),
        )


def test_create_intent_and_exact_name():
    intent = classify_intent(
        "Create a private GitHub repository named "
        "Nexuss AI. Do not initialize anything."
    )
    assert intent.kind is IntentKind.GITHUB_CREATE_REPOSITORY
    assert intent.entities["requested_name"] == "Nexuss AI"
    assert intent.entities["repository_name"] == "Nexuss-AI"


def test_manifest_requires_phone_approval():
    manifest = get_capability("github.repository.create")
    assert manifest is not None
    assert manifest.approval_policy is ApprovalPolicy.EXPLICIT
    assert manifest.approval_channel is ApprovalChannel.PHONE


def test_create_denied_without_verified_account():
    intent = classify_intent("Create a private repo named Nexuss AI.")
    decision = evaluate_step(build_plan(uuid4(), intent).steps[0])
    assert decision.outcome is PolicyOutcome.DENY
    assert decision.reason_code == "GITHUB_NOT_CONNECTED"


def test_live_repository_read():
    intent = classify_intent("Check my GitHub repositories.")
    step = build_plan(uuid4(), intent).steps[0]
    result = execute_step(
        step,
        observed_at=datetime.now(UTC),
        github_connector=FakeConnector(),
    )
    assert result.status is StepStatus.VERIFIED
    data = result.evidence[0].attributes
    assert data["total"] == 1
    assert data["credentials_exposed"] is False


def test_approved_create_is_verified():
    intent = classify_intent("Create a private repo named Nexuss AI.")
    intent = intent.model_copy(
        update={
            "entities": {
                **intent.entities,
                "account_login": "kexyz254",
                "account_id": "158442432",
            }
        }
    )
    plan = build_plan(uuid4(), intent)
    step = plan.steps[0]
    now = datetime.now(UTC)
    approval = ApprovalRequest(
        approval_id=uuid4(),
        task_id=plan.task_id,
        capability_id=step.capability_id,
        status=ApprovalStatus.PENDING,
        action_title="Create private GitHub repository",
        action_summary="Create exact repository.",
        exact_preview="exact",
        destination_label="GitHub",
        payload_sha256="0" * 64,
        approval_token="x" * 32,
        session_id=uuid4(),
        expires_at=now + timedelta(minutes=5),
        risk_tier=RiskTier.HIGH,
        reversible=False,
        approval_channel=ApprovalChannel.PHONE,
    )
    result = execute_step(
        step,
        observed_at=now,
        github_connector=FakeConnector(),
        approval=approval,
    )
    assert result.status is StepStatus.VERIFIED
    data = result.evidence[0].attributes
    assert data["full_name"] == "kexyz254/Nexuss-AI"
    assert data["private_verified"] is True
    assert data["empty_repository_verified"] is True
    assert data["credentials_exposed"] is False
