"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from nexuss.device.client import HttpDeviceNodeClient
from nexuss.device.models import DeviceCommandEnvelope
from nexuss.device.signing import DeviceSignatureError, sign_payload, verify_signature
from nexuss.device_node.executor import WindowsNotepadExecutor
from tests.fakes import FakeRunner

SECRET = "a" * 48
TASK_ID = UUID("00000000-0000-0000-0000-000000000760")
COMMAND_ID = UUID("00000000-0000-0000-0000-000000000761")


def test_signed_device_envelope_detects_tampering() -> None:
    now = datetime.now(UTC)
    envelope = DeviceCommandEnvelope(
        command_id=COMMAND_ID,
        task_id=TASK_ID,
        capability_id="device.launch_notepad",
        target_node_id="windows-primary",
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        nonce="n" * 40,
        parameters={},
    )
    signature = sign_payload(envelope, SECRET)
    verify_signature(envelope, SECRET, signature)

    tampered = envelope.model_copy(update={"target_node_id": "different-node"})
    with pytest.raises(DeviceSignatureError, match="DEVICE_NODE_SIGNATURE_INVALID"):
        verify_signature(tampered, SECRET, signature)


def test_executor_launches_only_fixed_path_and_rolls_back_receipt_process(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    executable = (
        tmp_path / "Windows" / "System32" / "notepad.exe"
    ).resolve()

    executor = WindowsNotepadExecutor(
        node_id="windows-primary",
        executable=executable,
        runner=runner,
    )

    evidence = executor.launch(
        task_id=TASK_ID,
        command_id=COMMAND_ID,
        target_node_id="windows-primary",
    )

    assert runner.executables == [executable]
    assert evidence.verified_running is True
    assert evidence.process_id == 9001

    rollback = executor.rollback(
        rollback_id=UUID("00000000-0000-0000-0000-000000000762"),
        task_id=TASK_ID,
        command_id=COMMAND_ID,
        target_node_id="windows-primary",
    )

    assert rollback.terminated is True
    assert rollback.verified_absent is True


def test_device_client_rejects_non_loopback_transport() -> None:
    with pytest.raises(ValueError, match="loopback HTTP endpoint"):
        HttpDeviceNodeClient(
            base_url="http://192.168.1.20:8200",
            shared_secret=SECRET,
        )
