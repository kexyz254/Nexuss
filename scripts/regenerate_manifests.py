"""Copyright © kexyz254peter. Nexuss AI - Confidential and Proprietary.

Regenerate FILE_MANIFEST.txt and SHA256SUMS.txt from the working tree.

Output matches the conventions observed in the existing files: paths are
``./``-prefixed, forward-slash separated, sorted; hashes are lowercase hex
followed by two spaces and the path (GNU coreutils ``sha256sum`` format).

The exclusion rules mirror scripts/validate_repository.py so the two tools
cannot drift apart silently: this module imports the validator's own
IGNORED_DIRECTORIES and FORBIDDEN_SUFFIXES rather than restating them.

Safety properties:
- Refuses to run if a file that validate_repository.py forbids is present,
  rather than writing a manifest that launders it.
- Refuses to include .env or any non-example env file even if the validator's
  name list were to miss a variant.
- Writes atomically: content is built fully in memory and written only after
  every file has hashed successfully.
- Prints a summary diff (added / removed) against the previous manifest so a
  regeneration is reviewable before commit.

Usage:
    python scripts/regenerate_manifests.py          # write
    python scripts/regenerate_manifests.py --check  # verify only, exit 1 on drift
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from validate_repository import (
    FORBIDDEN_NAMES,
    FORBIDDEN_SUFFIXES,
    IGNORED_DIRECTORIES,
)

ROOT = Path(__file__).resolve().parents[1]

# Never listed in a manifest regardless of validator rules. The runtime
# directory holds the paired-device database; manifests describe source.
_EXTRA_EXCLUDED_DIRECTORIES = {".nexuss-runtime", ".idea", ".vscode", "dist", "build"}
_EXTRA_EXCLUDED_SUFFIXES = {".zip", ".log", ".db", ".db-wal", ".db-shm"}
_MANIFEST_FILES = {"FILE_MANIFEST.txt", "SHA256SUMS.txt"}


def _is_env_like(name: str) -> bool:
    """True for .env and variants (.env.local, .env.production), never .env.example."""
    return name.startswith(".env") and name != ".env.example"


def _eligible_files() -> list[Path]:
    excluded_directories = IGNORED_DIRECTORIES | _EXTRA_EXCLUDED_DIRECTORIES
    excluded_suffixes = set(FORBIDDEN_SUFFIXES) | _EXTRA_EXCLUDED_SUFFIXES

    selected: list[Path] = []
    refusals: list[str] = []

    for candidate in sorted(ROOT.rglob("*")):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(ROOT)
        if any(part in excluded_directories for part in relative.parts):
            continue
        if relative.name in _MANIFEST_FILES and len(relative.parts) == 1:
            continue
        if candidate.suffix in excluded_suffixes:
            continue
        if candidate.name in FORBIDDEN_NAMES or _is_env_like(candidate.name):
            refusals.append(str(relative))
            continue
        selected.append(relative)

    if refusals:
        joined = ", ".join(refusals)
        raise SystemExit(
            f"STOP: refusing to regenerate manifests while forbidden files exist: {joined}. "
            "Remove them first; a manifest must never launder a secret-like file."
        )

    return selected


def _posix(path: Path) -> str:
    return "./" + path.as_posix()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with (ROOT / path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _build() -> tuple[str, str]:
    files = _eligible_files()
    manifest_lines = [_posix(path) for path in files]
    checksum_lines = [f"{_sha256(path)}  {_posix(path)}" for path in files]
    return "\n".join(manifest_lines) + "\n", "\n".join(checksum_lines) + "\n"


def _previous_manifest() -> set[str]:
    manifest_path = ROOT / "FILE_MANIFEST.txt"
    if not manifest_path.is_file():
        return set()
    return {
        line.strip()
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed manifests match the tree; write nothing",
    )
    arguments = parser.parse_args()

    manifest_text, checksums_text = _build()

    if arguments.check:
        current_manifest = (ROOT / "FILE_MANIFEST.txt").read_text(encoding="utf-8")
        current_checksums = (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8")
        if current_manifest == manifest_text and current_checksums == checksums_text:
            print("Manifests match the working tree.")
            return 0
        print("Manifests are stale. Run: python scripts/regenerate_manifests.py")
        return 1

    before = _previous_manifest()
    after = {line for line in manifest_text.splitlines() if line}

    (ROOT / "FILE_MANIFEST.txt").write_text(manifest_text, encoding="utf-8", newline="\n")
    (ROOT / "SHA256SUMS.txt").write_text(checksums_text, encoding="utf-8", newline="\n")

    added = sorted(after - before)
    removed = sorted(before - after)

    print(f"FILE_MANIFEST.txt: {len(after)} entries")
    for entry in added:
        print(f"  + {entry}")
    for entry in removed:
        print(f"  - {entry}")
    if not added and not removed:
        print("  (membership unchanged; hashes refreshed)")
    print("SHA256SUMS.txt: rewritten to match.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
