from __future__ import annotations

from nexuss.cognitive.runtime import (
    _COGNITIVE_INSTRUCTION_LIMIT,
    _COGNITIVE_TRUNCATION_MARKER,
    bound_cognitive_instruction,
)
from nexuss.engineering.models import EngineeringTaskSpec


def test_oversized_file_context_is_bounded_before_engineering_contract() -> None:
    instruction = (
        "Inspect this ZIP and summarize the important files.\n\n"
        + "A" * 25_000
        + "\nTAIL-EVIDENCE"
    )

    bounded = bound_cognitive_instruction(instruction)

    assert len(bounded) <= _COGNITIVE_INSTRUCTION_LIMIT
    assert _COGNITIVE_TRUNCATION_MARKER in bounded
    assert bounded.startswith("Inspect this ZIP")
    assert bounded.endswith("TAIL-EVIDENCE")

    task = EngineeringTaskSpec(
        goal=bounded,
        provider_id="deepseek",
    )
    assert task.goal == bounded
