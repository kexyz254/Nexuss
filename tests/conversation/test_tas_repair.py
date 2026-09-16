import json
import io
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexuss.conversation.tas_repair import (
    DockerValidator, EXISTING_TEST, REGRESSION, SOURCE, prepare_repair, review_repair,
)
from nexuss.conversation.tas_workflow import InvestigationStore


def setup_run(tmp_path):
    store = InvestigationStore(tmp_path / "workflow.db")
    run_id = store.create("owner")
    store.save(run_id, "owner", "Engineering / source", "completed", {"commit": "a" * 40})
    now = datetime.now(timezone.utc).isoformat()
    store.save(run_id, "owner", "Research / incident", "completed", {"reason_code": "execution_errors", "retrieved_at": now})
    store.save(run_id, "owner", "Maintenance / health", "completed", {"score": 40, "retrieved_at": now})
    return store, run_id


def candidate():
    return {"defect_found": True, "diagnosis": "Synthetic regression fixture, not a TAS diagnosis",
            "replacement": "def result():\n    return 2\n",
            "regression_test": "def test_result():\n    assert True\n"}


def loader(commit):
    assert commit == "a" * 40
    return Path("unused"), {SOURCE: "def result():\n    return 1\n", EXISTING_TEST: ""}


def proposer(values):
    remaining = iter(values)
    return lambda request: SimpleNamespace(done=True, tool_requests=(), completion_message=json.dumps(next(remaining)))


def test_proposal_review_and_validation_receipts(tmp_path):
    store, run_id = setup_run(tmp_path)
    calls = []
    class Validator:
        def validate(self, root, value):
            calls.append(value)
            return {"passed": True, "scope": "mock runner"}
    factory = lambda: proposer([candidate(), {"acceptable": True, "reason": "Fixture accepted"}])
    text = prepare_repair(store, run_id, "owner", factory, loader=loader, validator_factory=Validator)
    assert "passed targeted isolated validation" in text
    assert len(calls) == 1
    assert "def result" in review_repair(store, run_id, "owner")
    assert "already has a candidate" in prepare_repair(store, run_id, "owner", factory)
    with pytest.raises(ValueError):
        review_repair(store, run_id, "other")


def test_rejected_review_never_runs_candidate(tmp_path):
    store, run_id = setup_run(tmp_path)
    class Validator:
        def validate(self, *args):
            raise AssertionError("Rejected candidate must not execute")
    text = prepare_repair(store, run_id, "owner",
        lambda: proposer([candidate(), {"acceptable": False, "reason": "Weakens safety"}]),
        loader=loader, validator_factory=Validator)
    assert "rejected" in text
    assert "Validation / repair" not in store.get(run_id, "owner")


def test_no_defect_is_not_a_patch(tmp_path):
    store, run_id = setup_run(tmp_path)
    value = {"defect_found": False, "diagnosis": "No supported defect", "replacement": "", "regression_test": ""}
    text = prepare_repair(store, run_id, "owner", lambda: proposer([value]), loader=loader,
                          validator_factory=lambda: object())
    assert "no justified code defect" in text


def test_isolation_failure_prevents_provider_call(tmp_path):
    store, run_id = setup_run(tmp_path)
    def fail():
        raise ValueError("api_key=do-not-display")
    text = prepare_repair(store, run_id, "owner", lambda: pytest.fail("provider called"), validator_factory=fail)
    assert "blocked" in text
    assert "do-not-display" not in text
    assert "do-not-display" not in json.dumps(store.get(run_id, "owner"))


def test_validation_requires_baseline_failure_and_candidate_success(tmp_path):
    root = tmp_path / "snapshot"
    for path in (SOURCE, EXISTING_TEST):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# fixture\n")
    validator = object.__new__(DockerValidator)
    calls = []
    results = iter([0, 1, 0])
    def run(workspace, paths):
        calls.append(paths)
        assert not (workspace / ".env").exists()
        return {"exit_code": next(results)}
    (root / ".env").write_text("secret=not-copied")
    validator.run = run
    assert validator.validate(root, candidate())["passed"] is True
    assert calls == [[EXISTING_TEST], [REGRESSION], [EXISTING_TEST, REGRESSION]]
    validator.run = lambda *args: {"exit_code": 2}
    assert validator.validate(root, candidate())["passed"] is False


def test_unpinned_image_rejected():
    with pytest.raises(ValueError):
        DockerValidator("python:latest")


def test_stale_evidence_blocks_preparation_before_model_or_tests(tmp_path):
    store, run_id = setup_run(tmp_path)
    store.save(run_id, "owner", "Maintenance / health", "completed",
               {"score": 40, "retrieved_at": "2000-01-01T00:00:00+00:00"})
    text = prepare_repair(store, run_id, "owner", lambda: pytest.fail("Model must not run"))
    assert "must be recent" in text


def test_credential_shaped_source_blocks_model_disclosure(tmp_path):
    store, run_id = setup_run(tmp_path)
    def secret_source(commit):
        return Path("unused"), {SOURCE: 'password = "do-not-send-this"', EXISTING_TEST: ""}
    text = prepare_repair(store, run_id, "owner",
        lambda: lambda request: pytest.fail("Secret was sent to provider"),
        loader=secret_source, validator_factory=lambda: object())
    assert "blocked" in text
    assert "Engineering / candidate" not in store.get(run_id, "owner")


def test_docker_command_has_fixed_isolation_and_no_shell(tmp_path, monkeypatch):
    import nexuss.conversation.tas_repair as module
    commands = []
    class Process:
        stdout = io.BytesIO(b"1 passed in 0.01s")
        def wait(self, timeout):
            return 0
        def poll(self):
            return 0
    def popen(command, **kwargs):
        commands.append(command)
        assert "shell" not in kwargs
        return Process()
    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: None)
    runner = object.__new__(DockerValidator)
    runner.image, runner.docker = "sha256:" + "a" * 64, "docker"
    assert runner.run(tmp_path, [EXISTING_TEST])["exit_code"] == 0
    command = commands[0]
    assert {"--network=none", "--read-only", "--cap-drop=ALL", "--pull=never", "--user=65532:65532"} <= set(command)
    assert command[-1] == EXISTING_TEST
