from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_routes_are_registered_in_production_app() -> None:
    text = (ROOT / "src/nexuss/api/app.py").read_text(encoding="utf-8")
    assert "register_google_workspace_routes(" in text
    assert "register_commitment_routes(" in text
    assert "CommitmentGoalExecutor(commitment_service)" in text
    assert '"p68a_unified_commitment_intelligence"' in text


def test_external_provider_writes_remain_prohibited() -> None:
    text = (ROOT / "src/nexuss/core/registry.py").read_text(
        encoding="utf-8"
    )
    assert 'capability_id="communications.external_write"' in text
    assert "ApprovalPolicy.PROHIBITED" in text
    assert "CapabilityStatus.PROHIBITED" in text
