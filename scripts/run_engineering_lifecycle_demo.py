from __future__ import annotations

import json
import tempfile
from pathlib import Path
from uuid import uuid4

from nexuss.engineering.lifecycle import (
    EngineeringArtifactValidator,
    EngineeringTaskLifecycle,
    EngineeringValidationPolicy,
)
from nexuss.engineering.models import (
    EngineeringRunReceipt,
    EngineeringTaskSpec,
    ProviderKind,
    TaskSensitivity,
    WorkspaceKind,
)
from nexuss.engineering.provider_connections import (
    ProviderAccessCode,
    ProviderAccessDecision,
)
from nexuss.engineering.publication import (
    EngineeringPublicationPlanner,
)
from nexuss.engineering.store import (
    JsonEngineeringLifecycleStore,
)
from nexuss.engineering.workspace import IsolatedWorkspace


def _offline_executor(
    task: EngineeringTaskSpec,
    workspace: IsolatedWorkspace,
) -> EngineeringRunReceipt:
    workspace.write_text(
        "index.html",
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nexuss AI</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <main>
    <section class="hero">
      <p class="eyebrow">Human-authorized digital operations</p>
      <h1>Nexuss AI</h1>
      <p>Plan, verify, approve, execute, and prove.</p>
      <a href="#capabilities">Explore capabilities</a>
    </section>
    <section id="capabilities">
      <h2>Governed by design</h2>
      <p>Models reason. Deterministic systems act. You approve.</p>
    </section>
  </main>
</body>
</html>
""",
    )
    workspace.write_text(
        "styles.css",
        """:root {
  color-scheme: dark;
  font-family: Inter, system-ui, sans-serif;
}
body {
  margin: 0;
  background: #08111f;
  color: #f5f7fb;
}
main {
  min-height: 100vh;
}
.hero, #capabilities {
  max-width: 72rem;
  margin: 0 auto;
  padding: 6rem 2rem;
}
a {
  color: inherit;
}
""",
    )
    return EngineeringRunReceipt(
        task_id=task.task_id,
        provider_id="offline-verification-fixture",
        provider_kind=ProviderKind.LOCAL,
        workspace_kind=WorkspaceKind.LOCAL,
        rounds=1,
        completed=True,
        changed_files=workspace.changed_files,
        tool_results=(),
        final_message="Offline lifecycle fixture completed.",
        credentials_exposed=False,
        external_processing_used=False,
    )


def main() -> int:
    task = EngineeringTaskSpec(
        goal=(
            "Exercise the Nexuss engineering lifecycle without "
            "contacting a paid provider or GitHub."
        ),
        provider_id="offline-verification-fixture",
        sensitivity=TaskSensitivity.PUBLIC,
        external_processing_approved=False,
        max_files_changed=2,
    )
    access = ProviderAccessDecision(
        provider_id="offline-verification-fixture",
        provider_kind=ProviderKind.LOCAL,
        available=True,
        optional=True,
        code=ProviderAccessCode.READY,
        user_message=(
            "Offline deterministic lifecycle fixture is ready."
        ),
        model="deterministic-fixture-v1",
        identity_verified=True,
        billing_ready=True,
        credential_present=False,
        credentials_exposed=False,
    )

    base = (
        Path(tempfile.gettempdir())
        / "nexuss-engineering-lifecycle"
        / str(uuid4())
    )
    workspace = IsolatedWorkspace(base / "workspace")
    lifecycle = EngineeringTaskLifecycle(
        validator=EngineeringArtifactValidator(
            EngineeringValidationPolicy(
                require_landing_page_contract=True,
                block_external_web_references=True,
            )
        )
    )
    outcome = lifecycle.execute(
        task,
        access,
        _offline_executor,
        lambda: workspace,
    )
    if outcome.review is None:
        raise SystemExit(outcome.message)

    proposal = EngineeringPublicationPlanner.prepare_github(
        outcome.review,
        account_login="kexyz254",
        repository_name="Nexuss-AI",
        branch="main",
        commit_message="feat: add Nexuss AI landing page",
    )
    store = JsonEngineeringLifecycleStore(base / "records")
    record_path = store.save(outcome)

    print()
    print("=" * 72)
    print("NEXUSS ENGINEERING TASK LIFECYCLE")
    print("=" * 72)
    print(f"Task state:          {outcome.state.value}")
    print(f"Workspace:           {workspace.root}")
    print(f"Changed files:       {len(outcome.review.artifacts)}")
    print(
        f"Validation passed:   "
        f"{outcome.review.validation.passed}"
    )
    print(f"Diff SHA-256:        {outcome.review.diff_sha256}")
    print(f"Publication account: {proposal.account_login}")
    print(f"Repository:          {proposal.repository_name}")
    print(f"Branch:              {proposal.branch}")
    print(f"Approval channel:    {proposal.approval_channel}")
    print(f"Payload SHA-256:     {proposal.payload_sha256}")
    print(f"Lifecycle record:    {record_path}")
    print("Phone approved:      False")
    print("GitHub changed:      False")
    print("Published:           False")
    print("Credentials exposed: False")

    preview_path = base / "PUBLICATION-PREVIEW.json"
    preview_path.write_text(
        json.dumps(
            proposal.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"Publication preview: {preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
