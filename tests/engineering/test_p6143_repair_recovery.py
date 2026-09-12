import json
import zipfile
from pathlib import Path

from nexuss.engineering.prompt_build import _latest_failed_build_context


def test_latest_failed_candidate_and_matching_diagnostic_are_recovered(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    run = tmp_path / "Nexuss" / "engineering-runs" / "prompt-build-20260904-010101"
    workspace = run / "workspace"
    (workspace / ".git").mkdir(parents=True)
    progress = {
        "run_id": run.name,
        "core_task_id": "task-original",
        "goal": "implement P6.15 New Chat smoke slice",
        "phase": "failed",
        "terminal": True,
        "active": False,
    }
    (run / "progress.json").write_text(json.dumps(progress), encoding="utf-8")

    artifacts = tmp_path / "Nexuss" / "engineering-artifacts"
    artifacts.mkdir(parents=True)
    artifact = artifacts / "nexuss-prompt-build-20260904-010200.zip"
    manifest = {
        "format": "nexuss-prompt-build-v1",
        "goal": "implement P6.15 New Chat smoke slice",
        "success": False,
        "baseline_failures": ["FAILED tests/unit/test_constitution.py::known"],
        "post_failures": [
            "FAILED tests/unit/test_constitution.py::known",
            "FAILED tests/conversation/test_router.py::new",
        ],
        "new_failures": ["FAILED tests/conversation/test_router.py::new"],
        "changed_files": ["src/nexuss/conversation/store.py"],
    }
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("NEXUSS-BUILD-MANIFEST.json", json.dumps(manifest))
        archive.writestr("VALIDATION.txt", "one exact regression")

    recovered = _latest_failed_build_context()
    assert recovered["run_root"] == run
    assert recovered["workspace_root"] == workspace
    assert recovered["artifact"] == artifact
    assert recovered["manifest"]["new_failures"] == [
        "FAILED tests/conversation/test_router.py::new"
    ]
