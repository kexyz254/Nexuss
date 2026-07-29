"""Deterministic source-tree analysis for immutable repository snapshots."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from nexuss.connectors.github.operation_models import (
    DependencyManifestSummary,
    RepositorySnapshot,
    SourceAnalysisReport,
    SourceLanguageSummary,
)

_LANGUAGE_BY_SUFFIX = {
    ".c": "C",
    ".h": "C/C++ Header",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C++ Header",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".rs": "Rust",
    ".go": "Go",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sh": "Shell",
    ".ps1": "PowerShell",
    ".sql": "SQL",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".vue": "Vue",
    ".svelte": "Svelte",
}

_MANIFESTS = {
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "requirements-dev.txt": "Python",
    "Pipfile": "Python",
    "poetry.lock": "Python",
    "uv.lock": "Python",
    "package.json": "Node.js",
    "package-lock.json": "Node.js",
    "pnpm-lock.yaml": "Node.js",
    "yarn.lock": "Node.js",
    "Cargo.toml": "Rust",
    "Cargo.lock": "Rust",
    "go.mod": "Go",
    "go.sum": "Go",
    "pom.xml": "Maven",
    "build.gradle": "Gradle",
    "build.gradle.kts": "Gradle",
    "settings.gradle": "Gradle",
    "settings.gradle.kts": "Gradle",
    "CMakeLists.txt": "CMake",
    "Makefile": "Make",
    "meson.build": "Meson",
    "WORKSPACE": "Bazel",
    "MODULE.bazel": "Bazel",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "Package.swift": "Swift",
    "global.json": ".NET",
}

_BUILD_SYSTEM_FILES = {
    "pyproject.toml": "Python packaging",
    "setup.py": "Setuptools",
    "package.json": "Node.js scripts",
    "Cargo.toml": "Cargo",
    "go.mod": "Go modules",
    "pom.xml": "Maven",
    "build.gradle": "Gradle",
    "build.gradle.kts": "Gradle",
    "CMakeLists.txt": "CMake",
    "Makefile": "Make",
    "meson.build": "Meson",
    "WORKSPACE": "Bazel",
    "MODULE.bazel": "Bazel",
}

_ENTRY_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "manage.py",
    "index.js",
    "index.ts",
    "main.js",
    "main.ts",
    "main.rs",
    "main.go",
    "Main.java",
    "Program.cs",
}

_SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
    "__pycache__",
}


class GitHubRepositoryAnalyzer:
    def analyze(self, snapshot: RepositorySnapshot) -> SourceAnalysisReport:
        root = Path(snapshot.workspace_root).resolve()
        if not root.is_dir():
            raise FileNotFoundError("Repository snapshot directory is missing")

        language_files: dict[str, int] = defaultdict(int)
        language_bytes: dict[str, int] = defaultdict(int)
        manifests: list[DependencyManifestSummary] = []
        build_systems: set[str] = set()
        entry_points: set[str] = set()
        test_targets: set[str] = set()
        architecture_hints: set[str] = set()
        oversized: list[str] = []
        source_files = 0
        test_files = 0
        documentation_files = 0
        binary_files = 0

        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name == "NEXUSS-SNAPSHOT.json":
                continue
            relative = path.relative_to(root).as_posix()
            if any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts):
                continue
            size = path.stat().st_size
            if size > 5_000_000:
                oversized.append(relative)

            language = _LANGUAGE_BY_SUFFIX.get(path.suffix.casefold())
            if language:
                source_files += 1
                language_files[language] += 1
                language_bytes[language] += size
            elif self._is_binary(path):
                binary_files += 1

            lower_parts = tuple(part.casefold() for part in path.relative_to(root).parts)
            lower_name = path.name.casefold()
            if (
                "test" in lower_parts
                or "tests" in lower_parts
                or lower_name.startswith("test_")
                or lower_name.endswith(
                    ("_test.py", "test.java", "_test.go")
                )
            ):
                test_files += 1
                test_targets.add(relative)

            if path.suffix.casefold() in {".md", ".rst", ".adoc", ".txt"}:
                documentation_files += 1

            if path.name in _ENTRY_NAMES or lower_name in {
                name.casefold() for name in _ENTRY_NAMES
            }:
                entry_points.add(relative)

            ecosystem = _MANIFESTS.get(path.name)
            if ecosystem:
                manifests.append(
                    DependencyManifestSummary(
                        path=relative,
                        ecosystem=ecosystem,
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
            system = _BUILD_SYSTEM_FILES.get(path.name)
            if system:
                build_systems.add(system)

        top_level_directories = sorted(
            path.name
            for path in root.iterdir()
            if path.is_dir() and path.name not in _SKIP_DIRECTORIES
        )
        for name in top_level_directories:
            architecture_hints.add(f"Top-level module directory: {name}")
        if (root / "src").is_dir():
            architecture_hints.add("Uses a src-layout source tree")
        if (root / "lib").is_dir():
            architecture_hints.add("Contains a library-oriented lib directory")
        if (root / "apps").is_dir() or (root / "packages").is_dir():
            architecture_hints.add("Possible multi-package or monorepo layout")
        if (root / ".github" / "workflows").is_dir():
            architecture_hints.add("GitHub Actions workflows are present")
        container_files = {"Dockerfile", "compose.yaml", "docker-compose.yml"}
        if any((root / name).is_file() for name in container_files):
            architecture_hints.add("Container build or orchestration files are present")

        languages = tuple(
            SourceLanguageSummary(
                language=language,
                files=language_files[language],
                bytes=language_bytes[language],
            )
            for language in sorted(
                language_files,
                key=lambda item: (-language_bytes[item], item),
            )
        )
        evidence_payload = {
            "snapshot_id": str(snapshot.snapshot_id),
            "repository": snapshot.repository_full_name,
            "commit": snapshot.resolved_commit_sha,
            "languages": [item.model_dump() for item in languages],
            "build_systems": sorted(build_systems),
            "dependency_manifests": [
                item.model_dump() for item in sorted(manifests, key=lambda item: item.path)
            ],
            "entry_points": sorted(entry_points),
            "test_targets": sorted(test_targets),
            "source_files": source_files,
            "test_files": test_files,
            "documentation_files": documentation_files,
            "binary_files": binary_files,
            "oversized_files": sorted(oversized),
            "architecture_hints": sorted(architecture_hints),
        }
        evidence_sha = hashlib.sha256(
            json.dumps(
                evidence_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        return SourceAnalysisReport(
            snapshot_id=snapshot.snapshot_id,
            repository_full_name=snapshot.repository_full_name,
            resolved_commit_sha=snapshot.resolved_commit_sha,
            languages=languages,
            build_systems=tuple(sorted(build_systems)),
            dependency_manifests=tuple(sorted(manifests, key=lambda item: item.path)),
            likely_entry_points=tuple(sorted(entry_points)),
            test_targets=tuple(sorted(test_targets)[:500]),
            source_files=source_files,
            test_files=test_files,
            documentation_files=documentation_files,
            binary_files=binary_files,
            oversized_files=tuple(sorted(oversized)),
            architecture_hints=tuple(sorted(architecture_hints)),
            evidence_sha256=evidence_sha,
        )

    @staticmethod
    def _is_binary(path: Path) -> bool:
        try:
            sample = path.read_bytes()[:8_192]
        except OSError:
            return True
        if b"\x00" in sample:
            return True
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return True
        return False
