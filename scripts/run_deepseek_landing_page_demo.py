from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from nexuss.connectors.vault import DpapiSecretVault
from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import (
    EngineeringTaskSpec,
    TaskSensitivity,
    ToolName,
)
from nexuss.engineering.orchestrator import (
    EngineeringOrchestrator,
)
from nexuss.engineering.provider_connections import (
    EngineeringProviderConnectionService,
)
from nexuss.engineering.workspace import IsolatedWorkspace


class _LandingPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.has_title = False
        self.has_main = False
        self.has_h1 = False
        self.external_script = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.casefold()
        if normalized == "title":
            self.has_title = True
        elif normalized == "main":
            self.has_main = True
        elif normalized == "h1":
            self.has_h1 = True
        elif normalized == "script":
            values = {
                key.casefold(): value or ""
                for key, value in attrs
            }
            if values.get("src"):
                self.external_script = True


def _validate(
    root: Path,
    files: tuple[str, ...],
) -> dict[str, object]:
    allowed = {"index.html", "styles.css"}
    unexpected = sorted(set(files) - allowed)
    missing = sorted(allowed - set(files))
    if unexpected or missing:
        raise RuntimeError(
            "Landing-page file contract failed. "
            f"Missing={missing}; unexpected={unexpected}"
        )

    html = (root / "index.html").read_text(
        encoding="utf-8"
    )
    css = (root / "styles.css").read_text(
        encoding="utf-8"
    )

    parser = _LandingPageParser()
    parser.feed(html)

    lowered = (html + "\n" + css).casefold()
    prohibited = (
        "http://",
        "https://",
        "fetch(",
        "xmlhttprequest",
        "google-analytics",
        "googletagmanager",
        "gtag(",
        "facebook.com/tr",
        "<iframe",
    )
    detected = [
        marker
        for marker in prohibited
        if marker in lowered
    ]

    checks = {
        "title": parser.has_title,
        "main_landmark": parser.has_main,
        "primary_heading": parser.has_h1,
        "external_script_absent": (
            not parser.external_script
        ),
        "external_network_references_absent": (
            not detected
        ),
        "css_nonempty": bool(css.strip()),
        "file_contract": not unexpected and not missing,
    }
    if not all(checks.values()):
        raise RuntimeError(
            "Landing-page validation failed: "
            + json.dumps(checks, sort_keys=True)
        )
    return checks


def main() -> int:
    service = EngineeringProviderConnectionService(
        DpapiSecretVault()
    )
    access = service.deepseek_access()

    if not access.available:
        print()
        print("=" * 68)
        print("NEXUSS ENGINEERING CAPABILITY")
        print("=" * 68)
        print("Provider:        DeepSeek")
        print(f"Access:          {access.code.value}")
        print(f"Message:         {access.user_message}")
        print("Nexuss operational: True")
        print("Workspace created:  False")
        print("GitHub changed:      False")
        print("Published:           False")
        print("Key exposed:         False")
        return 2

    local_app_data = os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise SystemExit("LOCALAPPDATA is unavailable.")

    timestamp = datetime.now(UTC).strftime(
        "%Y%m%d-%H%M%S"
    )
    root = (
        Path(local_app_data)
        / "Nexuss"
        / "engineering-runs"
        / f"deepseek-landing-{timestamp}"
    )
    workspace = IsolatedWorkspace(root)

    task = EngineeringTaskSpec(
        goal=(
            "Create a self-contained, professional, responsive "
            "landing page for Nexuss AI. Create exactly two files: "
            "index.html and styles.css. Use semantic HTML, a strong "
            "hero section, concise product positioning, capability "
            "cards, governance messaging, and a clear call to action. "
            "Do not use external scripts, external fonts, analytics, "
            "trackers, remote images, forms, network calls, or inline "
            "JavaScript. Reference styles.css from index.html."
        ),
        provider_id="deepseek",
        sensitivity=TaskSensitivity.PUBLIC,
        external_processing_approved=False,
        allowed_tools=(
            ToolName.LIST_FILES,
            ToolName.READ_FILE,
            ToolName.WRITE_FILE,
        ),
        max_rounds=8,
        max_files_changed=2,
        max_runtime_seconds=300,
    )

    try:
        orchestrator = EngineeringOrchestrator(
            service.build_deepseek_router()
        )
        receipt = orchestrator.run(task, workspace)
    except EngineeringError as exc:
        print()
        print(f"STOPPED: {exc.code}")
        print(exc.message)
        print("Nexuss operational: True")
        print("GitHub changed:      False")
        print("Published:           False")
        return 3

    checks = _validate(root, receipt.changed_files)

    receipt_path = root / "NEXUSS-RUN-RECEIPT.json"
    receipt_path.write_text(
        json.dumps(
            {
                "engineering_receipt": receipt.model_dump(
                    mode="json"
                ),
                "validation": checks,
                "publication": {
                    "github_changed": False,
                    "published": False,
                    "phone_approval_used": False,
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 68)
    print("NEXUSS DEEPSEEK LANDING-PAGE WORKSPACE")
    print("=" * 68)
    print(f"Provider:       {receipt.provider_id}")
    print(f"Model:          {access.model}")
    print(f"Completed:      {receipt.completed}")
    print(f"Rounds:         {receipt.rounds}")
    print(
        "Changed files:  "
        + ", ".join(receipt.changed_files)
    )
    print(f"Workspace:      {root}")
    print(f"Receipt:        {receipt_path}")
    print("Validation:     passed")
    print("GitHub changed: False")
    print("Published:      False")
    print("Key exposed:    False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
