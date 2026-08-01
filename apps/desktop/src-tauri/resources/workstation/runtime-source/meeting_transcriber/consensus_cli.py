from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .cli import PROJECT_ROOT, _write_transcription_outputs
from .consensus import adjudicate_transcripts, load_candidate
from .formatting import write_json


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an audited canonical transcript from multiple STT results."
    )
    parser.add_argument("transcripts", nargs="+", type=Path)
    parser.add_argument(
        "--labels",
        help="Comma-separated labels in the same order as transcript files",
    )
    parser.add_argument(
        "--anchor",
        help="Label whose timestamps and speaker assignments remain authoritative",
    )
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--provider",
        choices=["ollama", "openai", "vllm", "deepseek"],
        default="ollama",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="gemma4:26b")
    parser.add_argument("--language", default="ru")
    parser.add_argument(
        "--glossary",
        type=Path,
        help="UTF-8 text file with one name or technical term per line",
    )
    parser.add_argument("--batch-chars", type=_positive_int, default=12_000)
    return parser


def _read_glossary(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def main(argv: list[str] | None = None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = [path.expanduser().resolve() for path in args.transcripts]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        parser.error(f"transcript does not exist: {missing[0]}")
    if len(paths) < 2:
        parser.error("provide at least two STT transcript JSON files")

    labels = (
        [item.strip() for item in args.labels.split(",")]
        if args.labels
        else [path.stem for path in paths]
    )
    if len(labels) != len(paths) or any(not label for label in labels):
        parser.error("--labels must contain one non-empty label per transcript")
    anchor = args.anchor or labels[0]
    output_dir = (
        args.output
        or PROJECT_ROOT
        / "outputs"
        / f"consensus-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    ).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        candidates = [
            load_candidate(path, label) for path, label in zip(paths, labels)
        ]
        api_key = (
            os.getenv("DEEPSEEK_API_KEY")
            if args.provider == "deepseek"
            else os.getenv("LLM_API_KEY")
        )
        transcript, audit = adjudicate_transcripts(
            candidates,
            anchor_label=anchor,
            provider=args.provider,
            base_url=args.base_url,
            model=args.model,
            api_key=api_key,
            language=args.language,
            glossary=_read_glossary(args.glossary),
            batch_chars=args.batch_chars,
            checkpoint_dir=output_dir / "consensus-checkpoints",
        )
        metadata = {
            "consensus": {
                "anchor": anchor,
                "judge_provider": args.provider,
                "judge_model": args.model,
                **audit["metrics"],
            }
        }
        _write_transcription_outputs(
            output_dir,
            transcript,
            metadata,
            source_name="multi-STT consensus",
        )
        write_json(output_dir / "consensus-audit.json", audit)
        print(f"Canonical transcript: {output_dir / 'transcript.json'}")
        print(f"Audit trail: {output_dir / 'consensus-audit.json'}")
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
