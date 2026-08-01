from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from meeting_transcriber.cli import PROJECT_ROOT
from meeting_transcriber.formatting import transcript_lines, write_json
from meeting_transcriber.protocol_final import (
    FINAL_PROTOCOL_SCHEMA,
    render_protocol_markdown,
    sanitize_final_protocol,
    synthesis_source,
)
from meeting_transcriber.protocol_model_prompts import protocol_model_suffix
from meeting_transcriber.protocol_guardrails import sanitize_protocol_extraction
from meeting_transcriber.summarization import (
    LocalChatClient,
    PROTOCOL_SYNTHESIS_SYSTEM,
    combine_extractions,
    parse_json_response,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("extraction", type=Path, nargs="+")
    parser.add_argument("--provider", choices=["ollama", "deepseek"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--base-url")
    return parser


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args()
    payload = json.loads(args.transcript.read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    lines = transcript_lines(transcript["segments"])
    extractions = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in args.extraction
    ]
    for item in extractions:
        item.pop("_final_protocol", None)
    extraction = sanitize_protocol_extraction(
        combine_extractions(extractions),
        lines,
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    if args.provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
        base_url = args.base_url or "https://api.deepseek.com"
    else:
        api_key = None
        base_url = args.base_url or "http://127.0.0.1:11434"

    client = LocalChatClient(
        provider=args.provider,
        base_url=base_url,
        model=args.model,
        api_key=api_key,
    )
    system = (
        PROTOCOL_SYNTHESIS_SYSTEM
        + protocol_model_suffix(
            provider=args.provider,
            model=args.model,
            stage="synthesis",
        )
        + " Write in Russian."
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(
                synthesis_source(extraction, lines),
                ensure_ascii=False,
            ),
        },
    ]
    rows: list[dict[str, Any]] = []
    markdown_values: list[str] = []
    try:
        for index in range(1, args.repeats + 1):
            started = time.perf_counter()
            raw = client.chat(messages, schema=FINAL_PROTOCOL_SCHEMA)
            elapsed = time.perf_counter() - started
            protocol = sanitize_final_protocol(
                parse_json_response(raw),
                lines,
                require_resolution_basis=True,
                fallback_actions=extraction.get("actions", []),
            )
            markdown = render_protocol_markdown(protocol)
            markdown_values.append(markdown)
            candidate = output / f"candidate-{index:02d}"
            candidate.mkdir(parents=True, exist_ok=True)
            write_json(candidate / "protocol.json", protocol)
            (candidate / "minutes.md").write_text(markdown, encoding="utf-8")
            write_json(
                candidate / "prompt.json",
                {
                    "provider": args.provider,
                    "model": args.model,
                    "messages": messages,
                    "schema": FINAL_PROTOCOL_SCHEMA,
                    "response": raw,
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
            rows.append(
                {
                    "candidate": index,
                    "elapsed_seconds": round(elapsed, 3),
                    "agenda": len(protocol["agenda"]),
                    "discussed": len(protocol["discussed"]),
                    "resolutions": len(protocol["resolutions"]),
                }
            )
    finally:
        client.close()

    similarities = []
    for left in range(len(markdown_values)):
        for right in range(left + 1, len(markdown_values)):
            similarities.append(
                {
                    "left": left + 1,
                    "right": right + 1,
                    "sequence_similarity": round(
                        difflib.SequenceMatcher(
                            None,
                            markdown_values[left],
                            markdown_values[right],
                        ).ratio(),
                        5,
                    ),
                }
            )
    write_json(
        output / "stability.json",
        {"candidates": rows, "pairwise": similarities},
    )
    print(json.dumps({"candidates": rows, "pairwise": similarities}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())