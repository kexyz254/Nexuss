"""Bounded, dependency-light extraction for common chat files."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

_MAX_EXTRACTED_CHARS = 120_000
_TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".py", ".js",
    ".ts", ".tsx", ".jsx", ".html", ".css", ".sql", ".sh", ".ps1",
    ".java", ".c", ".cc", ".cpp", ".h", ".hpp", ".rs", ".go", ".xml",
}


def _bound(value: str) -> str:
    normalized = value.replace("\x00", "")
    return normalized[:_MAX_EXTRACTED_CHARS]


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return _bound(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return _bound(data.decode("utf-8", errors="replace"))


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        payload = archive.read("word/document.xml")
    root = ElementTree.fromstring(payload)
    parts = [
        node.text or ""
        for node in root.iter()
        if node.tag.endswith("}t")
    ]
    return _bound("\n".join(part for part in parts if part))


def _xlsx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root:
                shared.append(" ".join(
                    node.text or ""
                    for node in item.iter()
                    if node.tag.endswith("}t")
                ))

        output: list[str] = []
        sheet_names = sorted(
            name for name in names
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )[:12]
        for sheet_name in sheet_names:
            output.append(f"[{Path(sheet_name).stem}]")
            root = ElementTree.fromstring(archive.read(sheet_name))
            row_count = 0
            for row in root.iter():
                if not row.tag.endswith("}row"):
                    continue
                values: list[str] = []
                for cell in row:
                    if not cell.tag.endswith("}c"):
                        continue
                    kind = cell.attrib.get("t")
                    value_node = next(
                        (child for child in cell if child.tag.endswith("}v")),
                        None,
                    )
                    raw = value_node.text if value_node is not None else ""
                    if kind == "s" and raw and raw.isdigit():
                        index = int(raw)
                        raw = shared[index] if index < len(shared) else raw
                    values.append(raw or "")
                if values:
                    output.append("\t".join(values))
                row_count += 1
                if row_count >= 500:
                    break
                if sum(len(item) for item in output) >= _MAX_EXTRACTED_CHARS:
                    break
        return _bound("\n".join(output))


def _pdf_text(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError:
        return None

    reader = PdfReader(io.BytesIO(data))
    pages: list[str] = []
    for page in reader.pages[:80]:
        pages.append(page.extract_text() or "")
        if sum(len(item) for item in pages) >= _MAX_EXTRACTED_CHARS:
            break
    return _bound("\n\n".join(pages))


def extract_text(name: str, media_type: str, data: bytes) -> tuple[str, str]:
    suffix = Path(name).suffix.casefold()
    try:
        if media_type.startswith("text/") or suffix in _TEXT_SUFFIXES:
            return _decode_text(data), "extracted"
        if suffix == ".docx":
            return _docx_text(data), "extracted"
        if suffix == ".xlsx":
            return _xlsx_text(data), "extracted"
        if suffix == ".pdf" or media_type == "application/pdf":
            value = _pdf_text(data)
            return (value, "extracted") if value else ("", "stored_only")
        if suffix in {".json", ".jsonl"}:
            parsed = json.loads(_decode_text(data))
            return _bound(json.dumps(parsed, ensure_ascii=False, indent=2)), "extracted"
        if suffix in {".csv", ".tsv"}:
            dialect = "excel-tab" if suffix == ".tsv" else "excel"
            rows = csv.reader(io.StringIO(_decode_text(data)), dialect=dialect)
            return _bound("\n".join("\t".join(row) for row in rows)), "extracted"
    except (KeyError, OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return "", "failed"
    return "", "stored_only"
