from __future__ import annotations

from pathlib import Path


def test_deterministic_routes_precede_provider_resolution() -> None:
    source = Path("src/nexuss/interactions/service.py").read_text(
        encoding="utf-8-sig"
    )
    deterministic = source.index("deterministic_route_result(")
    provider = source.index("self._providers.select(", deterministic)
    assert deterministic < provider
    assert "route_source = deterministic.source" in source
    assert "provider_assisted_router" in source
    assert "DeepSeek classified the turn" not in source


def test_original_user_text_remains_the_persisted_user_turn() -> None:
    source = Path("src/nexuss/interactions/service.py").read_text(
        encoding="utf-8-sig"
    )
    assert source.count("user_text=sanitized.value") >= 3
    assert '"original_user_text": sanitized.value' in source
    assert "resolved instruction entered Nexuss Core" in source
