"""Prompt-to-Build developer self-build capability for Nexuss.

This module is intentionally development-only.  A user prompt may authorize one
isolated DeepSeek engineering run.  Nexuss keeps file access, validation,
regression comparison, backup, and live application authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr

from nexuss.connectors.vault import DpapiSecretVault
from nexuss.domain.models import CapabilityResult, EvidenceRecord, PlanStep, StepStatus
from nexuss.engineering.credentials import ProviderCredentialStore
from nexuss.engineering.errors import EngineeringError
from nexuss.engineering.models import ModelProposal, ToolName, ToolRequest
from nexuss.engineering.provider_connections import EngineeringProviderConnectionService
from nexuss.engineering.tools import WorkspaceToolRegistry
from nexuss.engineering.workspace import IsolatedWorkspace, WorkspacePolicy

_ENABLED_ENV = "NEXUSS_DEVELOPER_SELF_BUILD"
_APPLY_ENV = "NEXUSS_DEVELOPER_SELF_BUILD_APPLY"
_MAX_MODEL_ROUNDS = 8
_MAX_REPAIR_ROUNDS = 2
_TEST_TIMEOUT_SECONDS = 1800
_PROMPT_LIMIT = 185_000

_EXCLUDED_DIRS = {
    ".git", ".patch-backups", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", ".venv", "venv", "target",
}
_EXCLUDED_FILES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "credentials.json", "secrets.json", "token.json",
}
_EXCLUDED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12", ".pfx", ".pyc"}
_FAILURE_NODE = re.compile(r"^(FAILED|ERROR)\s+([^\s]+)", re.MULTILINE)
_PROTECTED_SELF_BUILD_PREFIXES = (
    "src/nexuss/constitution/",
    "src/nexuss/connectors/vault.py",
    "src/nexuss/engineering/credentials.py",
    "src/nexuss/engineering/prompt_build.py",
    "src/nexuss/core/policy.py",
)

_NATIVE_TOOLS: list[dict[str, object]] = [
    {
        "type": "function",
        "function": {
            "name": "workspace_list_files",
            "description": "List files in one repository-relative directory in the isolated workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_read_file",
            "description": "Read one UTF-8 repository-relative file from the isolated workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_write_file",
            "description": "Write one complete UTF-8 file in the isolated workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "expected_sha256": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
]
_NATIVE_MAP = {
    "workspace_list_files": ToolName.LIST_FILES,
    "workspace_read_file": ToolName.READ_FILE,
    "workspace_write_file": ToolName.WRITE_FILE,
}


@dataclass(frozen=True)
class BuildOutcome:
    success: bool
    code: str
    message: str
    provider: str
    model: str
    workspace: str
    artifact_zip: str | None
    artifact_sha256: str | None
    changed_files: tuple[str, ...]
    baseline_failures: tuple[str, ...]
    new_failures: tuple[str, ...]
    applied_to_live_repository: bool
    backup_path: str | None
    restart_required: bool
    elapsed_seconds: float


_ACTIVE_PROGRESS_PHASES = {
    "preparing",
    "baseline",
    "deepseek",
    "writing",
    "syntax_verification",
    "regression_verification",
    "repair",
    "packaging",
    "applying",
}


class _BuildProgress:
    """Small local telemetry stream for Prompt-to-Build.

    This is a presentation projection only. It grants no task, policy, file, or
    provider authority. The file contains no credentials or model prompts.
    """

    def __init__(self, run_root: Path, goal: str, task_id: UUID | None = None) -> None:
        self._path = run_root / "progress.json"
        self._payload: dict[str, object] = {
            "schema": "nexuss.prompt_build.progress.v1",
            "run_id": run_root.name,
            "core_task_id": str(task_id) if task_id is not None else None,
            "goal": goal[:500],
            "started_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "phase": "preparing",
            "actor": "Nexuss",
            "message": "Preparing isolated engineering workspace.",
            "active": True,
            "terminal": False,
            "changed_file_count": 0,
            "round": 0,
            "events": [],
        }
        self.emit(
            actor="Nexuss",
            phase="preparing",
            message="Preparing isolated engineering workspace.",
        )

    def emit(
        self,
        *,
        actor: str,
        phase: str,
        message: str,
        round_number: int | None = None,
        changed_file_count: int | None = None,
        terminal: bool = False,
        code: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        event: dict[str, object] = {
            "at": now,
            "actor": actor,
            "phase": phase,
            "message": message[:1000],
        }
        if round_number is not None:
            event["round"] = round_number
        if code:
            event["code"] = code
        events = self._payload.get("events")
        if not isinstance(events, list):
            events = []
        events.append(event)
        self._payload["events"] = events[-24:]
        self._payload["updated_at"] = now
        self._payload["actor"] = actor
        self._payload["phase"] = phase
        self._payload["message"] = message[:1000]
        self._payload["active"] = phase in _ACTIVE_PROGRESS_PHASES and not terminal
        self._payload["terminal"] = terminal
        if round_number is not None:
            self._payload["round"] = round_number
        if changed_file_count is not None:
            self._payload["changed_file_count"] = changed_file_count
        if code:
            self._payload["code"] = code
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self._path)


def latest_prompt_build_progress() -> dict[str, object]:
    """Return the newest local Prompt-to-Build progress projection."""

    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    root = local / "Nexuss" / "engineering-runs"
    if not root.is_dir():
        return {"active": False, "terminal": False, "events": []}
    candidates = sorted(
        (path / "progress.json" for path in root.glob("prompt-build-*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime if path.is_file() else 0.0,
        reverse=True,
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {"active": False, "terminal": False, "events": []}


def mark_latest_prompt_build_failed(goal: str, code: str, message: str) -> None:
    """Mark the current matching progress projection terminal after a safe failure."""

    payload = latest_prompt_build_progress()
    if not payload.get("active") or str(payload.get("goal", "")) != goal[:500]:
        return
    run_id = str(payload.get("run_id", ""))
    if not run_id.startswith("prompt-build-"):
        return
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    path = local / "Nexuss" / "engineering-runs" / run_id / "progress.json"
    if not path.is_file():
        return
    now = datetime.now(UTC).isoformat()
    events = payload.get("events")
    if not isinstance(events, list):
        events = []
    events.append(
        {
            "at": now,
            "actor": "Nexuss",
            "phase": "failed",
            "message": message[:1000],
            "code": code,
        }
    )
    payload["events"] = events[-24:]
    payload["updated_at"] = now
    payload["actor"] = "Nexuss"
    payload["phase"] = "failed"
    payload["message"] = message[:1000]
    payload["code"] = code
    payload["active"] = False
    payload["terminal"] = True
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _repo_root() -> Path:
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").is_dir():
        raise EngineeringError(
            "ENGINEERING_LIVE_REPOSITORY_UNAVAILABLE",
            "The running Nexuss source tree is not a Git repository.",
        )
    return root


def _run(argv: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {
            "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
            "HOME", "USERPROFILE", "LOCALAPPDATA",
        }
    }
    return subprocess.run(
        argv,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        shell=False,
        check=False,
        timeout=timeout,
    )


def _git_output(repo: Path, argv: list[str]) -> str:
    completed = _run(["git", *argv], repo, timeout=120)
    if completed.returncode != 0:
        raise EngineeringError(
            "ENGINEERING_GIT_READ_FAILED",
            "Nexuss could not inspect the local Git worktree.",
        )
    return completed.stdout


def _is_excluded(relative: Path) -> bool:
    lowered = {part.casefold() for part in relative.parts}
    if lowered & {item.casefold() for item in _EXCLUDED_DIRS}:
        return True
    if relative.name.casefold() in {item.casefold() for item in _EXCLUDED_FILES}:
        return True
    return relative.suffix.casefold() in {item.casefold() for item in _EXCLUDED_SUFFIXES}


def _visible_files(repo: Path) -> tuple[Path, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=repo,
        capture_output=True,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        raise EngineeringError(
            "ENGINEERING_GIT_READ_FAILED",
            "Nexuss could not enumerate the local Git worktree.",
        )
    items: list[Path] = []
    for raw in completed.stdout.split(b"\x00"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8", errors="strict"))
        if not _is_excluded(relative) and (repo / relative).is_file():
            items.append(relative)
    return tuple(sorted(items, key=lambda item: item.as_posix()))


def _worktree_fingerprint(repo: Path) -> str:
    h = hashlib.sha256()
    h.update(_git_output(repo, ["rev-parse", "HEAD"]).strip().encode())
    files = _visible_files(repo)
    for relative in files:
        path = repo / relative
        h.update(relative.as_posix().encode())
        h.update(b"\0")
        h.update(_sha256_file(path).encode())
        h.update(b"\0")
    return h.hexdigest()


def _copy_worktree(repo: Path, target: Path) -> dict[str, str]:
    target.mkdir(parents=True, exist_ok=True)
    baseline_hashes: dict[str, str] = {}
    for relative in _visible_files(repo):
        source = repo / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        baseline_hashes[relative.as_posix()] = _sha256_file(source)
    for argv in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "Nexuss Prompt Builder"],
        ["git", "config", "user.email", "nexuss-prompt-builder@localhost"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "Nexuss isolated prompt-build baseline"],
    ):
        result = _run(argv, target, timeout=180)
        if result.returncode != 0:
            raise EngineeringError(
                "ENGINEERING_ISOLATED_GIT_INIT_FAILED",
                "Nexuss could not establish the isolated regression baseline.",
            )
    return baseline_hashes


def _pytest_nodes(output: str) -> tuple[str, ...]:
    return tuple(sorted({f"{kind} {node}" for kind, node in _FAILURE_NODE.findall(output)}))


def _run_full_pytest(root: Path) -> tuple[int, str, tuple[str, ...]]:
    result = _run(
        [
            os.fspath(Path(os.sys.executable)), "-m", "pytest",
            "--import-mode=importlib", "-q", "-p", "no:cacheprovider",
        ],
        root,
        timeout=_TEST_TIMEOUT_SECONDS,
    )
    output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
    return result.returncode, output, _pytest_nodes(output)


def _baseline_nodes(root: Path, fingerprint: str) -> tuple[str, ...]:
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    cache_root = local / "Nexuss" / "engineering-baselines"
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_path = cache_root / f"{fingerprint}.json"
    if cache_path.is_file():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            raw = payload.get("failing_error_nodes")
            if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
                return tuple(sorted(raw))
        except (OSError, ValueError, TypeError):
            pass
    code, output, nodes = _run_full_pytest(root)
    if code not in {0, 1}:
        raise EngineeringError(
            "ENGINEERING_BASELINE_VALIDATION_INVALID",
            "The regression baseline did not produce a normal pytest pass/fail result.",
            safe_details={"pytest_exit_code": code, "output_tail": output[-4000:]},
        )
    cache_path.write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "failing_error_nodes": list(nodes),
                "captured_at": datetime.now(UTC).isoformat(),
                "output_tail": output[-20_000:],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return nodes


def _compact_result(tool: ToolName, output: str, success: bool) -> dict[str, object]:
    max_chars = 18_000 if tool is ToolName.READ_FILE else 12_000
    if len(output) > max_chars:
        half = max_chars // 2
        output = output[:half] + "\n...[NEXUSS CONTEXT TRUNCATED]...\n" + output[-half:]
    return {"tool": tool.value, "success": success, "output": output}


class _DeepSeekNativeAgent:
    def __init__(self, api_key: SecretStr, model: str, api_base: str, max_tokens: int) -> None:
        self._api_key = api_key
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._max_tokens = max_tokens

    def _post(self, system: str, user: str, tools: list[dict[str, object]]) -> dict[str, object]:
        body: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": self._max_tokens,
            "thinking": {"type": "disabled"},
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        last: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(
                    base_url=self._api_base,
                    timeout=180.0,
                    headers={
                        "Authorization": "Bearer " + self._api_key.get_secret_value(),
                        "Content-Type": "application/json",
                        "User-Agent": "Nexuss-Prompt-To-Build/1.0",
                    },
                ) as client:
                    response = client.post("/chat/completions", json=body)
                    if response.status_code == 429 or response.status_code >= 500:
                        last = RuntimeError(f"temporary provider status {response.status_code}")
                        if attempt < 2:
                            time.sleep(attempt + 1)
                            continue
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        raise ValueError("provider payload is not an object")
                    return payload
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                if attempt < 2:
                    time.sleep(attempt + 1)
                    continue
        raise EngineeringError(
            "ENGINEERING_PROVIDER_UNAVAILABLE",
            "DeepSeek could not complete the isolated engineering request.",
            safe_details={"attempts": 3, "last_error": type(last).__name__ if last else "unknown"},
        )

    @staticmethod
    def _message(payload: dict[str, object]) -> dict[str, object]:
        try:
            choices = payload["choices"]
            first = choices[0]  # type: ignore[index]
            message = first["message"]  # type: ignore[index]
            if not isinstance(message, dict):
                raise TypeError
            return message
        except (KeyError, IndexError, TypeError) as exc:
            raise EngineeringError(
                "ENGINEERING_PROVIDER_RESPONSE_INVALID",
                "DeepSeek omitted the assistant message.",
            ) from exc

    def propose(self, *, goal: str, phase: str, context: dict[str, object], allowed: tuple[ToolName, ...]) -> ModelProposal:
        native_names = {
            ToolName.LIST_FILES: "workspace_list_files",
            ToolName.READ_FILE: "workspace_read_file",
            ToolName.WRITE_FILE: "workspace_write_file",
        }
        allowed_native = {native_names[item] for item in allowed}
        tools = [
            item for item in _NATIVE_TOOLS
            if str(item["function"]["name"]) in allowed_native  # type: ignore[index]
        ]
        system = (
            "You are DeepSeek acting only as Nexuss's engineering proposal engine. "
            "The user has explicitly enabled local developer self-build mode. Work only "
            "inside the isolated repository exposed through native tools. Never request or "
            "emit secrets, credentials, .env files, database contents, Git writes, GitHub "
            "publication, shell commands, or paths outside the workspace. Nexuss owns "
            "validation and live application. Make concrete progress; do not repeat the same "
            "list/read request. Existing files may be overwritten only after they have been "
            "read; Nexuss will enforce compare-and-swap hashes. "
            + (
                "You are in WRITE-REQUIRED mode. The only available tool is write_file. "
                "Do not return another plan or request more inspection. Use the source evidence "
                "already supplied by Nexuss and issue concrete write_file calls now. "
                if phase == "write_required"
                else ""
            )
            + f"Current phase: {phase}. User goal: {goal}"
        )
        user = json.dumps(context, ensure_ascii=False, sort_keys=True)
        if len(user) > _PROMPT_LIMIT:
            raise EngineeringError(
                "ENGINEERING_CONTEXT_TOO_LARGE",
                "The bounded engineering context exceeded the provider input budget.",
            )
        payload = self._post(system, user, tools)
        message = self._message(payload)
        raw_calls = message.get("tool_calls")
        requests: list[ToolRequest] = []
        if isinstance(raw_calls, list):
            for raw in raw_calls[:6]:
                if not isinstance(raw, dict):
                    continue
                function = raw.get("function")
                if not isinstance(function, dict):
                    continue
                name = str(function.get("name", ""))
                tool = _NATIVE_MAP.get(name)
                if tool is None or tool not in allowed:
                    continue
                raw_args = function.get("arguments", {})
                if isinstance(raw_args, str):
                    try:
                        arguments = json.loads(raw_args)
                    except json.JSONDecodeError:
                        arguments = {}
                elif isinstance(raw_args, dict):
                    arguments = dict(raw_args)
                else:
                    arguments = {}
                requests.append(
                    ToolRequest(
                        request_id=uuid4(),
                        tool_name=tool,
                        arguments=arguments,
                        rationale=f"DeepSeek requested bounded {tool.value} work for the user goal.",
                    )
                )
        content = message.get("content")
        summary = str(content or "DeepSeek engineering tool proposal.").strip()[:8_000]
        done = not requests and bool(content) and phase != "write_required"
        return ModelProposal(
            summary=summary or "DeepSeek engineering proposal.",
            tool_requests=tuple(requests),
            done=done,
            completion_message=summary if done else None,
        )


def _allowed_tools(phase: str) -> tuple[ToolName, ...]:
    if phase == "discovery":
        return (ToolName.LIST_FILES, ToolName.READ_FILE, ToolName.WRITE_FILE)
    if phase == "implementation":
        return (ToolName.READ_FILE, ToolName.WRITE_FILE)
    # Once the bounded discovery/implementation window is exhausted, browsing is
    # mechanically closed. This prevents a model from spending the rest of the
    # run re-reading the repository instead of implementing the requested change.
    return (ToolName.WRITE_FILE,)


def _execute_requests(
    requests: tuple[ToolRequest, ...],
    *,
    registry: WorkspaceToolRegistry,
    workspace: IsolatedWorkspace,
    read_hashes: dict[str, str],
    cache: dict[str, Any],
    progress: _BuildProgress | None = None,
    round_number: int | None = None,
) -> list[dict[str, object]]:
    outputs: list[dict[str, object]] = []
    for request in requests:
        arguments = dict(request.arguments)
        raw_path = str(arguments.get("path", ""))
        normalized_path = Path(raw_path).as_posix().lstrip("./") if raw_path else ""
        if normalized_path:
            arguments["path"] = normalized_path
        cache_key = request.tool_name.value + ":" + json.dumps(arguments, sort_keys=True, default=str)
        if request.tool_name in {ToolName.LIST_FILES, ToolName.READ_FILE} and cache_key in cache:
            outputs.append(
                {
                    "tool": request.tool_name.value,
                    "success": True,
                    "duplicate_suppressed": True,
                    "output": "Exact duplicate request suppressed; reuse prior evidence.",
                }
            )
            continue
        if request.tool_name is ToolName.WRITE_FILE:
            if any(
                normalized_path == protected.rstrip("/")
                or normalized_path.startswith(protected)
                for protected in _PROTECTED_SELF_BUILD_PREFIXES
            ):
                outputs.append(
                    {
                        "tool": request.tool_name.value,
                        "success": False,
                        "error_code": "ENGINEERING_SELF_BUILD_PROTECTED_PATH",
                        "output": (
                            "This trust-boundary file cannot be modified by autonomous "
                            "Prompt-to-Build. Use the manual governed upgrade path for it."
                        ),
                    }
                )
                continue
            candidate = workspace.root / normalized_path
            if candidate.exists() and not arguments.get("expected_sha256"):
                expected = read_hashes.get(normalized_path)
                if expected:
                    arguments["expected_sha256"] = expected
            request = request.model_copy(update={"arguments": arguments})
            if progress is not None:
                progress.emit(
                    actor="DeepSeek",
                    phase="writing",
                    message=f"Writing {normalized_path or 'a generated source file'}.",
                    round_number=round_number,
                    changed_file_count=len(workspace.changed_files),
                )
        elif progress is not None:
            action = "Inspecting" if request.tool_name is ToolName.READ_FILE else "Listing"
            progress.emit(
                actor="DeepSeek",
                phase="deepseek",
                message=f"{action} {normalized_path or 'the isolated workspace'}.",
                round_number=round_number,
                changed_file_count=len(workspace.changed_files),
            )
        result = registry.execute(request)
        if request.tool_name in {ToolName.LIST_FILES, ToolName.READ_FILE} and result.success:
            cache[cache_key] = result
        if request.tool_name is ToolName.READ_FILE and result.success:
            try:
                parsed = json.loads(result.output)
                if isinstance(parsed, dict) and normalized_path and parsed.get("sha256"):
                    read_hashes[normalized_path] = str(parsed["sha256"])
            except json.JSONDecodeError:
                pass
        if request.tool_name is ToolName.WRITE_FILE and progress is not None:
            progress.emit(
                actor="Nexuss",
                phase="writing",
                message=(
                    f"Accepted DeepSeek write for {normalized_path}."
                    if result.success
                    else f"Rejected DeepSeek write for {normalized_path}; controller validation failed."
                ),
                round_number=round_number,
                changed_file_count=len(workspace.changed_files),
            )
        outputs.append(_compact_result(request.tool_name, result.output, result.success))
    return outputs


def _changed_file_payload(workspace: IsolatedWorkspace, limit: int = 10) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for relative in workspace.changed_files[-limit:]:
        path = workspace.root / relative
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > 18_000:
            content = content[:9_000] + "\n...[TRUNCATED]...\n" + content[-9_000:]
        payload.append({"path": relative, "sha256": _sha256_file(path), "content": content})
    return payload


def _build_with_agent(
    *,
    goal: str,
    workspace: IsolatedWorkspace,
    agent: _DeepSeekNativeAgent,
    progress: _BuildProgress,
) -> tuple[int, list[dict[str, object]]]:
    registry = WorkspaceToolRegistry(workspace)
    read_hashes: dict[str, str] = {}
    cache: dict[str, Any] = {}
    recent: list[dict[str, object]] = []
    no_progress = 0
    forced_write_no_progress = 0
    last_changed = 0
    rounds = 0

    for round_number in range(1, _MAX_MODEL_ROUNDS + 1):
        rounds = round_number
        changed_count = len(workspace.changed_files)
        if changed_count:
            phase = "implementation"
        elif round_number <= 2:
            phase = "discovery"
        elif round_number <= 4:
            phase = "implementation"
        else:
            phase = "write_required"
        progress.emit(
            actor="DeepSeek",
            phase="deepseek" if phase != "write_required" else "writing",
            message=(
                f"Engineering round {round_number}: inspecting the isolated source."
                if phase == "discovery"
                else (
                    f"Engineering round {round_number}: implementing the requested change."
                    if phase == "implementation"
                    else f"Engineering round {round_number}: implementation is now write-required."
                )
            ),
            round_number=round_number,
            changed_file_count=changed_count,
        )
        context = {
            "goal": goal,
            "phase": phase,
            "changed_files": list(workspace.changed_files),
            "recent_tool_results": recent[-6:],
            "instruction": (
                "Inspect only what is necessary and implement the requested Nexuss change. "
                "If you already have enough context, write now. Nexuss will run tests after "
                "your writes. Do not merely describe a plan."
                if phase != "write_required"
                else (
                    "Browsing is closed. Use the source evidence already returned in recent_tool_results. "
                    "Issue concrete workspace_write_file calls now; do not describe another plan."
                )
            ),
        }
        proposal = agent.propose(goal=goal, phase=phase, context=context, allowed=_allowed_tools(phase))
        if proposal.tool_requests:
            try:
                outputs = _execute_requests(
                    proposal.tool_requests,
                    registry=registry,
                    workspace=workspace,
                    read_hashes=read_hashes,
                    cache=cache,
                    progress=progress,
                    round_number=round_number,
                )
            except Exception as exc:
                # A single malformed/unexpected workspace-tool failure must not
                # terminate the whole governed engineering task. Preserve a safe
                # diagnostic and let the bounded controller continue; the next
                # round can reduce context or enter WRITE-REQUIRED mode.
                error_type = type(exc).__name__
                progress.emit(
                    actor="Nexuss",
                    phase="deepseek",
                    message=(
                        "One isolated engineering tool request failed unexpectedly "
                        f"({error_type}); the controller contained it and will continue."
                    ),
                    round_number=round_number,
                    changed_file_count=len(workspace.changed_files),
                    code="ENGINEERING_TOOL_REQUEST_FAILURE",
                )
                outputs = [
                    {
                        "tool": "controller",
                        "success": False,
                        "error_code": "ENGINEERING_TOOL_REQUEST_FAILURE",
                        "error_type": error_type,
                        "output": (
                            "The isolated tool request failed unexpectedly; "
                            "Nexuss contained the failure without changing live source."
                        ),
                    }
                ]
            recent.extend(outputs)
        elif proposal.done and workspace.changed_files:
            break
        else:
            recent.append({"provider_message": proposal.summary, "actionable": False})

        current_changed = len(workspace.changed_files)
        if current_changed == last_changed:
            no_progress += 1
        else:
            no_progress = 0
            last_changed = current_changed
        if phase == "write_required":
            if current_changed == last_changed:
                forced_write_no_progress += 1
            else:
                forced_write_no_progress = 0
            # Give the write-only phase two genuine chances. The former generic
            # round-4 no-progress break made round 5 unreachable whenever the
            # model inspected without writing.
            if forced_write_no_progress >= 2:
                break
        else:
            forced_write_no_progress = 0

        if current_changed and round_number >= 6:
            break

    return rounds, recent


def _repair(
    *,
    goal: str,
    workspace: IsolatedWorkspace,
    agent: _DeepSeekNativeAgent,
    failure_output: str,
    failure_nodes: tuple[str, ...],
    progress: _BuildProgress,
) -> int:
    registry = WorkspaceToolRegistry(workspace)
    read_hashes = {
        relative: _sha256_file(workspace.root / relative)
        for relative in workspace.changed_files
        if (workspace.root / relative).is_file()
    }
    rounds = 0
    previous_signature = ""
    for round_number in range(1, _MAX_REPAIR_ROUNDS + 1):
        rounds = round_number
        progress.emit(
            actor="DeepSeek",
            phase="repair",
            message=f"Repairing {len(failure_nodes)} new regression failure(s).",
            round_number=round_number,
            changed_file_count=len(workspace.changed_files),
        )
        signature = hashlib.sha256(
            ("\n".join(failure_nodes) + "\n" + "\n".join(workspace.changed_files)).encode()
        ).hexdigest()
        if signature == previous_signature:
            break
        previous_signature = signature
        context = {
            "goal": goal,
            "phase": "repair",
            "new_failure_nodes": list(failure_nodes),
            "validation_output_tail": failure_output[-35_000:],
            "changed_file_snapshots": _changed_file_payload(workspace),
            "instruction": (
                "Repair only the new regression(s). Existing baseline failures are out of "
                "scope. Write concrete corrected files; do not return a plan."
            ),
        }
        proposal = agent.propose(
            goal=goal,
            phase="repair",
            context=context,
            allowed=(ToolName.READ_FILE, ToolName.WRITE_FILE),
        )
        if not proposal.tool_requests:
            break
        _execute_requests(
            proposal.tool_requests,
            registry=registry,
            workspace=workspace,
            read_hashes=read_hashes,
            cache={},
            progress=progress,
            round_number=round_number,
        )
    return rounds


def _syntax_check_changed(workspace: IsolatedWorkspace) -> None:
    for relative in workspace.changed_files:
        path = workspace.root / relative
        if path.suffix != ".py" or not path.is_file():
            continue
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise EngineeringError(
                "ENGINEERING_CHANGED_FILE_SYNTAX_INVALID",
                f"Generated Python source failed syntax validation: {relative}",
            ) from exc


def _proposal_zip(
    *,
    workspace: IsolatedWorkspace,
    goal: str,
    baseline_nodes: tuple[str, ...],
    post_nodes: tuple[str, ...],
    validation_output: str,
    model: str,
    success: bool,
) -> tuple[Path, str]:
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    root = local / "Nexuss" / "engineering-artifacts"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    output = root / f"nexuss-prompt-build-{stamp}.zip"
    diff = _run(["git", "diff", "--no-ext-diff", "HEAD", "--"], workspace.root, timeout=120)
    new_nodes = sorted(set(post_nodes) - set(baseline_nodes))
    manifest = {
        "format": "nexuss-prompt-build-v1",
        "goal": goal,
        "provider": "deepseek",
        "model": model,
        "success": success,
        "changed_files": list(workspace.changed_files),
        "baseline_failures": list(baseline_nodes),
        "post_failures": list(post_nodes),
        "new_failures": new_nodes,
        "credentials_exposed": False,
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("NEXUSS-BUILD-MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True))
        archive.writestr("DIFF.patch", diff.stdout + diff.stderr)
        archive.writestr("VALIDATION.txt", validation_output)
        for relative in workspace.changed_files:
            path = workspace.root / relative
            if path.is_file() and not _is_excluded(Path(relative)):
                archive.write(path, f"payload/{relative}")
    return output, _sha256_file(output)


def _apply_live(
    *,
    repo: Path,
    workspace: IsolatedWorkspace,
    baseline_hashes: dict[str, str],
    initial_fingerprint: str,
) -> str:
    if _worktree_fingerprint(repo) != initial_fingerprint:
        raise EngineeringError(
            "ENGINEERING_LIVE_WORKTREE_CHANGED",
            "The live Nexuss worktree changed during the build; the validated proposal was not applied.",
        )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup = repo / ".patch-backups" / f"prompt-build-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    applied: list[str] = []
    newly_created: list[str] = []
    try:
        for relative in workspace.changed_files:
            source = workspace.root / relative
            if not source.is_file():
                continue
            destination = repo / relative
            expected = baseline_hashes.get(relative)
            if destination.exists():
                actual = _sha256_file(destination)
                if expected is None or actual != expected:
                    raise EngineeringError(
                        "ENGINEERING_LIVE_FILE_CHANGED",
                        f"Live file changed after isolation: {relative}",
                    )
                backup_file = backup / relative
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_file)
            else:
                newly_created.append(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".nexuss-prompt-tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
            applied.append(relative)
        (backup / "MANIFEST.json").write_text(
            json.dumps({"applied": applied, "new_files": newly_created}, indent=2),
            encoding="utf-8",
        )
        return str(backup)
    except Exception:
        for relative in reversed(applied):
            destination = repo / relative
            backup_file = backup / relative
            if backup_file.is_file():
                shutil.copy2(backup_file, destination)
            elif relative in newly_created:
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
        raise



def _latest_failed_build_context() -> dict[str, object]:
    """Recover the newest retained failed Prompt-to-Build run and diagnostic artifact."""

    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    runs_root = local / "Nexuss" / "engineering-runs"
    artifacts_root = local / "Nexuss" / "engineering-artifacts"
    if not runs_root.is_dir():
        raise EngineeringError(
            "ENGINEERING_REPAIR_NO_FAILED_RUN",
            "Nexuss has no retained failed Prompt-to-Build run to repair.",
        )

    run_candidates = sorted(
        (path for path in runs_root.glob("prompt-build-*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for run_root in run_candidates:
        progress_path = run_root / "progress.json"
        workspace_root = run_root / "workspace"
        if not progress_path.is_file() or not (workspace_root / ".git").is_dir():
            continue
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(progress, dict):
            continue
        if not bool(progress.get("terminal")) or str(progress.get("phase")) != "failed":
            continue
        if run_root.name.startswith("prompt-build-repair-"):
            continue
        goal_prefix = str(progress.get("goal", ""))
        if not goal_prefix:
            continue

        artifacts: list[tuple[Path, dict[str, object], str]] = []
        if artifacts_root.is_dir():
            for artifact in sorted(
                artifacts_root.glob("nexuss-prompt-build-*.zip"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            ):
                try:
                    with zipfile.ZipFile(artifact) as archive:
                        manifest = json.loads(
                            archive.read("NEXUSS-BUILD-MANIFEST.json").decode("utf-8")
                        )
                        validation = archive.read("VALIDATION.txt").decode(
                            "utf-8", errors="replace"
                        )
                except (OSError, KeyError, ValueError, zipfile.BadZipFile):
                    continue
                if not isinstance(manifest, dict) or bool(manifest.get("success")):
                    continue
                manifest_goal = str(manifest.get("goal", ""))
                if manifest_goal.startswith(goal_prefix) or goal_prefix.startswith(manifest_goal[:500]):
                    artifacts.append((artifact, manifest, validation))
                    break
        if not artifacts:
            raise EngineeringError(
                "ENGINEERING_REPAIR_DIAGNOSTIC_ARTIFACT_MISSING",
                "The failed candidate exists, but its diagnostic artifact could not be matched safely.",
                safe_details={"run_id": run_root.name},
            )
        artifact, manifest, validation = artifacts[0]
        return {
            "run_root": run_root,
            "workspace_root": workspace_root,
            "progress": progress,
            "artifact": artifact,
            "manifest": manifest,
            "validation": validation,
        }

    raise EngineeringError(
        "ENGINEERING_REPAIR_NO_FAILED_RUN",
        "Nexuss has no retained failed Prompt-to-Build candidate that is safe to resume.",
    )


def _hydrate_changed_files(workspace: IsolatedWorkspace) -> tuple[str, ...]:
    changed = _run(["git", "diff", "--name-only", "HEAD", "--"], workspace.root, timeout=120)
    untracked = _run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        workspace.root,
        timeout=120,
    )
    if changed.returncode != 0 or untracked.returncode != 0:
        raise EngineeringError(
            "ENGINEERING_REPAIR_CANDIDATE_INSPECTION_FAILED",
            "Nexuss could not recover the retained candidate changed-file inventory.",
        )
    recovered = {
        line.strip()
        for line in (changed.stdout + "\n" + untracked.stdout).splitlines()
        if line.strip()
    }
    workspace._changed_files.update(recovered)  # type: ignore[attr-defined]
    return workspace.changed_files


def _assert_candidate_baseline_matches_live(repo: Path, workspace_root: Path) -> None:
    """Prove the retained candidate was isolated from the still-current live worktree."""

    tree = _run(["git", "ls-tree", "-r", "--name-only", "HEAD"], workspace_root, timeout=120)
    if tree.returncode != 0:
        raise EngineeringError(
            "ENGINEERING_REPAIR_BASELINE_INSPECTION_FAILED",
            "Nexuss could not inspect the retained candidate baseline.",
        )
    baseline_paths = {line.strip() for line in tree.stdout.splitlines() if line.strip()}
    live_paths = {item.as_posix() for item in _visible_files(repo)}
    if baseline_paths != live_paths:
        raise EngineeringError(
            "ENGINEERING_REPAIR_LIVE_WORKTREE_DRIFT",
            "The live Nexuss file inventory changed after the failed build; the retained candidate was not reused.",
            safe_details={
                "added_live_paths": sorted(live_paths - baseline_paths)[:20],
                "missing_live_paths": sorted(baseline_paths - live_paths)[:20],
            },
        )

    for relative in sorted(baseline_paths):
        baseline_oid = _run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            workspace_root,
            timeout=30,
        )
        live_oid = _run(
            ["git", "hash-object", f"--path={relative}", relative],
            repo,
            timeout=30,
        )
        if (
            baseline_oid.returncode != 0
            or live_oid.returncode != 0
            or baseline_oid.stdout.strip() != live_oid.stdout.strip()
        ):
            raise EngineeringError(
                "ENGINEERING_REPAIR_LIVE_WORKTREE_DRIFT",
                "The live Nexuss source changed after the failed build; the retained candidate was not reused.",
                safe_details={"path": relative},
            )


def _relevant_failure_sources(
    workspace_root: Path,
    failure_nodes: tuple[str, ...],
    limit: int = 4,
) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    seen: set[str] = set()
    for failure in failure_nodes:
        node = failure.split(" ", 1)[1] if " " in failure else failure
        relative = node.split("::", 1)[0].strip()
        if not relative or relative in seen:
            continue
        seen.add(relative)
        path = workspace_root / relative
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > 20_000:
            content = content[:10_000] + "\n...[TRUNCATED]...\n" + content[-10_000:]
        evidence.append(
            {
                "path": relative,
                "sha256": _sha256_file(path),
                "content": content,
            }
        )
        if len(evidence) >= limit:
            break
    return evidence


def _run_failure_nodes(root: Path, failure_nodes: tuple[str, ...]) -> tuple[int, str]:
    nodes = [
        item.split(" ", 1)[1] if " " in item else item
        for item in failure_nodes
    ]
    result = _run(
        [
            os.fspath(Path(os.sys.executable)),
            "-m",
            "pytest",
            "--import-mode=importlib",
            "-q",
            "-p",
            "no:cacheprovider",
            *nodes,
        ],
        root,
        timeout=_TEST_TIMEOUT_SECONDS,
    )
    output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
    return result.returncode, output


def run_latest_failed_build_repair(
    target: str,
    *,
    task_id: UUID | None = None,
) -> BuildOutcome:
    """Resume one retained failed candidate and permit one targeted repair proposal."""

    started = time.monotonic()
    repo = _repo_root()
    recovered = _latest_failed_build_context()
    source_run_root = recovered["run_root"]
    workspace_root = recovered["workspace_root"]
    source_progress = recovered["progress"]
    artifact = recovered["artifact"]
    manifest = recovered["manifest"]
    validation_output = str(recovered["validation"])
    assert isinstance(source_run_root, Path)
    assert isinstance(workspace_root, Path)
    assert isinstance(source_progress, dict)
    assert isinstance(artifact, Path)
    assert isinstance(manifest, dict)

    original_goal = str(manifest.get("goal", ""))
    baseline = tuple(sorted(str(item) for item in manifest.get("baseline_failures", []) if isinstance(item, str)))
    original_task_id = str(source_progress.get("core_task_id") or "")

    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_root = local / "Nexuss" / "engineering-runs" / f"prompt-build-repair-{stamp}"
    run_root.mkdir(parents=True, exist_ok=False)
    progress = _BuildProgress(
        run_root,
        f"Repair retained failed build: {target}",
        task_id,
    )
    progress.emit(
        actor="Nexuss",
        phase="preparing",
        message=(
            f"Recovered failed run {source_run_root.name}; validating its retained candidate before any provider call."
        ),
    )

    _assert_candidate_baseline_matches_live(repo, workspace_root)
    initial_fingerprint = _worktree_fingerprint(repo)
    workspace = IsolatedWorkspace(
        workspace_root,
        policy=WorkspacePolicy(
            max_file_bytes=2_000_000,
            max_output_chars=80_000,
            command_timeout_seconds=300,
            allowed_executables=frozenset({"python", "python3", "pytest", "git"}),
            allowed_git_subcommands=frozenset({"status", "diff", "log", "show", "rev-parse"}),
        ),
    )
    changed_files = _hydrate_changed_files(workspace)
    if not changed_files:
        raise EngineeringError(
            "ENGINEERING_REPAIR_CANDIDATE_EMPTY",
            "The retained failed build has no recoverable file changes.",
            safe_details={"source_run_id": source_run_root.name},
        )

    progress.emit(
        actor="Nexuss",
        phase="regression_verification",
        message="Re-running deterministic validation on the retained failed candidate.",
        changed_file_count=len(changed_files),
    )
    post_code, post_output, post_nodes = _run_full_pytest(workspace_root)
    if post_code not in {0, 1}:
        raise EngineeringError(
            "ENGINEERING_REPAIR_VALIDATION_INVALID",
            "The retained candidate did not produce a normal pytest pass/fail result.",
            safe_details={"pytest_exit_code": post_code, "source_run_id": source_run_root.name},
        )
    new_nodes = tuple(sorted(set(post_nodes) - set(baseline)))

    provider_calls = 0
    provider_model = "none"
    if new_nodes:
        connections = EngineeringProviderConnectionService(DpapiSecretVault(), timeout_seconds=60.0)
        access = connections.deepseek_access()
        if not access.available:
            raise EngineeringError(access.code.value.upper(), access.user_message)
        profile = connections.deepseek_profile(access.model)
        api_key = ProviderCredentialStore(DpapiSecretVault()).get_api_key("deepseek")
        agent = _DeepSeekNativeAgent(
            api_key,
            profile.model,
            profile.api_base,
            profile.max_output_tokens,
        )
        provider_model = profile.model

        diff = _run(["git", "diff", "--no-ext-diff", "HEAD", "--"], workspace_root, timeout=120)
        before_hashes = {
            relative: _sha256_file(workspace_root / relative)
            for relative in workspace.changed_files
            if (workspace_root / relative).is_file()
        }
        progress.emit(
            actor="DeepSeek",
            phase="repair",
            message=(
                f"Running one targeted repair call for {len(new_nodes)} exact new regression failure(s)."
            ),
            round_number=1,
            changed_file_count=len(workspace.changed_files),
        )
        context = {
            "original_task_id": original_task_id,
            "source_run_id": source_run_root.name,
            "diagnostic_artifact": str(artifact),
            "original_goal": original_goal,
            "repair_request": target,
            "new_failure_nodes": list(new_nodes),
            "validation_output_tail": post_output[-35_000:] or validation_output[-35_000:],
            "candidate_diff": (diff.stdout + diff.stderr)[-45_000:],
            "changed_file_snapshots": _changed_file_payload(workspace),
            "failing_test_sources": _relevant_failure_sources(workspace_root, new_nodes),
            "instruction": (
                "This is the only paid repair call. Use the exact failure evidence and source snapshots supplied. "
                "Do not browse. Issue concrete workspace_write_file calls that repair the existing candidate. "
                "Modify only files already changed by the failed candidate. Do not edit existing tests, weaken assertions, "
                "redesign the feature, or modify unrelated files."
            ),
        }
        proposal = agent.propose(
            goal=f"Repair retained failed build: {original_goal}",
            phase="write_required",
            context=context,
            allowed=(ToolName.WRITE_FILE,),
        )
        provider_calls = 1
        allowed_repair_paths = set(workspace.changed_files)
        repair_requests = tuple(
            request
            for request in proposal.tool_requests
            if request.tool_name is ToolName.WRITE_FILE
            and Path(str(request.arguments.get("path", ""))).as_posix().lstrip("./")
            in allowed_repair_paths
        )
        if not repair_requests:
            raise EngineeringError(
                "ENGINEERING_ECONOMIC_NO_PROGRESS",
                "The single targeted repair call produced no permitted correction to the retained changed file(s).",
                safe_details={
                    "source_run_id": source_run_root.name,
                    "new_failure_nodes": list(new_nodes),
                    "permitted_paths": sorted(allowed_repair_paths),
                },
            )
        outputs = _execute_requests(
            repair_requests,
            registry=WorkspaceToolRegistry(workspace),
            workspace=workspace,
            read_hashes=before_hashes,
            cache={},
            progress=progress,
            round_number=1,
        )
        del outputs
        after_hashes = {
            relative: _sha256_file(workspace_root / relative)
            for relative in workspace.changed_files
            if (workspace_root / relative).is_file()
        }
        if after_hashes == before_hashes:
            raise EngineeringError(
                "ENGINEERING_ECONOMIC_NO_PROGRESS",
                "The targeted repair call did not make a meaningful candidate change.",
                safe_details={"source_run_id": source_run_root.name},
            )

        _syntax_check_changed(workspace)
        exact_code, exact_output = _run_failure_nodes(workspace_root, new_nodes)
        if exact_code != 0:
            post_output = exact_output
        post_code, post_output, post_nodes = _run_full_pytest(workspace_root)
        if post_code not in {0, 1}:
            raise EngineeringError(
                "ENGINEERING_REPAIR_VALIDATION_INVALID",
                "The repaired candidate did not produce a normal pytest pass/fail result.",
                safe_details={"pytest_exit_code": post_code},
            )
        new_nodes = tuple(sorted(set(post_nodes) - set(baseline)))

    success = not new_nodes
    progress.emit(
        actor="Nexuss",
        phase="packaging",
        message=(
            "The retained candidate is regression-clean; packaging the repaired artifact."
            if success
            else "The targeted repair still has new regressions; packaging diagnostics without live application."
        ),
        changed_file_count=len(workspace.changed_files),
    )
    repaired_artifact, artifact_sha = _proposal_zip(
        workspace=workspace,
        goal=original_goal,
        baseline_nodes=baseline,
        post_nodes=post_nodes,
        validation_output=post_output,
        model=provider_model,
        success=success,
    )

    applied = False
    backup_path: str | None = None
    if success and os.getenv(_APPLY_ENV, "0").strip() == "1":
        baseline_hashes = {
            relative: _sha256_file(repo / relative)
            for relative in workspace.changed_files
            if (repo / relative).is_file()
        }
        progress.emit(
            actor="Nexuss",
            phase="applying",
            message="Applying the repaired regression-clean candidate with rollback backup.",
            changed_file_count=len(workspace.changed_files),
        )
        backup_path = _apply_live(
            repo=repo,
            workspace=workspace,
            baseline_hashes=baseline_hashes,
            initial_fingerprint=initial_fingerprint,
        )
        applied = True

    elapsed = time.monotonic() - started
    code = "ENGINEERING_REPAIR_SUCCESS" if success else "ENGINEERING_REPAIR_REGRESSION_FAILED"
    message = (
        "The retained failed candidate was repaired and passed baseline-aware regression verification. "
        + (
            "It was applied with a rollback backup; restart Nexuss and perform requirement-level acceptance."
            if applied
            else "The live repository was not changed."
        )
        if success
        else "The single targeted repair did not eliminate every new regression; live Nexuss was not changed."
    )
    progress.emit(
        actor="Nexuss",
        phase="completed" if success else "failed",
        message=message,
        changed_file_count=len(workspace.changed_files),
        terminal=True,
        code=code,
    )
    outcome = BuildOutcome(
        success=success,
        code=code,
        message=message,
        provider="deepseek" if provider_calls else "deterministic_local",
        model=provider_model,
        workspace=str(workspace_root),
        artifact_zip=str(repaired_artifact),
        artifact_sha256=artifact_sha,
        changed_files=workspace.changed_files,
        baseline_failures=baseline,
        new_failures=new_nodes,
        applied_to_live_repository=applied,
        backup_path=backup_path,
        restart_required=applied,
        elapsed_seconds=elapsed,
    )
    return outcome


def run_prompt_build(goal: str, *, task_id: UUID | None = None) -> BuildOutcome:
    started = time.monotonic()
    repo = _repo_root()
    initial_fingerprint = _worktree_fingerprint(repo)
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_root = local / "Nexuss" / "engineering-runs" / f"prompt-build-{stamp}"
    workspace_root = run_root / "workspace"
    run_root.mkdir(parents=True, exist_ok=True)
    progress = _BuildProgress(run_root, goal, task_id)
    baseline_hashes = _copy_worktree(repo, workspace_root)
    progress.emit(
        actor="Nexuss",
        phase="preparing",
        message="Isolated workspace created; capturing the regression baseline.",
    )
    workspace = IsolatedWorkspace(
        workspace_root,
        policy=WorkspacePolicy(
            max_file_bytes=2_000_000,
            max_output_chars=80_000,
            command_timeout_seconds=300,
            allowed_executables=frozenset({"python", "python3", "pytest", "git"}),
            allowed_git_subcommands=frozenset({"status", "diff", "log", "show", "rev-parse"}),
        ),
    )
    progress.emit(
        actor="Nexuss",
        phase="baseline",
        message="Checking the known regression baseline.",
    )
    baseline = _baseline_nodes(workspace_root, initial_fingerprint)
    progress.emit(
        actor="Nexuss",
        phase="baseline",
        message=f"Baseline ready with {len(baseline)} known failing/error node(s).",
    )

    connections = EngineeringProviderConnectionService(DpapiSecretVault(), timeout_seconds=60.0)
    access = connections.deepseek_access()
    if not access.available:
        raise EngineeringError(access.code.value.upper(), access.user_message)
    profile = connections.deepseek_profile(access.model)
    api_key = ProviderCredentialStore(DpapiSecretVault()).get_api_key("deepseek")
    agent = _DeepSeekNativeAgent(api_key, profile.model, profile.api_base, profile.max_output_tokens)
    progress.emit(
        actor="DeepSeek",
        phase="deepseek",
        message=f"Connected to {profile.model}; beginning isolated engineering work.",
    )

    _rounds, _history = _build_with_agent(
        goal=goal,
        workspace=workspace,
        agent=agent,
        progress=progress,
    )
    if not workspace.changed_files:
        progress.emit(
            actor="Nexuss",
            phase="failed",
            message="DeepSeek completed the bounded engineering window without producing a file change.",
            changed_file_count=0,
            terminal=True,
            code="ENGINEERING_NO_IMPLEMENTATION_PRODUCED",
        )
        raise EngineeringError(
            "ENGINEERING_NO_IMPLEMENTATION_PRODUCED",
            "DeepSeek inspected the isolated Nexuss source but produced no file changes.",
            safe_details={"model_rounds": _rounds},
        )

    progress.emit(
        actor="Nexuss",
        phase="syntax_verification",
        message=f"Verifying syntax for {len(workspace.changed_files)} changed file(s).",
        changed_file_count=len(workspace.changed_files),
    )
    _syntax_check_changed(workspace)
    progress.emit(
        actor="Nexuss",
        phase="regression_verification",
        message="Running the full baseline-aware regression suite.",
        changed_file_count=len(workspace.changed_files),
    )
    post_code, post_output, post_nodes = _run_full_pytest(workspace_root)
    validation_normal = post_code in {0, 1}
    new_nodes = tuple(sorted(set(post_nodes) - set(baseline)))
    repair_rounds = 0
    while validation_normal and new_nodes and repair_rounds < _MAX_REPAIR_ROUNDS:
        repair_rounds += _repair(
            goal=goal,
            workspace=workspace,
            agent=agent,
            failure_output=post_output,
            failure_nodes=new_nodes,
            progress=progress,
        )
        _syntax_check_changed(workspace)
        post_code, post_output, post_nodes = _run_full_pytest(workspace_root)
        validation_normal = post_code in {0, 1}
        if not validation_normal:
            break
        updated = tuple(sorted(set(post_nodes) - set(baseline)))
        if updated == new_nodes:
            break
        new_nodes = updated

    success = validation_normal and not new_nodes
    progress.emit(
        actor="Nexuss",
        phase="packaging",
        message=(
            "Regression gate passed; packaging the verified engineering artifact."
            if success
            else "Validation finished; packaging the diagnostic engineering artifact."
        ),
        changed_file_count=len(workspace.changed_files),
    )
    artifact, artifact_sha = _proposal_zip(
        workspace=workspace,
        goal=goal,
        baseline_nodes=baseline,
        post_nodes=post_nodes,
        validation_output=post_output,
        model=profile.model,
        success=success,
    )
    applied = False
    backup_path: str | None = None
    if success and os.getenv(_APPLY_ENV, "0").strip() == "1":
        progress.emit(
            actor="Nexuss",
            phase="applying",
            message="Applying the regression-clean build to live source with rollback backup.",
            changed_file_count=len(workspace.changed_files),
        )
        backup_path = _apply_live(
            repo=repo,
            workspace=workspace,
            baseline_hashes=baseline_hashes,
            initial_fingerprint=initial_fingerprint,
        )
        applied = True

    elapsed = time.monotonic() - started
    if success:
        message = (
            "The generated Nexuss build passed baseline-aware regression validation. "
            + (
                "It was applied to the live source with a backup; restart Nexuss "
                "and run requirement-level acceptance verification."
                if applied
                else (
                    "A regression-clean proposal ZIP was produced; the live source "
                    "was not changed and requirement-level acceptance remains pending."
                )
            )
        )
        code = "ENGINEERING_BUILD_SUCCESS"
    else:
        if not validation_normal:
            message = (
                "The isolated build could not prove correctness because pytest returned "
                f"controller/collection exit code {post_code}; live Nexuss was not changed."
            )
            code = "ENGINEERING_BUILD_VALIDATION_INVALID"
        else:
            message = "The isolated build introduced new regression failures and was not applied to live Nexuss."
            code = "ENGINEERING_BUILD_REGRESSION_FAILED"

    progress.emit(
        actor="Nexuss",
        phase="completed" if success else "failed",
        message=message,
        changed_file_count=len(workspace.changed_files),
        terminal=True,
        code=code,
    )

    return BuildOutcome(
        success=success,
        code=code,
        message=message,
        provider="deepseek",
        model=profile.model,
        workspace=str(workspace_root),
        artifact_zip=str(artifact),
        artifact_sha256=artifact_sha,
        changed_files=workspace.changed_files,
        baseline_failures=baseline,
        new_failures=new_nodes,
        applied_to_live_repository=applied,
        backup_path=backup_path,
        restart_required=applied,
        elapsed_seconds=elapsed,
    )


def execute_prompt_build(
    step: PlanStep,
    timestamp: datetime,
    *,
    task_id: UUID | None = None,
) -> CapabilityResult:
    if os.getenv(_ENABLED_ENV, "0").strip() != "1":
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[],
            error_code="DEVELOPER_SELF_BUILD_DISABLED",
        )
    goal = str(step.parameters.get("goal", "")).strip()
    if not goal:
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[],
            error_code="ENGINEERING_BUILD_GOAL_MISSING",
        )
    try:
        outcome = run_prompt_build(goal, task_id=task_id)
    except EngineeringError as exc:
        mark_latest_prompt_build_failed(goal, exc.code, exc.message)
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[
                EvidenceRecord(
                    source="local:engineering_prompt_build",
                    observed_at=timestamp,
                    attributes={
                        "source_mode": "isolated_developer_self_build",
                        "goal": goal,
                        "error_code": exc.code,
                        "error_details": exc.safe_details,
                        "progress": latest_prompt_build_progress(),
                        "credentials_exposed": False,
                        "live_repository_modified": False,
                    },
                )
            ],
            error_code=exc.code,
        )

    except Exception as exc:
        # Never let an unexpected capability exception escape far enough for
        # Core to misreport that the governed task did not exist.
        code = "ENGINEERING_UNEXPECTED_EXECUTION_FAILURE"
        message = (
            "The isolated engineering worker stopped unexpectedly "
            f"({type(exc).__name__}) and failed closed."
        )
        mark_latest_prompt_build_failed(goal, code, message)
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[
                EvidenceRecord(
                    source="local:engineering_prompt_build",
                    observed_at=timestamp,
                    attributes={
                        "source_mode": "isolated_developer_self_build",
                        "goal": goal,
                        "error_code": code,
                        "error_type": type(exc).__name__,
                        "progress": latest_prompt_build_progress(),
                        "credentials_exposed": False,
                        "live_repository_modified": False,
                    },
                )
            ],
            error_code=code,
        )

    attributes = {
        "source_mode": "isolated_developer_self_build",
        "goal": goal,
        "result_code": outcome.code,
        "message": outcome.message,
        "provider": outcome.provider,
        "model": outcome.model,
        "workspace": outcome.workspace,
        "artifact_zip": outcome.artifact_zip,
        "artifact_sha256": outcome.artifact_sha256,
        "engineering_build_receipt": {
            "result_code": outcome.code,
            "artifact_zip": outcome.artifact_zip,
            "changed_file_count": len(outcome.changed_files),
            "applied_to_live_repository": outcome.applied_to_live_repository,
            "acceptance_status": "post_restart_verification_required",
        },
        "sha256_verification": {
            "algorithm": "sha256",
            "artifact_sha256": outcome.artifact_sha256,
            "verified": bool(outcome.artifact_sha256),
        },
        "progress": latest_prompt_build_progress(),
        "changed_files": list(outcome.changed_files),
        "changed_file_count": len(outcome.changed_files),
        "baseline_failure_count": len(outcome.baseline_failures),
        "new_regression_count": len(outcome.new_failures),
        "new_regressions": list(outcome.new_failures),
        "applied_to_live_repository": outcome.applied_to_live_repository,
        "backup_path": outcome.backup_path,
        "restart_required": outcome.restart_required,
        "credentials_exposed": False,
        "elapsed_seconds": round(outcome.elapsed_seconds, 3),
    }
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED if outcome.success else StepStatus.FAILED,
        evidence=[
            EvidenceRecord(
                source="local:engineering_prompt_build",
                observed_at=timestamp,
                attributes=attributes,
            )
        ],
        error_code=None if outcome.success else outcome.code,
    )

def execute_latest_failed_build_repair(
    step: PlanStep,
    timestamp: datetime,
    *,
    task_id: UUID | None = None,
) -> CapabilityResult:
    if os.getenv(_ENABLED_ENV, "0").strip() != "1":
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[],
            error_code="DEVELOPER_SELF_BUILD_DISABLED",
        )
    target = str(step.parameters.get("target", "latest failed engineering build")).strip()
    try:
        recovered = _latest_failed_build_context()
        source_progress = recovered["progress"]
        source_run_root = recovered["run_root"]
        artifact = recovered["artifact"]
        assert isinstance(source_progress, dict)
        assert isinstance(source_run_root, Path)
        assert isinstance(artifact, Path)
        original_task_id = str(source_progress.get("core_task_id") or "")
        outcome = run_latest_failed_build_repair(target, task_id=task_id)
    except EngineeringError as exc:
        mark_latest_prompt_build_failed(
            f"Repair retained failed build: {target}",
            exc.code,
            exc.message,
        )
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[
                EvidenceRecord(
                    source="local:engineering_repair",
                    observed_at=timestamp,
                    attributes={
                        "source_mode": "retained_failed_build_repair",
                        "target": target,
                        "error_code": exc.code,
                        "error_details": exc.safe_details,
                        "progress": latest_prompt_build_progress(),
                        "credentials_exposed": False,
                        "live_repository_modified": False,
                    },
                )
            ],
            error_code=exc.code,
        )

    except Exception as exc:
        code = "ENGINEERING_REPAIR_UNEXPECTED_FAILURE"
        message = (
            "The retained engineering repair stopped unexpectedly "
            f"({type(exc).__name__}) and failed closed."
        )
        mark_latest_prompt_build_failed(
            f"Repair retained failed build: {target}",
            code,
            message,
        )
        return CapabilityResult(
            step_id=step.step_id,
            capability_id=step.capability_id,
            status=StepStatus.FAILED,
            evidence=[
                EvidenceRecord(
                    source="local:engineering_repair",
                    observed_at=timestamp,
                    attributes={
                        "source_mode": "retained_failed_build_repair",
                        "target": target,
                        "error_code": code,
                        "error_type": type(exc).__name__,
                        "progress": latest_prompt_build_progress(),
                        "credentials_exposed": False,
                        "live_repository_modified": False,
                    },
                )
            ],
            error_code=code,
        )

    attributes = {
        "source_mode": "retained_failed_build_repair",
        "target": target,
        "original_task_id": original_task_id,
        "source_run_id": source_run_root.name,
        "source_diagnostic_artifact": str(artifact),
        "result_code": outcome.code,
        "message": outcome.message,
        "provider": outcome.provider,
        "model": outcome.model,
        "workspace": outcome.workspace,
        "artifact_zip": outcome.artifact_zip,
        "artifact_sha256": outcome.artifact_sha256,
        "engineering_repair_receipt": {
            "original_task_id": original_task_id,
            "source_run_id": source_run_root.name,
            "result_code": outcome.code,
            "changed_files": list(outcome.changed_files),
            "new_regressions": list(outcome.new_failures),
            "applied_to_live_repository": outcome.applied_to_live_repository,
            "restart_required": outcome.restart_required,
        },
        "regression_verification": {
            "baseline_failures": list(outcome.baseline_failures),
            "new_regressions": list(outcome.new_failures),
            "verified": outcome.success,
        },
        "sha256_verification": {
            "algorithm": "sha256",
            "artifact_sha256": outcome.artifact_sha256,
            "verified": bool(outcome.artifact_sha256),
        },
        "backup_path": outcome.backup_path,
        "restart_required": outcome.restart_required,
        "credentials_exposed": False,
        "progress": latest_prompt_build_progress(),
    }
    return CapabilityResult(
        step_id=step.step_id,
        capability_id=step.capability_id,
        status=StepStatus.VERIFIED if outcome.success else StepStatus.FAILED,
        evidence=[
            EvidenceRecord(
                source="local:engineering_repair",
                observed_at=timestamp,
                attributes=attributes,
            )
        ],
        error_code=None if outcome.success else outcome.code,
    )

