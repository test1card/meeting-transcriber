from __future__ import annotations

import argparse
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
from meeting_transcriber.formatting import safe_slug, transcript_lines, write_json
import meeting_transcriber.summarization as summarization


BASE_CLIENT = summarization.LocalChatClient


class AuditClient(BASE_CLIENT):
    audit_dir: Path

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.request_index = 0
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
    ) -> str:
        started = time.perf_counter()
        response = super().chat(messages, schema=schema)
        self.request_index += 1
        write_json(
            self.audit_dir / f"{self.request_index:03d}.json",
            {
                "provider": self.provider,
                "model": self.model,
                "messages": messages,
                "schema": schema,
                "response": response,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            },
        )
        return response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--provider", choices=["ollama", "deepseek"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--chunk-chars", type=int, default=16_000)
    return parser


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args()
    payload = json.loads(args.transcript.read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    lines = transcript_lines(transcript["segments"])
    run_dir = args.output.resolve() / safe_slug(args.model)
    run_dir.mkdir(parents=True, exist_ok=True)

    AuditClient.audit_dir = run_dir / "_audit" / "prompts"
    summarization.LocalChatClient = AuditClient
    if args.provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
        base_url = args.base_url or "https://api.deepseek.com"
    else:
        api_key = None
        base_url = args.base_url or "http://127.0.0.1:11434"

    result = summarization.summarize_with_model(
        lines,
        provider=args.provider,
        base_url=base_url,
        model=args.model,
        api_key=api_key,
        summary_language="Russian",
        chunk_chars=args.chunk_chars,
    )
    (run_dir / "minutes.md").write_text(result.summary_markdown, encoding="utf-8")
    write_json(run_dir / "extraction.json", result.extraction)
    write_json(run_dir / "metrics.json", result.metrics)
    print(json.dumps(result.metrics, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
