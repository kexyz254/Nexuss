from pathlib import Path


def test_core_health_and_assets_expose_runtime_truth_contract() -> None:
    source = Path("src/nexuss/api/app.py").read_text(encoding="utf-8")

    assert '"build_sha": os.getenv("NEXUSS_BUILD_SHA", "unknown")' in source
    assert '"build_branch": os.getenv("NEXUSS_BUILD_BRANCH", "unknown")' in source
    assert '"ui_contract": "p621_runtime_truth_progress"' in source
    assert 'request.url.path.startswith("/assets/")' in source
    assert 'response.headers["Cache-Control"] = "no-store"' in source
    assert '@app.get("/v1/runtime/build")' in source
    assert "HttpLocalControlClient.from_environment().inspect_update()" in source


def test_launcher_propagates_same_git_identity_to_runtime() -> None:
    source = Path("scripts/start_p5.ps1").read_text(encoding="utf-8")

    assert "$BuildSha = (git rev-parse HEAD).Trim()" in source
    assert "$BuildBranch = (git branch --show-current).Trim()" in source
    assert source.count("NEXUSS_BUILD_SHA") >= 3
    assert source.count("NEXUSS_BUILD_BRANCH") >= 3
    assert 'Write-Host "Build:   $BuildSha"' in source
