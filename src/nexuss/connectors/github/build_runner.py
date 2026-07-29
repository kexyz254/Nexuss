"""Fail-closed build planning and explicitly enabled trusted-local execution."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from nexuss.connectors.github.operation_models import (
    BuildCommandPlan,
    BuildCommandResult,
    BuildExecutionMode,
    BuildPlan,
    BuildRunReceipt,
    RepositorySnapshot,
    SourceAnalysisReport,
)

_ALLOWED_EXECUTABLES = {
    "python",
    "python3",
    "node",
    "npm",
    "cargo",
    "go",
    "cmake",
    "ctest",
    "mvn",
    "dotnet",
}


class BuildExecutionDenied(RuntimeError):
    pass


class GitHubBuildRunner:
    """Generate deterministic plans; execute only under explicit local policy."""

    def plan(
        self,
        snapshot: RepositorySnapshot,
        analysis: SourceAnalysisReport,
    ) -> BuildPlan:
        commands: list[BuildCommandPlan] = []
        names = {item.path for item in analysis.dependency_manifests}
        build_systems = set(analysis.build_systems)

        if "pyproject.toml" in names or "requirements.txt" in names:
            commands.extend(
                [
                    BuildCommandPlan(
                        label="python-compile",
                        argv=("python", "-m", "compileall", "-q", "."),
                        reason="Compile Python source without installing dependencies.",
                        executes_repository_code=False,
                    ),
                    BuildCommandPlan(
                        label="python-tests",
                        argv=("python", "-m", "pytest", "-q"),
                        reason="Run the repository test suite if pytest is available.",
                        executes_repository_code=True,
                    ),
                ]
            )
        if "package.json" in names:
            commands.extend(
                [
                    BuildCommandPlan(
                        label="node-package-metadata",
                        argv=("node", "--check", "package.json"),
                        reason="Syntax-check package metadata as JavaScript-compatible input.",
                        executes_repository_code=False,
                    ),
                    BuildCommandPlan(
                        label="node-tests",
                        argv=("npm", "test", "--", "--runInBand"),
                        reason="Run the declared Node.js test script without installing packages.",
                        executes_repository_code=True,
                    ),
                ]
            )
        if "Cargo" in build_systems:
            commands.append(
                BuildCommandPlan(
                    label="cargo-tests",
                    argv=("cargo", "test", "--locked"),
                    reason="Run locked Rust tests without dependency mutation.",
                    executes_repository_code=True,
                )
            )
        if "Go modules" in build_systems:
            commands.append(
                BuildCommandPlan(
                    label="go-tests",
                    argv=("go", "test", "./..."),
                    reason="Run Go package tests.",
                    executes_repository_code=True,
                )
            )
        if "CMake" in build_systems:
            commands.extend(
                [
                    BuildCommandPlan(
                        label="cmake-configure",
                        argv=("cmake", "-S", ".", "-B", "build", "-DBUILD_TESTING=ON"),
                        reason="Configure a separate CMake build directory.",
                        executes_repository_code=True,
                    ),
                    BuildCommandPlan(
                        label="cmake-build",
                        argv=("cmake", "--build", "build", "--parallel", "2"),
                        reason="Build the configured CMake project.",
                        executes_repository_code=True,
                    ),
                    BuildCommandPlan(
                        label="cmake-tests",
                        argv=("ctest", "--test-dir", "build", "--output-on-failure"),
                        reason="Run CTest targets after a successful build.",
                        executes_repository_code=True,
                    ),
                ]
            )
        if "Maven" in build_systems:
            commands.append(
                BuildCommandPlan(
                    label="maven-tests",
                    argv=("mvn", "-B", "test"),
                    reason="Run Maven tests without interactive prompts.",
                    executes_repository_code=True,
                )
            )
        if ".NET" in {item.ecosystem for item in analysis.dependency_manifests}:
            commands.append(
                BuildCommandPlan(
                    label="dotnet-tests",
                    argv=("dotnet", "test", "--nologo"),
                    reason="Run .NET tests.",
                    executes_repository_code=True,
                )
            )

        enabled = os.getenv("NEXUSS_GITHUB_WORKSPACE_TRUSTED_LOCAL", "0") == "1"
        mode = BuildExecutionMode.TRUSTED_LOCAL if enabled else BuildExecutionMode.PLAN_ONLY
        boundary = (
            "Trusted-local execution is enabled by operator configuration. "
            "The child process receives no GitHub token or connector-vault path, but this is not "
            "an operating-system security sandbox."
            if enabled
            else
            "Execution is disabled. Set NEXUSS_GITHUB_WORKSPACE_TRUSTED_LOCAL=1 only for "
            "repositories the operator trusts, or install a future sandbox adapter."
        )
        return BuildPlan(
            snapshot_id=snapshot.snapshot_id,
            repository_full_name=snapshot.repository_full_name,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            mode=mode,
            commands=tuple(commands),
            execution_allowed=enabled and bool(commands),
            execution_boundary=boundary,
        )

    def execute(
        self,
        snapshot: RepositorySnapshot,
        plan: BuildPlan,
        *,
        timeout_seconds: int = 300,
    ) -> BuildRunReceipt:
        if plan.snapshot_id != snapshot.snapshot_id:
            raise BuildExecutionDenied("Build plan belongs to another snapshot")
        if plan.mode is not BuildExecutionMode.TRUSTED_LOCAL or not plan.execution_allowed:
            raise BuildExecutionDenied(plan.execution_boundary)
        timeout = max(5, min(timeout_seconds, 1_800))
        source = Path(snapshot.workspace_root).resolve()
        temporary = Path(tempfile.mkdtemp(prefix="nexuss-build-"))
        workspace = temporary / "workspace"
        results: list[BuildCommandResult] = []
        try:
            shutil.copytree(
                source,
                workspace,
                ignore=shutil.ignore_patterns("NEXUSS-SNAPSHOT.json"),
            )
            self._make_writable(workspace)
            environment = self._safe_environment(temporary)
            for command in plan.commands:
                executable = Path(command.argv[0]).name.casefold()
                if executable not in _ALLOWED_EXECUTABLES:
                    raise BuildExecutionDenied("Build plan contains a non-allowlisted executable")
                try:
                    completed = subprocess.run(
                        list(command.argv),
                        cwd=workspace,
                        env=environment,
                        shell=False,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=timeout,
                        check=False,
                    )
                    output = completed.stdout[:100_000]
                    result = BuildCommandResult(
                        label=command.label,
                        argv=command.argv,
                        exit_code=completed.returncode,
                        output=output,
                        timed_out=False,
                        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                    )
                except subprocess.TimeoutExpired as exc:
                    raw = exc.stdout or ""
                    output = raw if isinstance(raw, str) else raw.decode(errors="replace")
                    output = output[:100_000]
                    result = BuildCommandResult(
                        label=command.label,
                        argv=command.argv,
                        exit_code=124,
                        output=output,
                        timed_out=True,
                        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                    )
                except OSError as exc:
                    output = f"Executable unavailable: {type(exc).__name__}"
                    result = BuildCommandResult(
                        label=command.label,
                        argv=command.argv,
                        exit_code=127,
                        output=output,
                        output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                    )
                results.append(result)
                if result.exit_code != 0:
                    break
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

        evidence_payload = {
            "snapshot_id": str(snapshot.snapshot_id),
            "plan_id": str(plan.plan_id),
            "repository": snapshot.repository_full_name,
            "commit": snapshot.resolved_commit_sha,
            "commands": [item.model_dump(mode="json") for item in results],
        }
        evidence = hashlib.sha256(
            json.dumps(
                evidence_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        return BuildRunReceipt(
            plan_id=plan.plan_id,
            snapshot_id=snapshot.snapshot_id,
            repository_full_name=snapshot.repository_full_name,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            mode=plan.mode,
            completed=bool(results) and all(item.exit_code == 0 for item in results),
            commands=tuple(results),
            workspace_deleted=not temporary.exists(),
            network_isolation_claimed=False,
            evidence_sha256=evidence,
        )

    @staticmethod
    def _safe_environment(temporary: Path) -> dict[str, str]:
        allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC"}
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in allowed
        }
        environment.update(
            {
                "HOME": str(temporary / "home"),
                "USERPROFILE": str(temporary / "home"),
                "TEMP": str(temporary / "temp"),
                "TMP": str(temporary / "temp"),
                "GIT_TERMINAL_PROMPT": "0",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INPUT": "1",
                "NPM_CONFIG_FUND": "false",
                "NPM_CONFIG_AUDIT": "false",
            }
        )
        Path(environment["HOME"]).mkdir(parents=True, exist_ok=True)
        Path(environment["TEMP"]).mkdir(parents=True, exist_ok=True)
        return environment

    @staticmethod
    def _make_writable(root: Path) -> None:
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    path.chmod(0o600)
                except OSError:
                    continue
