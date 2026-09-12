"""Durable Developer Engineering Policy.

P6.14 — replaces launcher-only self-build enablement with a durable policy
covering self-build, verified live apply, external engineering provider
access, approval mode, and economic-budget requirements.

Nexuss remains authoritative. The engineering provider (e.g. DeepSeek) cannot
raise its budget, approve itself, expand permissions, publish Git changes, or
mark its own work verified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import FrozenSet, Optional


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalMode(Enum):
    NONE = "none"
    PER_MISSION = "per_mission"
    PER_ACTION = "per_action"


@dataclass(frozen=True)
class CapabilityRisk:
    """Risk classification for a capability/action."""

    name: str
    risk: RiskLevel
    requires_approval: bool = True


# engineering.build_artifact is HIGH risk.
CAPABILITY_RISKS: FrozenSet[CapabilityRisk] = frozenset(
    {
        CapabilityRisk("engineering.build_artifact", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.repair_failed_build", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.verify_acceptance", RiskLevel.LOW, False),
        CapabilityRisk("engineering.inspect", RiskLevel.LOW, False),
        CapabilityRisk("engineering.isolated_write", RiskLevel.MEDIUM, True),
        CapabilityRisk("engineering.implement", RiskLevel.MEDIUM, True),
        CapabilityRisk("engineering.targeted_repair", RiskLevel.MEDIUM, True),
        CapabilityRisk("engineering.deterministic_test", RiskLevel.LOW, False),
        CapabilityRisk("engineering.budget_increase", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.trust_boundary_expansion", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.constitution_access", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.vault_access", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.credential_access", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.permission_expansion", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.destructive_migration", RiskLevel.HIGH, True),
        CapabilityRisk("engineering.publication", RiskLevel.HIGH, True),
    }
)

_RISK_BY_NAME = {c.name: c for c in CAPABILITY_RISKS}


@dataclass(frozen=True)
class DeveloperPolicy:
    """Durable developer engineering policy configuration."""

    self_build_enabled: bool = False
    verified_live_apply_required: bool = True
    external_provider_access: bool = False
    approval_mode: ApprovalMode = ApprovalMode.PER_MISSION
    soft_budget_usd: Decimal = Decimal("1.00")
    hard_budget_usd: Decimal = Decimal("5.00")
    max_paid_calls: int = 6
    max_discovery_calls: int = 2
    max_repair_calls: int = 3

    def risk_for(self, capability: str) -> Optional[CapabilityRisk]:
        return _RISK_BY_NAME.get(capability)

    def requires_approval(self, capability: str) -> bool:
        risk = self.risk_for(capability)
        if risk is None:
            # Unknown capabilities fail closed.
            return True

        # These are the mission entry points. They always require one exact
        # governed approval regardless of launcher environment or approval-mode
        # convenience settings.
        if capability in {
            "engineering.build_artifact",
            "engineering.repair_failed_build",
        }:
            return True

        # Explicitly read-only / no-approval capabilities stay approval-free.
        # This includes deterministic acceptance verification.
        if not risk.requires_approval:
            return False

        if self.approval_mode == ApprovalMode.NONE:
            return False
        if self.approval_mode == ApprovalMode.PER_ACTION:
            return True

        # PER_MISSION: once the exact mission is approved, ordinary isolated
        # work inside it does not request repeated approval.
        normal = {
            "engineering.inspect",
            "engineering.isolated_write",
            "engineering.implement",
            "engineering.targeted_repair",
            "engineering.deterministic_test",
        }
        if capability in normal:
            return False
        return True


def requires_new_approval(capability: str) -> bool:
    """Return True for capabilities that always require a NEW approval even
    within an already-approved mission."""
    always_new = {
        "engineering.budget_increase",
        "engineering.trust_boundary_expansion",
        "engineering.constitution_access",
        "engineering.vault_access",
        "engineering.credential_access",
        "engineering.permission_expansion",
        "engineering.destructive_migration",
        "engineering.publication",
    }
    return capability in always_new
