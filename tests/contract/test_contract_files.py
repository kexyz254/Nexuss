"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_json_schemas_are_valid_and_fail_closed() -> None:
    names = [
        "task-request.schema.json",
        "capability-result.schema.json",
        "action-receipt.schema.json",
        "approval-decision.schema.json",
    ]
    for name in names:
        data = json.loads((ROOT / "contracts" / "schemas" / name).read_text(encoding="utf-8"))
        assert data["$schema"].endswith("2020-12/schema")
        assert data["additionalProperties"] is False


def test_ats_connector_is_readonly_named() -> None:
    assert (ROOT / "connectors" / "ats-readonly").is_dir()


def test_p3_openapi_declares_approval_rollback_and_receipt_history() -> None:
    contract = (ROOT / "contracts" / "openapi" / "core-api.yaml").read_text(encoding="utf-8")

    assert "/v1/tasks/{task_id}/approval:" in contract
    assert "/v1/tasks/{task_id}/rollback:" in contract
    assert "/v1/tasks/{task_id}/receipt:" in contract
    assert "/v1/tasks/{task_id}/receipts:" in contract
    assert "approval-decision.schema.json" in contract
    assert "ats.write" not in contract
