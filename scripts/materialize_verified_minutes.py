from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from meeting_transcriber.documents import build_minutes
from meeting_transcriber.formatting import transcript_lines, write_json
from meeting_transcriber.protocol_final import (
    render_protocol_markdown,
    sanitize_final_protocol,
)
def parse_json_response(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("The archived final response must contain a JSON object")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("extraction", type=Path)
    parser.add_argument("final_prompt", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="deepseek-v4-flash")
    args = parser.parse_args()

    transcript_payload = json.loads(args.transcript.read_text(encoding="utf-8"))
    transcript = transcript_payload.get("transcript", transcript_payload)
    lines = transcript_lines(transcript["segments"])
    extraction = json.loads(args.extraction.read_text(encoding="utf-8"))
    archived = json.loads(args.final_prompt.read_text(encoding="utf-8"))
    protocol = sanitize_final_protocol(
        parse_json_response(archived["response"]),
        lines,
        require_resolution_basis=True,
        fallback_actions=extraction.get("actions", []),
    )
    markdown = render_protocol_markdown(protocol)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "protocol.json", protocol)
    (output / "minutes.md").write_text(markdown, encoding="utf-8")
    slug = re.sub(r"[^0-9A-Za-zА-Яа-я._-]+", "-", args.model).strip("-").lower()
    minutes_dir = output / "stages" / "minutes"
    minutes_dir.mkdir(parents=True, exist_ok=True)
    (minutes_dir / f"minutes-{slug}.md").write_text(markdown, encoding="utf-8")
    job = {
        "input": {"filename": args.transcript.parent.parent.parent.name + ".mp4"},
        "text_processing": {
            "mode": "deepseek",
            "provider": "deepseek",
            "model": args.model,
        },
    }
    write_json(output / "job.json", job)
    document = build_minutes(output, job)
    print(json.dumps({"minutes": str(document), "protocol": protocol}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())