from pathlib import Path


def test_development_package_attachment_route_exists():
    source = (Path(__file__).resolve().parents[2] / "src" / "nexuss" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "executeDevelopmentPackageInstruction" in source
    assert 'fetch("/v1/development-packages"' in source
    assert "isDevelopmentPackageInstruction" in source
    assert "No LLM/API call is required" in source
    assert "P6.13 ASYNC PACKAGE APPROVAL POLLING" in source
    assert "developmentPackageTask" in source
