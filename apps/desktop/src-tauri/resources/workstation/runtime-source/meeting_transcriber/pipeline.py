from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from .document_validation import valid_docx
from .events import append_event, read_json, update_status, utc_now
from .jobs import DOCUMENTS, MAX_RECORDING_SECONDS, STAGES, load_job


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"
STAGE_WEIGHTS = {name: weight for name, _, weight in STAGES}
STAGE_LABELS = {name: label for name, label, _ in STAGES}
STAGE_PREFIX: dict[str, float] = {}
_prefix = 0.0
for _name, _, _weight in STAGES:
    STAGE_PREFIX[_name] = _prefix
    _prefix += _weight


class JobCancelled(RuntimeError):
    pass


class StageFailed(RuntimeError):
    pass


class JobAlreadyRunning(RuntimeError):
    pass


def _no_window_creation_flags(*, new_process_group: bool = False) -> int:
    if os.name != "nt":
        return 0
    flags = subprocess.CREATE_NO_WINDOW
    if new_process_group:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    return flags


def _load_project_environment() -> None:
    """Load missing values from .env without ever logging their contents."""
    path = PROJECT_ROOT / ".env"
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ[name] = value


def _windows_python(name: str) -> Path:
    path = PROJECT_ROOT / name / "Scripts" / "python.exe"
    if not path.is_file():
        raise StageFailed(f"Не найдено окружение {name}. Запустите setup.ps1.")
    return path


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        still_active = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code)
            ):
                return False
            return exit_code.value == still_active
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _acquire_gpu_lock(job_dir: Path) -> Path:
    runtime = PROJECT_ROOT / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    lock = runtime / "active-gpu-job.json"
    payload = {
        "pid": os.getpid(),
        "job_dir": str(job_dir),
        "started_at": utc_now(),
    }
    for _ in range(2):
        try:
            descriptor = os.open(
                lock,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.write("\n")
            return lock
        except FileExistsError:
            existing = read_json(lock, {}) or {}
            if _pid_running(int(existing.get("pid") or 0)):
                other = existing.get("job_dir") or "другое задание"
                if str(other) == str(job_dir):
                    raise JobAlreadyRunning(
                        f"Задание уже выполняется (PID {existing.get('pid')})."
                    )
                raise StageFailed(
                    "Видеокарта уже обрабатывает другую запись. "
                    f"Дождитесь её завершения: {other}"
                )
            try:
                lock.unlink()
            except FileNotFoundError:
                pass
    raise StageFailed("Не удалось получить блокировку видеокарты.")


def _release_gpu_lock(lock: Path, job_dir: Path) -> None:
    existing = read_json(lock, {}) or {}
    if (
        int(existing.get("pid") or 0) == os.getpid()
        and existing.get("job_dir") == str(job_dir)
    ):
        lock.unlink(missing_ok=True)


def _powershell_script(script: str, *arguments: str) -> list[str]:
    return [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PROJECT_ROOT / script),
        *map(str, arguments),
    ]


def _cancel_requested(job_dir: Path) -> bool:
    return (job_dir / "cancel.request").exists()


def _terminate_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=_no_window_creation_flags(),
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def _tail(path: Path, limit: int = 3500) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:].strip()


def _progress_from_file(path: Path) -> tuple[float | None, int | None, int | None]:
    value = read_json(path)
    if not isinstance(value, dict):
        return None, None, None
    has_completed = value.get("completed") is not None
    current = int(value.get("completed") if has_completed else value.get("chunk") or 0)
    total = int(value.get("total_chunks") or value.get("total") or 0)
    if total <= 0:
        return None, current or None, total or None
    if value.get("status") == "complete":
        return 1.0, total, total
    if has_completed:
        return min(0.99, current / total), current, total
    generated = int(value.get("generated_tokens") or 0)
    maximum = int(value.get("max_new_tokens") or 0)
    within = min(generated / maximum, 0.95) if maximum > 0 else 0.0
    progress = max(0.0, min(0.99, ((max(1, current) - 1) + within) / total))
    return progress, current, total


def _checkpoint_progress(path: Path, pattern: str, total: int | None) -> tuple[
    float | None, int | None, int | None
]:
    current = len(list(path.glob(pattern))) if path.is_dir() else 0
    if not total:
        return None, current or None, None
    return min(0.99, current / total), current, total


def _estimate_text_batches(transcript_path: Path, max_chars: int = 12_000) -> int | None:
    payload = read_json(transcript_path)
    if not isinstance(payload, dict):
        return None
    transcript = payload.get("transcript", payload)
    segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
    if not segments:
        return None
    total = sum(
        len(json.dumps(item, ensure_ascii=False)) + 2
        for item in segments
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    )
    return max(1, math.ceil(total / max_chars))


def _update_stage_progress(
    job_dir: Path,
    stage: str,
    *,
    fraction: float | None,
    current: int | None = None,
    total: int | None = None,
    message: str | None = None,
) -> None:
    status = read_json(job_dir / "status.json", {}) or {}
    started_epoch = float(status.get("_started_epoch") or time.time())
    elapsed = max(0, time.time() - started_epoch)
    prefix = STAGE_PREFIX[stage]
    overall = prefix
    if fraction is not None:
        overall += STAGE_WEIGHTS[stage] * max(0.0, min(1.0, fraction))
    eta = None
    if overall >= 0.02:
        eta = max(0, int(elapsed * (1.0 - overall) / overall))
    changes: dict[str, Any] = {
        "overall_progress": round(overall, 4),
        "stage_progress": None if fraction is None else round(fraction, 4),
        "elapsed_seconds": int(elapsed),
        "eta_seconds": eta,
        "current_unit": current,
        "total_units": total,
    }
    if message:
        changes["message"] = message
    update_status(job_dir, changes, event_type="progress")


def _set_stage(job_dir: Path, stage: str, message: str) -> None:
    if _cancel_requested(job_dir):
        raise JobCancelled
    update_status(
        job_dir,
        {
            "state": stage,
            "stage": stage,
            "stage_label": STAGE_LABELS[stage],
            "stage_progress": 0.0,
            "overall_progress": round(STAGE_PREFIX[stage], 4),
            "current_unit": None,
            "total_units": None,
            "message": message,
            "error": None,
        },
        event_type="stage_started",
    )


def _complete_stage(job_dir: Path, stage: str, message: str) -> None:
    _update_stage_progress(job_dir, stage, fraction=1.0, message=message)
    append_event(
        job_dir,
        {"type": "stage_completed", "stage": stage, "message": message},
    )


def _run_command(
    job_dir: Path,
    stage: str,
    command: list[str],
    *,
    log_name: str,
    progress_reader: Callable[[], tuple[float | None, int | None, int | None]]
    | None = None,
    environment: dict[str, str] | None = None,
) -> None:
    log_path = job_dir / "logs" / log_name
    log_path.parent.mkdir(parents=True, exist_ok=True)
    creationflags = _no_window_creation_flags(new_process_group=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    if environment:
        env.update(environment)
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n[{utc_now()}] START {' '.join(command)}\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        last_report: tuple[float | None, int | None, int | None] | None = None
        last_emit = 0.0
        while process.poll() is None:
            if _cancel_requested(job_dir):
                update_status(
                    job_dir,
                    {
                        "state": "CANCELLING",
                        "message": "Безопасная остановка текущего этапа…",
                    },
                    event_type="cancelling",
                )
                _terminate_tree(process)
                raise JobCancelled
            now = time.monotonic()
            if progress_reader and now - last_emit >= 2:
                report = progress_reader()
                if report != last_report:
                    _update_stage_progress(
                        job_dir,
                        stage,
                        fraction=report[0],
                        current=report[1],
                        total=report[2],
                    )
                    last_report = report
                last_emit = now
            elif not progress_reader and now - last_emit >= 10:
                _update_stage_progress(job_dir, stage, fraction=None)
                last_emit = now
            time.sleep(0.5)
        log.write(f"[{utc_now()}] EXIT {process.returncode}\n")
    if process.returncode != 0:
        detail = _tail(log_path)
        raise StageFailed(
            f"{STAGE_LABELS[stage]} завершился с кодом {process.returncode}."
            + (f"\n\n{detail}" if detail else "")
        )


def _media_duration(input_path: Path) -> float:
    ffprobe = shutil.which("ffprobe.exe") or shutil.which("ffprobe")
    if not ffprobe:
        raise StageFailed("FFmpeg/ffprobe не найден. Запустите setup.ps1.")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        creationflags=_no_window_creation_flags(),
    )
    if completed.returncode != 0:
        raise StageFailed("Не удалось прочитать длительность или аудиодорожку записи.")
    try:
        return float(completed.stdout.strip())
    except ValueError as error:
        raise StageFailed("FFprobe вернул некорректную длительность записи.") from error


def _transcript_complete(path: Path) -> bool:
    payload = read_json(path)
    if not isinstance(payload, dict):
        return False
    metadata = payload.get("metadata", {})
    return bool(metadata.get("complete", True)) and bool(
        payload.get("transcript", payload).get("segments")
    )


def _document_manifest(job_dir: Path) -> list[dict[str, Any]]:
    value = read_json(job_dir / "documents" / "manifest.json", [])
    if not isinstance(value, list):
        return []
    document_dir = (job_dir / "documents").resolve()
    indexed = {
        str(item.get("filename")): item
        for item in value
        if isinstance(item, dict) and item.get("filename")
    }
    validated: list[dict[str, Any]] = []
    for definition in DOCUMENTS:
        item = indexed.get(definition["filename"])
        if not item:
            return []
        path = Path(str(item.get("path", "")))
        if path.name != definition["filename"] or not valid_docx(
            path, expected_parent=document_dir
        ):
            return []
        validated.append(item)
    return validated


def _run_job_locked(job_dir: Path) -> int:
    job_dir = job_dir.expanduser().resolve()
    _load_project_environment()
    job = load_job(job_dir)
    input_path = Path(job["input"]["path"])
    text = job["text_processing"]
    provider = str(text["provider"])
    base_url = str(text["base_url"])
    model = str(text["model"])
    started = time.time()
    existing_status = read_json(job_dir / "status.json", {}) or {}
    started_at = existing_status.get("started_at") or utc_now()
    (job_dir / "cancel.request").unlink(missing_ok=True)
    update_status(
        job_dir,
        {
            "state": "VALIDATING",
            "started_at": started_at,
            "_started_epoch": started,
            "finished_at": None,
            "error": None,
            "message": "Проверяем запись и окружение",
        },
        event_type="job_started",
    )
    try:
        _set_stage(job_dir, "VALIDATING", "Проверяем файл и длительность")
        duration = _media_duration(input_path)
        if duration <= 0:
            raise StageFailed("Запись не содержит доступной аудиодорожки.")
        if duration > MAX_RECORDING_SECONDS + 1:
            raise StageFailed(
                "Запись длиннее пяти часов. Разделите её на две части перед обработкой."
            )
        if provider == "deepseek" and not os.environ.get("DEEPSEEK_API_KEY"):
            raise StageFailed(
                "Ключ DeepSeek не найден в окружении Windows. API-режим недоступен."
            )
        update_status(
            job_dir,
            {"recording_duration_seconds": round(duration, 3)},
        )
        _complete_stage(job_dir, "VALIDATING", "Запись готова к обработке")

        whisper = job_dir / "stages" / "whisperx"
        if not _transcript_complete(whisper / "transcript.json"):
            _set_stage(job_dir, "TRANSCRIBING_WHISPERX", "WhisperX распознаёт речь")
            _run_command(
                job_dir,
                "TRANSCRIBING_WHISPERX",
                _powershell_script(
                    "run.ps1",
                    str(input_path),
                    "-OutputDirectory",
                    str(whisper),
                    "-Language",
                    "ru",
                    "-NoDiarization",
                    "-NoSummary",
                ),
                log_name="whisperx.log",
            )
        _complete_stage(job_dir, "TRANSCRIBING_WHISPERX", "WhisperX завершён")

        moss = job_dir / "stages" / "moss"
        if not _transcript_complete(moss / "transcript.json"):
            _set_stage(job_dir, "TRANSCRIBING_MOSS", "MOSS обрабатывает запись частями")
            _run_command(
                job_dir,
                "TRANSCRIBING_MOSS",
                _powershell_script(
                    "run-moss-checkpointed.ps1",
                    str(input_path),
                    "-OutputDirectory",
                    str(moss),
                ),
                log_name="moss.log",
                progress_reader=lambda: _progress_from_file(moss / "progress.json"),
            )
        _complete_stage(job_dir, "TRANSCRIBING_MOSS", "MOSS завершён, части сохранены")

        speakers = job_dir / "stages" / "moss-global"
        if not _transcript_complete(speakers / "transcript.json"):
            _set_stage(job_dir, "CLUSTERING_SPEAKERS", "Объединяем голоса на всей записи")
            command = _powershell_script(
                "run-speaker-clustering.ps1",
                "-MossTranscript",
                str(moss / "transcript.json"),
                "-AudioFile",
                str(input_path),
                "-OutputDirectory",
                str(speakers),
                "-MaxSpeakers",
                str(job.get("max_speakers", 8)),
            )
            if job.get("speaker_count"):
                command.extend(["-NumSpeakers", str(job["speaker_count"])])
            _run_command(
                job_dir,
                "CLUSTERING_SPEAKERS",
                command,
                log_name="speakers.log",
            )
        _complete_stage(job_dir, "CLUSTERING_SPEAKERS", "Говорящие объединены")

        qwen = job_dir / "stages" / "qwen"
        qwen_python = PROJECT_ROOT / ".venv-qwen" / "Scripts" / "python.exe"
        qwen_enabled = qwen_python.is_file()
        if qwen_enabled:
            if not _transcript_complete(qwen / "transcript.json"):
                _set_stage(job_dir, "TRANSCRIBING_QWEN", "Qwen делает независимую расшифровку")
                _run_command(
                    job_dir,
                    "TRANSCRIBING_QWEN",
                    _powershell_script(
                        "run-qwen-checkpointed.ps1",
                        str(input_path),
                        "-OutputDirectory",
                        str(qwen),
                    ),
                    log_name="qwen.log",
                    progress_reader=lambda: _progress_from_file(qwen / "progress.json"),
                )
            _complete_stage(job_dir, "TRANSCRIBING_QWEN", "Qwen завершён, части сохранены")
        else:
            _complete_stage(
                job_dir,
                "TRANSCRIBING_QWEN",
                "Qwen пропущен: для профиля 8 ГБ достаточно MOSS и WhisperX",
            )
        if provider == "ollama":
            subprocess.run(
                _powershell_script("scripts/Start-Ollama.ps1"),
                cwd=PROJECT_ROOT,
                timeout=60,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_no_window_creation_flags(),
            )

        python = _windows_python(".venv-win")
        consensus = job_dir / "stages" / "consensus"
        if not _transcript_complete(consensus / "transcript.json"):
            transcript_paths = [
                str(speakers / "transcript.json"),
                str(whisper / "transcript.json"),
            ]
            transcript_labels = ["moss", "whisperx"]
            if qwen_enabled and _transcript_complete(qwen / "transcript.json"):
                transcript_paths.insert(1, str(qwen / "transcript.json"))
                transcript_labels.insert(1, "qwen")
            _set_stage(
                job_dir,
                "ADJUDICATING",
                "Модель сверяет варианты расшифровки и временные метки",
            )
            command = [
                str(python),
                "-m",
                "meeting_transcriber.consensus_cli",
                *transcript_paths,
                "--labels",
                ",".join(transcript_labels),
                "--anchor",
                "moss",
                "--output",
                str(consensus),
                "--provider",
                provider,
                "--base-url",
                base_url,
                "--model",
                model,
                "--language",
                "ru",
            ]
            _run_command(
                job_dir,
                "ADJUDICATING",
                command,
                log_name="consensus.log",
                progress_reader=lambda: _progress_from_file(
                    consensus / "consensus-checkpoints" / "progress.json"
                ),
            )
        _complete_stage(job_dir, "ADJUDICATING", "Сверка вариантов завершена")

        minutes = job_dir / "stages" / "minutes"
        minutes.mkdir(parents=True, exist_ok=True)
        if not list(minutes.glob("minutes-*.md")):
            _set_stage(job_dir, "CREATING_MINUTES", "Модель составляет протокол")
            command = [
                str(python),
                "-m",
                "meeting_transcriber.compare_cli",
                str(consensus / "transcript.json"),
                "--output",
                str(minutes),
                "--summary-language",
                "Russian",
            ]
            if provider == "deepseek":
                command.extend(["--local-models", "", "--deepseek-models", model])
            else:
                command.extend(
                    [
                        "--local-provider",
                        "ollama",
                        "--local-base-url",
                        base_url,
                        "--local-models",
                        model,
                        "--no-deepseek",
                    ]
                )
            _run_command(
                job_dir,
                "CREATING_MINUTES",
                command,
                log_name="minutes.log",
            )
        _complete_stage(job_dir, "CREATING_MINUTES", "Протокол подготовлен")

        cleaned = job_dir / "stages" / "cleaned"
        if not (cleaned / "transcript-cleaned.json").is_file():
            _set_stage(job_dir, "CLEANING_TRANSCRIPT", "Убираем речевой мусор и повторы")
            _run_command(
                job_dir,
                "CLEANING_TRANSCRIPT",
                [
                    str(python),
                    str(PROJECT_ROOT / "scripts" / "clean_transcript_deepseek.py"),
                    str(consensus / "transcript.json"),
                    "--output",
                    str(cleaned),
                    "--provider",
                    provider,
                    "--base-url",
                    base_url,
                    "--model",
                    model,
                ],
                log_name="cleanup.log",
                progress_reader=lambda: _progress_from_file(
                    cleaned / "progress.json"
                ),
            )
        _complete_stage(job_dir, "CLEANING_TRANSCRIPT", "Редакционная версия готова")

        condensed = job_dir / "stages" / "condensed"
        if not (condensed / "transcript-condensed.json").is_file():
            _set_stage(job_dir, "CONDENSING_TRANSCRIPT", "Оставляем только существенное")
            _run_command(
                job_dir,
                "CONDENSING_TRANSCRIPT",
                [
                    str(python),
                    str(PROJECT_ROOT / "scripts" / "condense_transcript_deepseek.py"),
                    str(consensus / "transcript.json"),
                    "--output",
                    str(condensed),
                    "--provider",
                    provider,
                    "--base-url",
                    base_url,
                    "--model",
                    model,
                ],
                log_name="condensation.log",
                progress_reader=lambda: _progress_from_file(
                    condensed / "progress.json"
                ),
            )
        _complete_stage(job_dir, "CONDENSING_TRANSCRIPT", "Сокращённая версия готова")

        documents = _document_manifest(job_dir)
        if len(documents) != len(DOCUMENTS):
            _set_stage(job_dir, "BUILDING_DOCX", "Собираем четыре документа Word")
            _run_command(
                job_dir,
                "BUILDING_DOCX",
                [
                    str(_windows_python(".venv-docs")),
                    "-m",
                    "meeting_transcriber.documents",
                    "--job-dir",
                    str(job_dir),
                ],
                log_name="documents.log",
            )
            documents = _document_manifest(job_dir)
        if len(documents) != len(DOCUMENTS):
            raise StageFailed("Не удалось создать все четыре документа Word.")
        _complete_stage(job_dir, "BUILDING_DOCX", "Документы Word готовы")

        elapsed = int(time.time() - started)
        update_status(
            job_dir,
            {
                "state": "COMPLETE",
                "stage": None,
                "stage_label": "Готово",
                "message": "Созданы четыре документа",
                "overall_progress": 1.0,
                "stage_progress": 1.0,
                "elapsed_seconds": elapsed,
                "eta_seconds": 0,
                "finished_at": utc_now(),
                "documents": documents,
                "_started_epoch": None,
            },
            event_type="job_completed",
        )
        return 0
    except JobCancelled:
        update_status(
            job_dir,
            {
                "state": "CANCELLED",
                "stage_label": "Остановлено",
                "message": "Обработка остановлена. Готовые части сохранены.",
                "finished_at": utc_now(),
                "eta_seconds": None,
                "_started_epoch": None,
            },
            event_type="job_cancelled",
        )
        return 130
    except Exception as error:
        detail = str(error)
        trace = traceback.format_exc()
        (job_dir / "logs" / "pipeline-error.log").write_text(
            trace, encoding="utf-8"
        )
        update_status(
            job_dir,
            {
                "state": "FAILED",
                "stage_label": "Нужно внимание",
                "message": detail.splitlines()[0],
                "error": {
                    "message": detail.splitlines()[0],
                    "detail": detail,
                    "log_path": str(job_dir / "logs" / "pipeline-error.log"),
                },
                "finished_at": utc_now(),
                "eta_seconds": None,
                "_started_epoch": None,
            },
            event_type="job_failed",
        )
        return 1


def run_job(job_dir: Path) -> int:
    job_dir = job_dir.expanduser().resolve()
    try:
        lock = _acquire_gpu_lock(job_dir)
    except JobAlreadyRunning:
        return 0
    except StageFailed as error:
        update_status(
            job_dir,
            {
                "state": "FAILED",
                "stage_label": "Занято",
                "message": str(error),
                "error": {"message": str(error), "detail": str(error)},
                "finished_at": utc_now(),
                "eta_seconds": None,
            },
            event_type="job_failed",
        )
        return 1
    try:
        return _run_job_locked(job_dir)
    finally:
        _release_gpu_lock(lock, job_dir)
