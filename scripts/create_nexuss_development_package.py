"""Create a deterministic Nexuss development-package ZIP without modifying the repo."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

_WINDOWS_RESERVED = frozenset({
    "aux", "con", "nul", "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str) -> str:
    converted = value.replace("\\", "/").strip()
    path = PurePosixPath(converted)
    if not converted or converted.startswith("/") or not path.parts:
        raise ValueError(f"invalid repository path: {value!r}")
    normalized_parts: list[str] = []
    for part in path.parts:
        if part in {"", ".", ".."}:
            raise ValueError(f"invalid repository path: {value!r}")
        if ":" in part or any(ord(character) < 32 for character in part):
            raise ValueError(f"invalid repository path: {value!r}")
        if part.rstrip(" .") != part:
            raise ValueError(f"invalid repository path: {value!r}")
        if part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED:
            raise ValueError(f"invalid repository path: {value!r}")
        normalized_parts.append(part)
    return PurePosixPath(*normalized_parts).as_posix()


def git_head(repo: Path) -> str | None:
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and len(value) == 40 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--focused-test", action="append", default=[])
    parser.add_argument("--delete-path", action="append", default=[])
    parser.add_argument("--trust-boundary-change", action="store_true")
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()

    repo = args.repository.expanduser().resolve()
    payload_root = args.payload_root.expanduser().resolve()
    if not (repo / ".git").is_dir():
        raise SystemExit(f"STOP: not a Git repository: {repo}")
    if not payload_root.is_dir():
        raise SystemExit(f"STOP: payload root does not exist: {payload_root}")

    entries: list[dict[str, object]] = []
    payload_files: list[tuple[Path, str]] = []
    seen: set[str] = set()

    for source in sorted(path for path in payload_root.rglob("*") if path.is_file()):
        relative = normalize(source.relative_to(payload_root).as_posix())
        if relative in seen:
            raise SystemExit(f"STOP: duplicate package path: {relative}")
        seen.add(relative)
        live = repo / relative
        if live.exists() and not live.is_file():
            raise SystemExit(f"STOP: live target is not a regular file: {relative}")
        after_hash = sha256_file(source)
        if live.is_file():
            before_hash = sha256_file(live)
            if before_hash == after_hash:
                continue
            operation = "replace"
        else:
            before_hash = None
            operation = "add"
        entries.append(
            {
                "path": relative,
                "operation": operation,
                "before_sha256": before_hash,
                "sha256": after_hash,
                "size_bytes": source.stat().st_size,
            }
        )
        payload_files.append((source, relative))

    for raw in args.delete_path:
        relative = normalize(raw)
        if relative in seen:
            raise SystemExit(f"STOP: path cannot be payload and delete target: {relative}")
        live = repo / relative
        if not live.is_file():
            raise SystemExit(f"STOP: delete target does not exist: {relative}")
        seen.add(relative)
        entries.append(
            {
                "path": relative,
                "operation": "delete",
                "before_sha256": sha256_file(live),
                "sha256": None,
                "size_bytes": None,
            }
        )

    if not entries:
        raise SystemExit("STOP: package contains no changed or deleted files.")

    manifest = {
        "format": "nexuss-development-package-v1",
        "package_id": args.package_id,
        "phase": args.phase,
        "title": args.title,
        "description": args.description,
        "created_at": datetime.now(UTC).isoformat(),
        "requires_restart": not args.no_restart,
        "trust_boundary_change": bool(args.trust_boundary_change),
        "database_schema_changed": False,
        "base_git_head": git_head(repo),
        "files": sorted(entries, key=lambda item: str(item["path"])),
        "focused_tests": list(dict.fromkeys(args.focused_test)),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "NEXUSS-DEVELOPMENT-MANIFEST.json",
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        )
        for source, relative in sorted(payload_files, key=lambda item: item[1]):
            archive.write(source, f"payload/{relative}")

    print("PASS: Nexuss development package created.")
    print(f"Package: {args.output}")
    print(f"SHA-256: {sha256_file(args.output)}")
    print(f"Changed/deleted files: {len(entries)}")
    print(f"Focused tests: {len(manifest['focused_tests'])}")
    print("Repository modified: false")
    print("LLM/API used: false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
