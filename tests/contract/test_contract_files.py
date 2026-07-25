"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_json_schemas_are_valid_json() -> None:
    names = [
        "task-request.schema.json",
        "capability-result.schema.json",
        "action-receipt.schema.json",
    ]
    for name in names:
        data = json.loads((ROOT / "contracts" / "schemas" / name).read_text(encoding="utf-8"))
        assert data["$schema"].endswith("2020-12/schema")
        assert data["additionalProperties"] is False


def test_ats_connector_is_readonly_named() -> None:
    assert (ROOT / "connectors" / "ats-readonly").is_dir()


def test_p1_openapi_declares_receipt_endpoint() -> None:
    contract = (ROOT / "contracts" / "openapi" / "core-api.yaml").read_text(encoding="utf-8")
    assert "/v1/tasks/{task_id}/receipt:" in contract
    assert "ats.write" not in contract
