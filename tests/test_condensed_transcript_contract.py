from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "condense_transcript_deepseek.py"
    )
    spec = importlib.util.spec_from_file_location("condense_transcript", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_model_ids_preserve_original_turn_text() -> None:
    module = _load_script()
    batch = [
        {"id": "C00001", "text": "Содержательная реплика."},
        {"id": "C00002", "text": "Нельзя потерять этот факт."},
    ]
    raw = json.dumps(
        {"items": [{"id": "C00001", "text": "Содержательная реплика."}]},
        ensure_ascii=False,
    )

    result = module.validate(raw, batch)

    assert result[1] == {
        "id": "C00002",
        "text": "Нельзя потерять этот факт.",
        "fallback": "model_omitted_id",
    }
