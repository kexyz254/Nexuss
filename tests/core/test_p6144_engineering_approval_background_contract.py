from pathlib import Path


def test_engineering_approval_is_specific_and_backgrounded():
    root = Path(__file__).resolve().parents[2]
    source = (root / "src/nexuss/core/service.py").read_text(
        encoding="utf-8-sig"
    )
    assert '"engineering.repair_failed_build"' in source
    assert '"engineering.build_artifact"' in source
    assert "Nexuss · Developer Engineering" in source
    assert "if self._is_background_engineering_plan(task.plan):" in source
    assert "normal isolated work inside this mission does not request it again" in source
