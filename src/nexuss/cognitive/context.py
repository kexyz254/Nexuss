"""Privacy-filtered context for cognitive providers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nexuss.core.registry import list_capabilities


class CognitiveCapabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    title: str
    risk_tier: str
    approval_policy: str
    execution_mode: str
    status: str


class CognitiveArchitectureComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component: str
    responsibility: str


class CognitiveContextSnapshot(BaseModel):
    """Bounded context containing no credentials or repository content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_mode: str
    api_version: str
    interface: str
    git_branch: str
    git_commit: str
    git_changed_entries: int = Field(ge=0)
    provider_status: str

    capabilities: tuple[CognitiveCapabilitySummary, ...]
    architecture: tuple[CognitiveArchitectureComponent, ...]
    authority_boundary: tuple[str, ...]

    contains_credentials: bool = False
    contains_file_contents: bool = False
    contains_approval_tokens: bool = False
    contains_hidden_reasoning: bool = False

    def to_provider_summary(self) -> str:
        return self.model_dump_json(indent=2)


def _run_git(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=Path.cwd(),
            check=True,
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return ""

    return completed.stdout.strip()


def build_cognitive_context(
    *,
    provider_status: str,
) -> CognitiveContextSnapshot:
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    commit = _run_git("rev-parse", "HEAD")
    porcelain = _run_git("status", "--porcelain")

    changed_entries = len(
        [
            line
            for line in porcelain.splitlines()
            if line.strip()
        ]
    )

    capabilities = tuple(
        CognitiveCapabilitySummary(
            capability_id=manifest.capability_id,
            title=manifest.title,
            risk_tier=str(manifest.risk_tier),
            approval_policy=str(manifest.approval_policy),
            execution_mode=manifest.execution_mode,
            status=str(manifest.status),
        )
        for manifest in list_capabilities()
    )

    architecture = (
        CognitiveArchitectureComponent(
            component="FastAPI control API",
            responsibility=(
                "Authenticated local API entry points, security headers, "
                "session validation, and bounded connector registration."
            ),
        ),
        CognitiveArchitectureComponent(
            component="Deterministic intent and planning plane",
            responsibility=(
                "Classify operational intent and produce registered "
                "capability plans."
            ),
        ),
        CognitiveArchitectureComponent(
            component="Policy and approval plane",
            responsibility=(
                "Allow safe reads, deny unsupported operations, and require "
                "exact-payload approval for controlled writes."
            ),
        ),
        CognitiveArchitectureComponent(
            component="Execution and verification plane",
            responsibility=(
                "Execute registered capabilities and verify expected evidence."
            ),
        ),
        CognitiveArchitectureComponent(
            component="DeepSeek cognitive provider",
            responsibility=(
                "Generate bounded answers, designs, plans, code proposals, "
                "reviews, debugging guidance, and creative work without tools."
            ),
        ),
        CognitiveArchitectureComponent(
            component="Static JavaScript control interface",
            responsibility=(
                "Present conversations, plans, approvals, evidence, "
                "lifecycles, and receipts."
            ),
        ),
        CognitiveArchitectureComponent(
            component="Trusted mobile fabric",
            responsibility=(
                "Require exact-payload phone approval for trusted-device "
                "and external write operations."
            ),
        ),
        CognitiveArchitectureComponent(
            component="Commitment intelligence",
            responsibility=(
                "Provide read-only calendar, email, contact, and commitment "
                "summaries through privacy-bounded connectors."
            ),
        ),
    )

    authority_boundary = (
        "DeepSeek may reason, analyze, write, design, code, review, debug, "
        "plan, synthesize, and create proposals.",
        "DeepSeek has no shell, file, connector, device, approval, receipt, "
        "publishing, credential, or execution authority.",
        "Nexuss selects and minimizes context before external processing.",
        "Nexuss retains policy, approval, dispatch, execution, verification, "
        "receipt, audit, and final authority.",
        "Real writes require the applicable Nexuss approval policy.",
    )

    return CognitiveContextSnapshot(
        active_mode=os.getenv(
            "NEXUSS_CORE_MODE",
            "p68a_unified_commitment_intelligence",
        ),
        api_version="0.5.2",
        interface="FastAPI and static JavaScript P5 control plane",
        git_branch=branch or "unavailable",
        git_commit=commit or "unavailable",
        git_changed_entries=changed_entries,
        provider_status=provider_status,
        capabilities=capabilities,
        architecture=architecture,
        authority_boundary=authority_boundary,
    )
