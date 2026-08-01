from __future__ import annotations

import json
from pathlib import Path

import pytest

from meeting_transcriber.jobs import (
    DOCUMENTS,
    JobValidationError,
    create_job,
    safe_recording_name,
)


def make_recording(tmp_path: Path, name: str = "запись совещания.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(b"not media; creation does not decode the recording")
    return path


def test_create_local_job_preserves_unicode_and_contract(tmp_path: Path) -> None:
    recording = make_recording(tmp_path)
    output = tmp_path / "результаты"

    job_dir = create_job(
        input_path=str(recording),
        output_root=str(output),
        mode="local",
        model="gemma4:e4b",
    )

    job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    assert job["input"]["path"] == str(recording.resolve())
    assert status["input_filename"] == "запись совещания.mp4"
    assert job["text_processing"]["provider"] == "ollama"
    assert job["text_processing"]["cloud_consent"] is False
    assert status["state"] == "QUEUED"
    assert [item["filename"] for item in job["documents"]] == [
        item["filename"] for item in DOCUMENTS
    ]
    for relative in (
        "checkpoints",
        "documents",
        "_audit/transcripts",
        "_audit/prompts",
        "_audit/metrics",
        "logs",
        "stages",
    ):
        assert (job_dir / relative).is_dir()


def test_deepseek_job_requires_explicit_consent(tmp_path: Path) -> None:
    recording = make_recording(tmp_path)
    with pytest.raises(JobValidationError, match="подтвердить"):
        create_job(
            input_path=str(recording),
            output_root=str(tmp_path / "out"),
            mode="deepseek",
            model="deepseek-v4-flash",
            cloud_consent=False,
        )


def test_deepseek_job_records_consent_without_a_secret(tmp_path: Path) -> None:
    recording = make_recording(tmp_path)
    job_dir = create_job(
        input_path=str(recording),
        output_root=str(tmp_path / "out"),
        mode="deepseek",
        model="deepseek-v4-flash",
        cloud_consent=True,
    )
    text = (job_dir / "job.json").read_text(encoding="utf-8")
    assert '"cloud_consent": true' in text
    assert "DEEPSEEK_API_KEY" not in text


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    recording = make_recording(tmp_path, "notes.txt")
    with pytest.raises(JobValidationError, match="не поддерживается"):
        create_job(
            input_path=str(recording),
            output_root=str(tmp_path / "out"),
            mode="local",
            model="gemma4:e4b",
        )


def test_safe_recording_name_keeps_cyrillic_but_removes_windows_characters() -> None:
    assert safe_recording_name('Встреча: "Кубик" / финал') == "Встреча_ _Кубик_ _ финал"
