import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException, Request

from nexuss.local_control.client import HttpLocalControlClient, LocalControlError
from nexuss.local_control.models import LocalUpdateResult


@pytest.fixture
def module():
    # Load the actual route without booting unrelated Windows DPAPI services.
    tree = ast.parse(Path("src/nexuss/api/app.py").read_text())
    route = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name == "runtime_update_result")
    namespace = {
        "app": FastAPI(), "Request": Request, "HTTPException": HTTPException,
        "HttpLocalControlClient": HttpLocalControlClient,
        "LocalControlError": LocalControlError, "os": os,
        "_require_local_control": Mock(),
    }
    exec(compile(ast.Module(body=[route], type_ignores=[]), "runtime_update_route", "exec"), namespace)  # noqa: S102 - trusted local route only
    return namespace


def test_result_endpoint_reports_running_process_and_enforces_local_control(monkeypatch, module):
    guard = Mock()
    monkeypatch.setitem(module, "_require_local_control", guard)
    monkeypatch.setenv("NEXUSS_BUILD_SHA", "b" * 40)
    result = LocalUpdateResult(status="completed", target_sha="a" * 40,
                              active_sha="a" * 40, detail="Restarted")
    monkeypatch.setattr(module["HttpLocalControlClient"], "from_environment", lambda: SimpleNamespace(
        update_result=lambda: result,
    ))
    request = Mock()
    response = module["runtime_update_result"](request)
    guard.assert_called_once_with(request)
    assert response["running_sha"] == "b" * 40
    assert response["active_sha"] == "a" * 40
    guard.side_effect = HTTPException(status_code=403)
    with pytest.raises(HTTPException) as denied:
        module["runtime_update_result"](request)
    assert denied.value.status_code == 403


def test_missing_connector_cannot_report_success(monkeypatch, module):
    monkeypatch.setitem(module, "_require_local_control", Mock())
    client = Mock()
    client.update_result.side_effect = LocalControlError("Unavailable")
    monkeypatch.setattr(module["HttpLocalControlClient"], "from_environment", lambda: client)
    with pytest.raises(HTTPException) as unavailable:
        module["runtime_update_result"](Mock())
    assert unavailable.value.status_code == 503
