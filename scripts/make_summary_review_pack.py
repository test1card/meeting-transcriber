from __future__ import annotations

import argparse
import json
import string
from pathlib import Path
from typing import Any


SECTIONS = {
    "decisions": "decision",
    "actions": "task",
    "risks": "risk",
    "open_questions": "question",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a blinded human-review pack for meeting summaries."
    )
    parser.add_argument(
        "--extraction",
        action="append",
        required=True,
        help="Private system label=structured extraction JSON",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-output", type=Path)
    return parser.parse_args()


def parse_specs(values: list[str]) -> list[tuple[str, Path]]:
    parsed: list[tuple[str, Path]] = []
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Expected label=path, got {value!r}")
        label, raw_path = value.split("=", 1)
        parsed.append((label, Path(raw_path).expanduser().resolve()))
    if len(parsed) > len(string.ascii_uppercase):
        raise SystemExit("At most 26 systems are supported.")
    return parsed


def candidate(
    blind_id: str, section: str, index: int, item: dict[str, Any]
) -> dict[str, Any]:
    text_field = SECTIONS[section]
    result = {
        "id": f"{blind_id}-{section[:1].upper()}{index:02d}",
        "text": str(item.get(text_field, "")).strip(),
        "evidence": str(item.get("evidence", "")).strip(),
        "review": {
            "support": "",
            "matched_gold_id": "",
            "evidence_checked": "",
            "notes": "",
        },
    }
    if section in {"decisions", "actions"}:
        result["owner"] = str(item.get("owner", "unspecified")).strip()
        result["review"]["owner_correct"] = None
    if section == "actions":
        result["due"] = str(item.get("due", "unspecified")).strip()
        result["review"]["due_correct"] = None
    return result


def build_pack(specifications: list[tuple[str, Path]]) -> tuple[dict, dict]:
    systems: dict[str, Any] = {}
    key: dict[str, str] = {}
    for blind_id, (label, path) in zip(string.ascii_uppercase, specifications):
        payload = json.loads(path.read_text(encoding="utf-8"))
        key[blind_id] = label
        systems[blind_id] = {
            section: [
                candidate(blind_id, section, index, item)
                for index, item in enumerate(payload.get(section, []), start=1)
            ]
            for section in SECTIONS
        }
    pack = {
        "instructions": [
            "Keep the key file away from the reviewer until scoring is complete.",
            "First read/listen to the meeting and independently fill gold.decisions "
            "and gold.actions. Use stable IDs D01... and A01....",
            "Then review every candidate without guessing its system. Set support "
            "to supported, partial, unsupported, or unclear.",
            "For supported/partial decisions and actions, set matched_gold_id. "
            "Use the same gold ID for paraphrases of the same item.",
            "Check the cited transcript time and record the actual evidence in "
            "evidence_checked. Mark owner_correct/due_correct only when the model "
            "made a concrete owner/deadline claim.",
        ],
        "scoring_policy": {
            "supported_weight": 1.0,
            "partial_weight": 0.5,
            "unsupported_weight": 0.0,
            "unclear_weight": 0.0,
            "precision_denominator": "all reviewed candidate items",
            "recall_denominator": "independently authored gold items",
        },
        "gold": {"decisions": [], "actions": []},
        "systems": systems,
    }
    return pack, {"blind_system_key": key}


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    key_output = (
        args.key_output.expanduser().resolve()
        if args.key_output
        else output.with_name(f"{output.stem}-key.json")
    )
    pack, key = build_pack(parse_specs(args.extraction))
    output.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    key_output.write_text(
        json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Review pack: {output}")
    print(f"Private key: {key_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
