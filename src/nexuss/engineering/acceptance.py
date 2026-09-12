"""Deterministic read-only post-build engineering acceptance evidence."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from nexuss.core.registry import get_capability
from nexuss.engineering.prompt_build import latest_prompt_build_progress


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _safe_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""


def _tree_text(root: Path) -> str:
    chunks: list[str] = []
    if not root.is_dir():
        return ""
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.suffix.casefold() not in {".py", ".json"}
            or "__pycache__" in path.parts
        ):
            continue
        text = _safe_text(path)
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _staged_files(repo: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=repo,
            capture_output=True,
            text=True,
            shell=False,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ["<git inspection unavailable>"]
    if result.returncode != 0:
        return ["<git inspection unavailable>"]
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def collect_engineering_acceptance(
    *,
    target: str,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    """Collect local evidence only. No external provider is called."""

    repo = _repo_root()
    economics_root = repo / "src" / "nexuss" / "economics"
    economics_text = _tree_text(economics_root).casefold()
    p5_text = _safe_text(repo / "src" / "nexuss" / "ui" / "p5.js")
    platform_text = _safe_text(
        repo / "src" / "nexuss" / "ui" / "nexuss_ui_platform.js"
    )
    staged = _staged_files(repo)

    build = get_capability("engineering.build_artifact")
    verify = get_capability("engineering.verify_acceptance")
    package_apply = get_capability("engineering.package.apply")

    checks = {
        "build_capability_registered": build is not None,
        "build_capability_high_risk": (
            build is not None
            and getattr(build.risk_tier, "value", str(build.risk_tier)) == "high"
        ),
        "acceptance_capability_registered": verify is not None,
        "acceptance_is_read_only": (
            verify is not None
            and verify.execution_mode == "deterministic_local_readonly"
        ),
        "approved_package_lane_registered": package_apply is not None,
        "economics_module_present": economics_root.is_dir(),
        "pricing_registry_evidence": (
            "pricing" in economics_text and "model" in economics_text
        ),
        "budget_governor_evidence": (
            "budget" in economics_text and "provider" in economics_text
        ),
        "usage_accounting_evidence": (
            "usage" in economics_text and "token" in economics_text
        ),
        "cost_or_ledger_evidence": (
            "cost" in economics_text or "ledger" in economics_text
        ),
        "deepseek_seed_pricing_evidence": all(
            token in economics_text
            for token in ("0.022", "0.66", "1.98", "0.044", "1.32", "3.96")
        ),
        "prompt_build_managed_window_contract": all(
            marker in p5_text
            for marker in (
                "engineering-progress-minimize",
                "engineering-progress-hide",
                "engineering-progress-restore",
                "engineeringProgressWindowState",
            )
        ),
        "capability_dock_autoload_contract": (
            "createSystemWindows();" in platform_text
            and "buildDock();" in platform_text
            and "nx-capability-dock" in platform_text
        ),
        "no_staged_files": not staged,
    }

    passed = all(checks.values())
    return {
        "source_mode": "deterministic_local_engineering_acceptance",
        "target": target,
        "observed_at": (observed_at or datetime.now(UTC)).isoformat(),
        "deterministic_checks": checks,
        "acceptance_status": (
            "pass_with_manual_ui_checks" if passed else "incomplete"
        ),
        "acceptance_complete": passed,
        "manual_checks_required": [
            "Prompt-to-Build minimize / hide / restore / drag interaction",
            "Responsive placement at desktop and narrow/mobile widths",
        ],
        "prompt_build_progress": latest_prompt_build_progress(),
        "staged_files": staged,
        "external_provider_called": False,
        "paid_llm_calls": 0,
        "credentials_exposed": False,
    }
