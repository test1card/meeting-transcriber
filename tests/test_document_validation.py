from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from meeting_transcriber.document_validation import valid_docx
from meeting_transcriber.jobs import DOCUMENTS
from meeting_transcriber.pipeline import _document_manifest


def _write_minimal_docx(path: Path, text: str = "Текст документа") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r>'
                f"<w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
        archive.writestr("padding.bin", b"0" * 2_048)


def test_valid_docx_requires_integrity_text_and_expected_location(tmp_path: Path) -> None:
    document_dir = tmp_path / "documents"
    valid = document_dir / "valid.docx"
    _write_minimal_docx(valid)
    assert valid_docx(valid, expected_parent=document_dir)

    empty = document_dir / "empty.docx"
    _write_minimal_docx(empty, text=" ")
    assert not valid_docx(empty, expected_parent=document_dir)

    corrupt = document_dir / "corrupt.docx"
    corrupt.write_bytes(b"not a docx" * 200)
    assert not valid_docx(corrupt, expected_parent=document_dir)
    assert not valid_docx(valid, expected_parent=tmp_path / "other")


def test_manifest_is_complete_ordered_and_rejects_one_corrupt_file(tmp_path: Path) -> None:
    document_dir = tmp_path / "documents"
    manifest = []
    for definition in reversed(DOCUMENTS):
        path = document_dir / definition["filename"]
        _write_minimal_docx(path)
        manifest.append({**definition, "path": str(path), "size_bytes": path.stat().st_size})
    (document_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    validated = _document_manifest(tmp_path)
    assert [item["filename"] for item in validated] == [
        definition["filename"] for definition in DOCUMENTS
    ]

    (document_dir / DOCUMENTS[2]["filename"]).write_bytes(b"broken" * 300)
    assert _document_manifest(tmp_path) == []
