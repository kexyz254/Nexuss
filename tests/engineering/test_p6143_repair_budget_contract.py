from pathlib import Path


def test_repair_path_is_single_call_write_required_and_fail_closed():
    root = Path(__file__).resolve().parents[2]
    source = (root / "src/nexuss/engineering/prompt_build.py").read_text(
        encoding="utf-8-sig"
    )
    assert 'phase="write_required"' in source
    assert "allowed=(ToolName.WRITE_FILE,)" in source
    assert "provider_calls = 1" in source
    assert "allowed_repair_paths = set(workspace.changed_files)" in source
    assert "ENGINEERING_ECONOMIC_NO_PROGRESS" in source
    assert "_assert_candidate_baseline_matches_live" in source
