from nexuss.policy.developer import ApprovalMode, DeveloperPolicy, RiskLevel


def test_durable_policy_covers_build_repair_and_acceptance():
    policy = DeveloperPolicy()
    assert policy.risk_for("engineering.build_artifact").risk is RiskLevel.HIGH
    assert policy.risk_for("engineering.repair_failed_build").risk is RiskLevel.HIGH
    assert policy.risk_for("engineering.verify_acceptance").risk is RiskLevel.LOW

    assert policy.requires_approval("engineering.build_artifact") is True
    assert policy.requires_approval("engineering.repair_failed_build") is True
    assert policy.requires_approval("engineering.verify_acceptance") is False


def test_high_risk_mission_entry_stays_approval_bound_even_if_mode_none():
    policy = DeveloperPolicy(approval_mode=ApprovalMode.NONE)
    assert policy.requires_approval("engineering.build_artifact") is True
    assert policy.requires_approval("engineering.repair_failed_build") is True
    assert policy.requires_approval("engineering.verify_acceptance") is False
