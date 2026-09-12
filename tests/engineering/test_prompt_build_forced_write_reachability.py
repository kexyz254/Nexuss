from pathlib import Path


def _source() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "src/nexuss/engineering/prompt_build.py").read_text(
        encoding="utf-8-sig"
    )


def test_zero_change_path_reaches_write_required_before_stopping():
    source = _source()

    assert 'phase = "write_required"' in source
    assert "if no_progress >= 3 and round_number >= 4:" not in source
    assert "forced_write_no_progress = 0" in source
    assert "if phase == \"write_required\":" in source
    assert "forced_write_no_progress >= 2" in source


def test_discovery_remains_bounded_before_forced_write():
    source = _source()

    assert "elif round_number <= 2:" in source
    assert "elif round_number <= 4:" in source
    assert "Browsing is closed." in source
