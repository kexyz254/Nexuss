"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

import json
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_json_schemas_are_valid_json() -> None:
    for name in ["task-request.schema.json", "capability-result.schema.json"]:
        data = json.loads((ROOT / "contracts" / "schemas" / name).read_text())
        assert data["$schema"].endswith("2020-12/schema")
        assert data["additionalProperties"] is False


def test_ats_connector_is_readonly_named() -> None:
    assert (ROOT / "connectors" / "ats-readonly").is_dir()
