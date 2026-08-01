from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-'][0-9A-Za-zА-Яа-яЁё]+)*")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure STT outputs and optionally score them against references."
    )
    parser.add_argument(
        "transcripts",
        nargs="+",
        help="Inputs as label=path/to/transcript.json",
    )
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument(
        "--api-cost",
        action="append",
        default=[],
        help="Measured cost as label=USD; repeat for multiple external methods",
    )
    parser.add_argument("--window-seconds", type=float, default=30.0)
    return parser.parse_args()


def load_transcript(spec: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if "=" not in spec:
        raise ValueError(f"Expected label=path, got {spec!r}")
    label, raw_path = spec.split("=", 1)
    payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    return label, transcript, dict(payload.get("metadata", {}))


def normalized_words(text: str) -> list[str]:
    return [match.group(0).casefold() for match in WORD_RE.finditer(text)]


def normalized_chars(text: str) -> list[str]:
    return list("".join(normalized_words(text)))


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, actual in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected != actual),
                )
            )
        previous = current
    return previous[-1]


def text_in_window(segments: list[dict[str, Any]], start: float, end: float) -> str:
    return " ".join(
        str(segment.get("text", "")).strip()
        for segment in segments
        if float(segment.get("start", 0)) < end
        and float(segment.get("end", segment.get("start", 0))) > start
    ).strip()


def base_metrics(
    transcript: dict[str, Any],
    metadata: dict[str, Any],
    duration: float,
) -> dict[str, Any]:
    segments = transcript.get("segments", [])
    all_text = " ".join(str(segment.get("text", "")) for segment in segments)
    end = max(
        (float(segment.get("end", segment.get("start", 0))) for segment in segments),
        default=0.0,
    )
    nested_consensus = metadata.get("consensus", {})
    elapsed = metadata.get("elapsed_seconds")
    if elapsed is None and isinstance(nested_consensus, dict):
        elapsed = nested_consensus.get("elapsed_seconds")
    return {
        "segments": len(segments),
        "words": len(normalized_words(all_text)),
        "characters": len(all_text),
        "speakers": len(
            {
                str(segment.get("speaker"))
                for segment in segments
                if segment.get("speaker")
            }
        ),
        "last_timestamp": round(end, 3),
        "timeline_coverage": round(min(1.0, end / duration), 5),
        "runtime_seconds": elapsed,
        "real_time_factor": (
            round(float(elapsed) / duration, 5) if elapsed is not None else None
        ),
        "cost_usd": 0.0,
    }


def reference_metrics(
    segments: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> dict[str, Any]:
    word_errors = word_total = char_errors = char_total = 0
    clips: list[dict[str, Any]] = []
    for reference in references:
        start, end = float(reference["start"]), float(reference["end"])
        expected = str(reference["text"])
        actual = text_in_window(segments, start, end)
        expected_words, actual_words = normalized_words(expected), normalized_words(actual)
        expected_chars, actual_chars = normalized_chars(expected), normalized_chars(actual)
        clip_word_errors = edit_distance(expected_words, actual_words)
        clip_char_errors = edit_distance(expected_chars, actual_chars)
        word_errors += clip_word_errors
        word_total += len(expected_words)
        char_errors += clip_char_errors
        char_total += len(expected_chars)
        clips.append(
            {
                "id": reference.get("id"),
                "start": start,
                "end": end,
                "word_errors": clip_word_errors,
                "reference_words": len(expected_words),
                "character_errors": clip_char_errors,
                "reference_characters": len(expected_chars),
            }
        )
    return {
        "wer": round(word_errors / max(1, word_total), 5),
        "cer": round(char_errors / max(1, char_total), 5),
        "word_errors": word_errors,
        "reference_words": word_total,
        "character_errors": char_errors,
        "reference_characters": char_total,
        "clips": clips,
    }


def main() -> int:
    args = parse_args()
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    loaded = [load_transcript(spec) for spec in args.transcripts]
    references = None
    if args.reference:
        references_payload = json.loads(args.reference.read_text(encoding="utf-8"))
        references = references_payload.get("clips", references_payload)

    report: dict[str, Any] = {"duration_seconds": args.duration, "models": {}}
    api_costs: dict[str, float] = {}
    for spec in args.api_cost:
        if "=" not in spec:
            raise SystemExit(f"Expected --api-cost label=USD, got {spec!r}")
        cost_label, raw_cost = spec.split("=", 1)
        api_costs[cost_label] = float(raw_cost)

    for label, transcript, metadata in loaded:
        metrics = base_metrics(transcript, metadata, args.duration)
        metrics["cost_usd"] = api_costs.get(label, 0.0)
        if references:
            metrics["reference"] = reference_metrics(
                transcript.get("segments", []), references
            )
        report["models"][label] = metrics

    rows: list[dict[str, Any]] = []
    window_count = int((args.duration + args.window_seconds - 1) // args.window_seconds)
    for index in range(window_count):
        start = index * args.window_seconds
        end = min(args.duration, start + args.window_seconds)
        texts = {
            label: text_in_window(transcript.get("segments", []), start, end)
            for label, transcript, _ in loaded
        }
        pair_scores = []
        for left, right in itertools.combinations(texts, 2):
            score = SequenceMatcher(
                None,
                " ".join(normalized_words(texts[left])),
                " ".join(normalized_words(texts[right])),
            ).ratio()
            pair_scores.append(score)
        rows.append(
            {
                "start": start,
                "end": end,
                "mean_pair_similarity": (
                    sum(pair_scores) / len(pair_scores) if pair_scores else 1.0
                ),
                **{f"text_{label}": text for label, text in texts.items()},
            }
        )
    rows.sort(key=lambda row: row["mean_pair_similarity"])
    report["lowest_agreement_windows"] = [
        {
            "start": row["start"],
            "end": row["end"],
            "mean_pair_similarity": round(row["mean_pair_similarity"], 5),
        }
        for row in rows[:20]
    ]

    (output_dir / "benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with (output_dir / "disagreement-windows.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    headers = [
        "Model",
        "Runtime",
        "RTF",
        "Words",
        "Segments",
        "Speakers",
        "Coverage",
        "WER",
        "CER",
        "Marginal/API cost",
    ]
    table = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for label, metrics in report["models"].items():
        reference = metrics.get("reference", {})
        table.append(
            "| "
            + " | ".join(
                [
                    label,
                    str(metrics["runtime_seconds"] or "n/a"),
                    str(metrics["real_time_factor"] or "n/a"),
                    str(metrics["words"]),
                    str(metrics["segments"]),
                    str(metrics["speakers"]),
                    f'{metrics["timeline_coverage"]:.1%}',
                    str(reference.get("wer", "requires reference")),
                    str(reference.get("cer", "requires reference")),
                    f'${metrics["cost_usd"]:.6f}'.rstrip("0").rstrip("."),
                ]
            )
            + " |"
        )
    (output_dir / "benchmark.md").write_text(
        "# STT benchmark\n\n"
        + "\n".join(table)
        + "\n\nWER/CER are reported only against manually corrected reference clips. "
        "Cross-model agreement is recorded separately and is not treated as truth.\n",
        encoding="utf-8",
    )
    print(f"Wrote benchmark to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
