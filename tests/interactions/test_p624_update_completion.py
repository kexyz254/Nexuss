from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from nexuss.interactions import service as module
from nexuss.local_control.models import LocalUpdateResult


@pytest.mark.parametrize(
    ("status", "active", "running", "target", "expected"),
    [
        ("completed", "a", "a", "a", "restarted runtime is running"),
        ("completed", "a", "b", "a", "accepted"),
        ("completed", "b", "a", "a", "accepted"),
        ("completed", "a", "a", "b", "accepted"),
        ("rolled_back", "b", "b", "a", "rolled back"),
        ("recovery_failed", "b", "b", "a", "recovery failed"),
    ],
)
def test_refresh_persists_only_matching_verified_restart(
    monkeypatch, status, active, running, target, expected,
):
    session = uuid4()
    stored = SimpleNamespace(
        conversation=SimpleNamespace(user_session_id=session),
        core_task_id=uuid4(), conversation_id=uuid4(),
        display_text="Update accepted",
        assistant_message=SimpleNamespace(message_id=uuid4(), text="Update accepted"),
        model_copy=lambda *, update: SimpleNamespace(**update),
    )
    task = SimpleNamespace(
        state="completed", results=[],
        plan=SimpleNamespace(steps=[SimpleNamespace(
            capability_id="system.update.apply",
            parameters={"expected_target_sha": "a" * 40},
        )]),
    )
    result = LocalUpdateResult(
        status=status, target_sha=target * 40, active_sha=active * 40, detail="Health check",
    )
    monkeypatch.setenv("NEXUSS_BUILD_SHA", running * 40)
    monkeypatch.setattr(module.HttpLocalControlClient, "from_environment", lambda: SimpleNamespace(
        update_result=lambda: result,
    ))
    monkeypatch.setattr(module, "InteractionPresentation", lambda **kw: kw)
    conversations = Mock()
    interactions = Mock()
    interactions.get.return_value = stored
    core = Mock()
    core.get_task.return_value = task
    core.get_receipt.return_value = None
    service = module.UnifiedInteractionService(
        providers=Mock(), resolver=Mock(), conversation_store=conversations,
        interaction_store=interactions, core_service=core,
    )
    updated = service.refresh(interaction_id=uuid4(), user_session_id=session)
    assert expected in updated.display_text
    interactions.save.assert_called_once_with(updated)
    if expected == "accepted":
        conversations.update_message_text.assert_not_called()
    else:
        assert conversations.update_message_text.call_args.kwargs["text"] == updated.display_text
