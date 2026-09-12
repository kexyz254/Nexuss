"""P6.12 launcher security contracts."""

from pathlib import Path


def test_launcher_keeps_node_loopback_and_secret_off_command_line() -> None:
    text = Path("scripts/start_nexuss_p612.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "127.0.0.1" in text
    assert "nexuss.device_node.app:app" in text
    assert "RandomNumberGenerator" in text
    assert "NEXUSS_DEVICE_NODE_SECRET" in text
    assert "Remove-Item Env:NEXUSS_DEVICE_NODE_SECRET" in text
    assert "--host" in text
    assert '"127.0.0.1"' in text
    assert 'NEXUSS_WINDOWS_NODE_ID' in text
    assert '"windows-primary"' in text
    assert '/health/ready' in text
    assert 'p5_trusted_windows_node' in text

    node_argument_start = text.index("$nodeArguments = @(")
    node_argument_end = text.index(")", node_argument_start)
    node_arguments = text[node_argument_start:node_argument_end]
    assert "DEVICE_NODE_SECRET" not in node_arguments
    assert "deviceSecret" not in node_arguments


def test_launcher_does_not_attempt_android_provider_bypass() -> None:
    text = Path("scripts/start_nexuss_p612.ps1").read_text(
        encoding="utf-8-sig"
    ).casefold()
    forbidden = (
        "adb shell",
        "fastboot",
        "usb debugging",
        "enable developer options",
        "bypass carrier",
        "bypass provider",
    )
    for token in forbidden:
        assert token not in text
