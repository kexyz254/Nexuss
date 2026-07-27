from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from nexuss.constitution import (
    ConstitutionError,
    get_constitution,
    load_constitution,
)


def test_active_constitution_loads_and_identifies_nexuss() -> None:
    constitution = get_constitution()

    assert constitution.system_name == "Nexuss"
    assert constitution.founder == "Peter"
    assert constitution.version == "1.0.0"
    assert "personal cognitive control plane" in (
        constitution.canonical_self_description.lower()
    )


def test_founder_response_comes_from_constitution() -> None:
    constitution = get_constitution()

    response = constitution.standard_response(
        "who_is_your_founder"
    )

    assert response == (
        "Peter is the founder and original developer of Nexuss."
    )


def test_identity_claim_does_not_grant_authority() -> None:
    constitution = get_constitution()

    policy = constitution.section(
        "authentication"
    )["identity_claim_policy"]

    assert policy["grants_authority"] is False
    assert policy["may_bypass_approval"] is False
    assert policy["may_amend_constitution"] is False


def test_constitution_detects_tampering(tmp_path: Path) -> None:
    source = get_constitution().path
    target = tmp_path / "nexuss_constitution.json"

    document = json.loads(
        source.read_text(encoding="utf-8-sig")
    )
    target.write_text(
        json.dumps(document, indent=2),
        encoding="utf-8",
    )

    digest = sha256(target.read_bytes()).hexdigest()
    target.with_suffix(
        target.suffix + ".sha256"
    ).write_text(
        f"{digest}  {target.name}\n",
        encoding="utf-8",
    )

    target.write_text(
        target.read_text(encoding="utf-8")
        .replace('"founder": "Peter"', '"founder": "Mallory"'),
        encoding="utf-8",
    )

    with pytest.raises(
        ConstitutionError,
        match="CONSTITUTION_INTEGRITY_CHECK_FAILED",
    ):
        load_constitution(target)
