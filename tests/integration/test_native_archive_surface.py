from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_native_archive_route_and_two_phase_mobile_routing_exist() -> None:
    app_path = ROOT / "src/nexuss/api/app.py"
    tree = ast.parse(
        app_path.read_text(encoding="utf-8"),
        filename=str(app_path),
    )
    routes: dict[tuple[str, str], str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            function = decorator.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr in {"get", "post", "delete"}
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                routes[
                    (function.attr.upper(), decorator.args[0].value)
                ] = node.name

    assert routes[("POST", "/v1/archive-imports")] == (
        "create_archive_import"
    )
    assert routes[("GET", "/v1/mobile/pending")] == (
        "get_mobile_pending_approvals"
    )
    assert routes[
        ("POST", "/v1/mobile/tasks/{task_id}/decision")
    ] == "decide_mobile_approval"


def test_desktop_surface_has_zip_picker_and_raw_upload() -> None:
    html = (
        ROOT / "src/nexuss/ui/index.html"
    ).read_text(encoding="utf-8")
    javascript = (
        ROOT / "src/nexuss/ui/app.js"
    ).read_text(encoding="utf-8")

    assert 'id="archive-input"' in html
    assert 'accept=".zip,application/zip' in html
    assert 'id="archive-attachment"' in html
    assert 'fetch("/v1/archive-imports"' in javascript
    assert '"Content-Type": "application/zip"' in javascript
    assert '"X-Nexuss-Repository-Name"' in javascript
    assert "repositoryNameFromInstruction" in javascript
    assert "selectedArchive" in javascript
