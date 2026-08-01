from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))
if str(PROJECT_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR / "scripts"))

from evaluate_minutes_prompts import score_result


def as_evaluation_result(protocol: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": "ПРОТОКОЛ СОВЕЩАНИЯ",
        "date": "unspecified",
        "time": "unspecified",
        "location": "unspecified",
        "attendees": [],
        "agenda": protocol.get("agenda", []),
        "discussed": protocol.get("discussed", []),
        "resolved": protocol.get("resolutions", []),
        "notes": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--protocol",
        action="append",
        nargs=2,
        metavar=("MODEL", "PATH"),
        required=True,
    )
    args = parser.parse_args()

    transcript_payload = json.loads(args.transcript.read_text(encoding="utf-8"))
    transcript = transcript_payload.get("transcript", transcript_payload)
    duration = max(
        (float(item.get("end") or 0) for item in transcript.get("segments", [])),
        default=0.0,
    )
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    rows = []
    for model, path_text in args.protocol:
        protocol_path = Path(path_text)
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        result = as_evaluation_result(protocol)
        rows.append(
            {
                "model": model,
                "protocol": str(protocol_path.resolve()),
                "discussed_count": len(result["discussed"]),
                "resolved_count": len(result["resolved"]),
                **score_result(result, gold, duration),
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"metrics_version": 1, "runs": rows}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
