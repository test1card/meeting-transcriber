from __future__ import annotations

import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile


def valid_docx(path: Path, *, expected_parent: Path | None = None) -> bool:
    """Validate that a clerk-facing DOCX is local, intact, and contains visible text."""
    try:
        resolved = path.resolve(strict=True)
        if expected_parent is not None and resolved.parent != expected_parent.resolve():
            return False
        if resolved.suffix.lower() != ".docx" or resolved.stat().st_size < 1_024:
            return False
        with ZipFile(resolved) as archive:
            if archive.testzip() is not None:
                return False
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                return False
            document_xml = archive.read("word/document.xml")
        return bool(re.search(rb"<w:t(?:\s[^>]*)?>\s*[^<\s]", document_xml))
    except (OSError, BadZipFile, KeyError):
        return False
