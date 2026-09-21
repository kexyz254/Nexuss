"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Fail-closed policy evaluation for the Nexuss P5 capability registry.
"""

from nexuss.core.registry import get_capability
from nexuss.domain.models import (
    ApprovalChannel,
    ApprovalPolicy,
    CapabilityStatus,
    PlanStep,
    PolicyDecision,
    PolicyOutcome,
)

_PROHIBITED_CAPABILITIES = {
    "ats.write_order",
    "finance.transfer",
    "social.publish",
    "nexuss.unsupported",
    "device.workspace.prepare",
}


def evaluate_step(step: PlanStep) -> PolicyDecision:
    if step.capability_id in _PROHIBITED_CAPABILITIES:
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.DENY,
            reason_code="CAPABILITY_PROHIBITED_BY_POLICY",
            explanation="This capability is outside the approved P5 execution boundary.",
        )

    if step.capability_id == "github.repository.create":
        if not str(step.parameters.get("account_login", "")).strip():
            return PolicyDecision(
                step_id=step.step_id,
                capability_id=step.capability_id,
                outcome=PolicyOutcome.DENY,
                reason_code="GITHUB_NOT_CONNECTED",
                explanation=(
                    "A verified GitHub account must be connected before "
                    "repository creation can be approved."
                ),
            )
        if (
            step.parameters.get("private") is not True
            or step.parameters.get("auto_init") is not False
        ):
            return PolicyDecision(
                step_id=step.step_id,
                capability_id=step.capability_id,
                outcome=PolicyOutcome.DENY,
                reason_code="GITHUB_REPOSITORY_CONTRACT_INVALID",
                explanation=(
                    "Only a private, uninitialized repository is permitted."
                ),
            )

    if step.capability_id == "system.update.apply":
        branch = str(step.parameters.get("branch", ""))
        current_sha = str(
            step.parameters.get("expected_current_sha", "")
        )
        target_sha = str(
            step.parameters.get("expected_target_sha", "")
        )
        sha_valid = (
            len(current_sha) == 40
            and len(target_sha) == 40
            and all(
                character in "0123456789abcdef"
                for character in current_sha + target_sha
            )
        )
        clean_worktree = (
            str(step.parameters.get("clean_worktree", "")).casefold()
            == "true"
        )
        fast_forward_available = (
            str(
                step.parameters.get(
                    "fast_forward_available",
                    "",
                )
            ).casefold()
            == "true"
        )
        if (
            branch != "feature/p5-knowledge-media-mobile"
            or not sha_valid
            or current_sha == target_sha
            or not clean_worktree
            or not fast_forward_available
        ):
            return PolicyDecision(
                step_id=step.step_id,
                capability_id=step.capability_id,
                outcome=PolicyOutcome.DENY,
                reason_code="LOCAL_UPDATE_CONTRACT_INVALID",
                explanation=(
                    "Nexuss self-update requires an exact changed SHA pair "
                    "on the approved development branch."
                ),
            )

    if step.capability_id in {
        "engineering.build_artifact",
        "engineering.repair_failed_build",
    }:
        manifest = get_capability(step.capability_id)
        if manifest is None:
            return PolicyDecision(
                step_id=step.step_id,
                capability_id=step.capability_id,
                outcome=PolicyOutcome.DENY,
                reason_code="CAPABILITY_NOT_REGISTERED",
                explanation="Unregistered engineering capabilities cannot execute in Nexuss.",
            )
        if manifest.status is CapabilityStatus.PROHIBITED:
            return PolicyDecision(
                step_id=step.step_id,
                capability_id=step.capability_id,
                outcome=PolicyOutcome.DENY,
                reason_code="CAPABILITY_REGISTRY_PROHIBITED",
                explanation=(
                    "The capability registry marks this engineering capability as prohibited."
                ),
            )
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.REQUIRE_APPROVAL,
            reason_code="DEVELOPER_ENGINEERING_MISSION_APPROVAL_REQUIRED",
            explanation=(
                "This high-risk Developer Engineering mission requires one explicit "
                "desktop approval bound to the exact task payload. After approval, "
                "ordinary isolated inspection, implementation, targeted repair, and "
                "deterministic verification inside that mission do not require repeated "
                "approval. Budget increases, trust-boundary expansion, Constitution or "
                "vault/credential access, permission expansion, destructive migration, "
                "and publication remain separately approval-bound."
            ),
        )

    manifest = get_capability(step.capability_id)
    if manifest is None:
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.DENY,
            reason_code="CAPABILITY_NOT_REGISTERED",
            explanation="Unregistered capabilities cannot execute in Nexuss.",
        )

    if manifest.status is CapabilityStatus.PROHIBITED:
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.DENY,
            reason_code="CAPABILITY_REGISTRY_PROHIBITED",
            explanation="The capability registry marks this capability as prohibited.",
        )

    if manifest.approval_policy is ApprovalPolicy.EXPLICIT:
        phone_required = manifest.approval_channel is ApprovalChannel.PHONE
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.REQUIRE_APPROVAL,
            reason_code=(
                "TRUSTED_PHONE_APPROVAL_REQUIRED"
                if phone_required
                else "EXPLICIT_USER_APPROVAL_REQUIRED"
            ),
            explanation=(
                "This trusted-device command requires approval from a paired phone bound to "
                "the requesting Nexuss session and the exact payload hash."
                if phone_required
                else (
                    "This controlled write is authorized only after the user approves the exact "
                    "payload bound to the current authenticated session."
                )
            ),
        )

    if (
        step.capability_id == "assistant.respond"
        and step.parameters.get("response_key")
    ):
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.ALLOW,
            reason_code="CONSTITUTIONAL_INFORMATIONAL_RESPONSE",
            explanation=(
                "The active hash-verified Nexuss Constitution "
                "authorizes this informational response. It creates "
                "no external side effect and grants no authority."
            ),
        )

    if manifest.approval_policy is ApprovalPolicy.NONE:
        reason_code = (
            "INFORMATIONAL_NO_SIDE_EFFECT"
            if manifest.execution_mode == "deterministic_local"
            else "REGISTERED_READ_ONLY_OR_SIMULATED"
        )
        return PolicyDecision(
            step_id=step.step_id,
            capability_id=step.capability_id,
            outcome=PolicyOutcome.ALLOW,
            reason_code=reason_code,
            explanation="The registered capability has no approved external side effect.",
        )

    return PolicyDecision(
        step_id=step.step_id,
        capability_id=step.capability_id,
        outcome=PolicyOutcome.DENY,
        reason_code="FAIL_CLOSED_POLICY_CONFIGURATION",
        explanation="No explicit policy outcome authorizes this capability.",
    )
