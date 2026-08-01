from __future__ import annotations

import json
import os

import pytest

import meeting_transcriber.pipeline as pipeline
from meeting_transcriber.pipeline import (
    JobAlreadyRunning,
    StageFailed,
    _acquire_gpu_lock,
    _pid_running,
    _progress_from_file,
    _release_gpu_lock,
)


def test_chunk_progress_uses_real_completed_work(tmp_path) -> None:
    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps(
            {
                "status": "running",
                "chunk": 3,
                "total_chunks": 10,
                "generated_tokens": 500,
                "max_new_tokens": 1000,
            }
        ),
        encoding="utf-8",
    )
    fraction, current, total = _progress_from_file(progress)
    assert fraction == 0.25
    assert current == 3
    assert total == 10


def test_complete_chunk_progress_is_one(tmp_path) -> None:
    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps({"status": "complete", "chunk": 10, "total_chunks": 10}),
        encoding="utf-8",
    )
    assert _progress_from_file(progress) == (1.0, 10, 10)


def test_consensus_progress_uses_reported_total_not_text_estimate(tmp_path) -> None:
    progress = tmp_path / "progress.json"
    progress.write_text(
        json.dumps({"status": "running", "completed": 10, "total_chunks": 18}),
        encoding="utf-8",
    )
    assert _progress_from_file(progress) == (10 / 18, 10, 18)

def test_missing_progress_is_indeterminate(tmp_path) -> None:
    assert _progress_from_file(tmp_path / "missing.json") == (None, None, None)


def test_windows_safe_pid_probe_detects_current_process() -> None:
    assert _pid_running(os.getpid())
    assert not _pid_running(2_000_000_000)


def test_only_one_gpu_job_lock_can_be_active(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "PROJECT_ROOT", tmp_path)
    first = tmp_path / "job-one"
    second = tmp_path / "job-two"
    lock = _acquire_gpu_lock(first)
    try:
        with pytest.raises(StageFailed, match="уже обрабатывает"):
            _acquire_gpu_lock(second)
    finally:
        _release_gpu_lock(lock, first)
    assert not lock.exists()


def test_restarting_same_job_is_a_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline, "PROJECT_ROOT", tmp_path)
    job = tmp_path / "same-job"
    lock = _acquire_gpu_lock(job)
    try:
        with pytest.raises(JobAlreadyRunning, match="уже выполняется"):
            _acquire_gpu_lock(job)
    finally:
        _release_gpu_lock(lock, job)


@pytest.mark.skipif(os.name != "nt", reason="Windows process flags")
def test_pipeline_children_never_create_console_windows() -> None:
    flags = pipeline._no_window_creation_flags(new_process_group=True)
    assert flags & pipeline.subprocess.CREATE_NO_WINDOW
    assert flags & pipeline.subprocess.CREATE_NEW_PROCESS_GROUP