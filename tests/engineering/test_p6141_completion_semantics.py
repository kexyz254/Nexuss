from pathlib import Path


def test_regression_success_requires_post_restart_acceptance_wording():
    root = Path(__file__).resolve().parents[2]
    source = (root / "src/nexuss/engineering/prompt_build.py").read_text(
        encoding="utf-8-sig"
    )
    assert "requirement-level acceptance verification" in source
    assert "post_restart_verification_required" in source
