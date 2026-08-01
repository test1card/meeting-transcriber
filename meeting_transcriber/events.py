from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def append_event(job_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    payload = {"timestamp": utc_now(), **event}
    event_path = job_dir / "events.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with event_path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stream.flush()
    return payload


def emit_stdout(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def update_status(
    job_dir: Path,
    changes: dict[str, Any],
    *,
    event_type: str | None = None,
) -> dict[str, Any]:
    path = job_dir / "status.json"
    current = read_json(path, {}) or {}
    current.update(changes)
    current["updated_at"] = utc_now()
    write_json_atomic(path, current)
    if event_type:
        event = append_event(
            job_dir,
            {"type": event_type, "status": current},
        )
        emit_stdout(event)
    return current


def fail_with_message(message: str, code: int = 1) -> int:
    print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
    return code
