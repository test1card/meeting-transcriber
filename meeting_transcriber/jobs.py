from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .events import read_json, utc_now, write_json_atomic


MAX_RECORDING_SECONDS = 5 * 60 * 60
SUPPORTED_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}
MODES = {"local", "deepseek"}
DOCUMENTS = (
    {
        "key": "minutes",
        "filename": "01_Протокол_совещания.docx",
        "title": "Протокол совещания",
        "description": "Решения, задачи, сроки и ключевые вопросы",
    },
    {
        "key": "full",
        "filename": "02_Полная_стенограмма.docx",
        "title": "Полная стенограмма",
        "description": "Максимально полный текст с говорящими и временем",
    },
    {
        "key": "edited",
        "filename": "03_Редакционная_стенограмма.docx",
        "title": "Редакционная стенограмма",
        "description": "Читаемая версия без речевого мусора",
    },
    {
        "key": "condensed",
        "filename": "04_Сокращенная_смысловая_стенограмма.docx",
        "title": "Сокращённая смысловая стенограмма",
        "description": "Только существенное, в хронологическом порядке",
    },
)

STAGES = (
    ("VALIDATING", "Проверка записи", 0.02),
    ("TRANSCRIBING_WHISPERX", "Распознавание WhisperX", 0.10),
    ("TRANSCRIBING_MOSS", "Распознавание и говорящие MOSS", 0.35),
    ("CLUSTERING_SPEAKERS", "Объединение голосов", 0.08),
    ("TRANSCRIBING_QWEN", "Независимое распознавание Qwen", 0.18),
    ("ADJUDICATING", "Сверка вариантов текста", 0.12),
    ("CREATING_MINUTES", "Подготовка протокола", 0.05),
    ("CLEANING_TRANSCRIPT", "Редакционная обработка", 0.05),
    ("CONDENSING_TRANSCRIPT", "Смысловое сокращение", 0.03),
    ("BUILDING_DOCX", "Создание документов Word", 0.02),
)


class JobValidationError(ValueError):
    pass


def safe_recording_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned[:80].rstrip(" .")
    return cleaned or "meeting"


def validate_new_job(
    *,
    input_path: Path,
    output_root: Path,
    mode: str,
    model: str,
    speaker_count: int | None,
    cloud_consent: bool,
) -> None:
    if not input_path.is_file():
        raise JobValidationError("Файл записи не найден.")
    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise JobValidationError(
            f"Формат {input_path.suffix or '(без расширения)'} пока не поддерживается."
        )
    if mode not in MODES:
        raise JobValidationError("Неизвестный режим обработки.")
    if not model.strip():
        raise JobValidationError("Не выбрана текстовая модель.")
    if mode == "deepseek" and not cloud_consent:
        raise JobValidationError(
            "Для режима DeepSeek нужно подтвердить передачу текста стенограммы."
        )
    if speaker_count is not None and not 1 <= speaker_count <= 20:
        raise JobValidationError("Количество говорящих должно быть от 1 до 20.")
    output_root.mkdir(parents=True, exist_ok=True)
    if not output_root.is_dir():
        raise JobValidationError("Не удалось открыть папку результатов.")


def create_job(
    *,
    input_path: str,
    output_root: str,
    mode: str,
    model: str,
    speaker_count: int | None = None,
    cloud_consent: bool = False,
) -> Path:
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_root).expanduser().resolve()
    validate_new_job(
        input_path=source,
        output_root=destination,
        mode=mode,
        model=model,
        speaker_count=speaker_count,
        cloud_consent=cloud_consent,
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = safe_recording_name(source.stem)
    job_dir = destination / f"{slug}-{stamp}"
    suffix = 2
    while job_dir.exists():
        job_dir = destination / f"{slug}-{stamp}-{suffix}"
        suffix += 1
    for relative in (
        "checkpoints",
        "documents",
        "_audit/transcripts",
        "_audit/prompts",
        "_audit/metrics",
        "logs",
        "stages",
    ):
        (job_dir / relative).mkdir(parents=True, exist_ok=True)

    created_at = utc_now()
    job = {
        "schema_version": 1,
        "job_id": str(uuid.uuid4()),
        "created_at": created_at,
        "input": {
            "path": str(source),
            "filename": source.name,
            "size_bytes": source.stat().st_size,
        },
        "output_root": str(destination),
        "job_dir": str(job_dir),
        "language": "ru",
        "max_recording_seconds": MAX_RECORDING_SECONDS,
        "speaker_count": speaker_count,
        "max_speakers": max(8, speaker_count or 0),
        "text_processing": {
            "mode": mode,
            "provider": "deepseek" if mode == "deepseek" else "ollama",
            "model": model,
            "base_url": (
                "https://api.deepseek.com"
                if mode == "deepseek"
                else "http://127.0.0.1:11434"
            ),
            "cloud_consent": bool(cloud_consent),
        },
        "documents": list(DOCUMENTS),
    }
    write_json_atomic(job_dir / "job.json", job)
    write_json_atomic(
        job_dir / "status.json",
        {
            "schema_version": 1,
            "job_id": job["job_id"],
            "input_filename": source.name,
            "state": "QUEUED",
            "stage": None,
            "stage_label": "Ожидает запуска",
            "overall_progress": 0.0,
            "stage_progress": None,
            "message": "Задание создано",
            "created_at": created_at,
            "updated_at": created_at,
            "started_at": None,
            "finished_at": None,
            "elapsed_seconds": 0,
            "eta_seconds": None,
            "provider": job["text_processing"]["provider"],
            "model": model,
            "cloud_used": mode == "deepseek",
            "documents": [],
            "error": None,
        },
    )
    return job_dir


def load_job(job_dir: Path) -> dict[str, Any]:
    payload = read_json(job_dir / "job.json")
    if not isinstance(payload, dict):
        raise JobValidationError("Повреждён или отсутствует job.json.")
    return payload
