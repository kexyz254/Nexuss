from __future__ import annotations

from pathlib import Path


def _app() -> str:
    return Path("src/nexuss/ui/app.js").read_text(
        encoding="utf-8-sig"
    )


def test_normal_submit_uses_unified_interaction_only() -> None:
    source = _app()
    start = source.index(
        'elements.form.addEventListener("submit", (event) => {'
    )
    end = source.index(
        'elements.input.addEventListener("keydown"',
        start,
    )
    submit = source[start:end]

    assert "submitUnifiedUserTurn(utterance, channel)" in submit
    assert "understandAndExecute(utterance, channel)" not in submit
    assert "/v1/understanding/resolve" not in submit


def test_unified_turn_preserves_original_text_and_prevents_duplicates() -> None:
    source = _app()
    start = source.index("async function submitUnifiedUserTurn(")
    end = source.index(
        'elements.form.addEventListener("submit", (event) => {',
        start,
    )
    implementation = source[start:end]

    assert "originalUserText" in implementation
    assert 'addMessage("user", originalUserText)' in implementation
    assert "nexussUnifiedTurnPromise" in implementation
    assert "No duplicate interaction was created" in implementation
    assert "executeInstruction(originalUserText, channel)" in implementation


def test_obsolete_p610c_bridge_is_removed() -> None:
    source = _app()
    assert "P6.11 REMOVED OBSOLETE P6.10C" in source
    assert "function isUnifiedMediaTask" not in source
    assert "function revealVerifiedMediaPresentation" not in source


def test_legacy_understanding_gateway_is_not_deleted() -> None:
    source = _app()
    assert 'fetch("/v1/understanding/resolve"' in source
    assert "legacyGatewayActiveForNormalSubmit: false" in source
