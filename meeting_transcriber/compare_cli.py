from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .cli import PROJECT_ROOT, _write_comparison
from .formatting import safe_slug, transcript_lines, write_json
from .summarization import ModelResult, summarize_with_model


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare local Ollama and DeepSeek summaries of one transcript."
    )
    parser.add_argument("transcript_json", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--local-provider",
        choices=["ollama", "openai", "vllm"],
        default="ollama",
    )
    parser.add_argument("--local-base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--local-models", default="gemma4:e4b,gemma4:26b")
    parser.add_argument(
        "--deepseek-models",
        default="deepseek-v4-flash,deepseek-v4-pro",
    )
    parser.add_argument("--no-deepseek", action="store_true")
    parser.add_argument(
        "--summary-language",
        default="the same language as the transcript",
    )
    parser.add_argument("--chunk-chars", type=int, default=16_000)
    return parser


def _models(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _run_job(
    lines: list[str],
    output_dir: Path,
    *,
    provider: str,
    base_url: str,
    model: str,
    api_key: str | None,
    summary_language: str,
    chunk_chars: int,
) -> ModelResult:
    print(f"[{provider}] Running {model!r}...")
    result = summarize_with_model(
        lines,
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        summary_language=summary_language,
        chunk_chars=chunk_chars,
    )
    slug = safe_slug(model)
    (output_dir / f"minutes-{slug}.md").write_text(
        result.summary_markdown,
        encoding="utf-8",
    )
    write_json(output_dir / f"extraction-{slug}.json", result.extraction)
    write_json(output_dir / f"metrics-{slug}.json", result.metrics)
    return result


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args(argv)
    transcript_path = args.transcript_json.expanduser().resolve()
    output_dir = (args.output or transcript_path.parent).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        payload = json.loads(transcript_path.read_text(encoding="utf-8"))
        transcript = payload.get("transcript", payload)
        lines = transcript_lines(transcript.get("segments", []))
        if not lines:
            raise ValueError("Transcript contains no text segments")

        results: list[ModelResult] = []
        for model in _models(args.local_models):
            results.append(
                _run_job(
                    lines,
                    output_dir,
                    provider=args.local_provider,
                    base_url=args.local_base_url,
                    model=model,
                    api_key=os.getenv("LLM_API_KEY"),
                    summary_language=args.summary_language,
                    chunk_chars=args.chunk_chars,
                )
            )

        deepseek_models = [] if args.no_deepseek else _models(args.deepseek_models)
        if deepseek_models:
            deepseek_key = os.getenv("DEEPSEEK_API_KEY")
            if not deepseek_key:
                raise ValueError(
                    "DeepSeek comparison requested, but DEEPSEEK_API_KEY is missing"
                )
            for model in deepseek_models:
                results.append(
                    _run_job(
                        lines,
                        output_dir,
                        provider="deepseek",
                        base_url="https://api.deepseek.com",
                        model=model,
                        api_key=deepseek_key,
                        summary_language=args.summary_language,
                        chunk_chars=args.chunk_chars,
                    )
                )

        _write_comparison(output_dir, results)
        print(f"Comparison complete: {output_dir}")
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
