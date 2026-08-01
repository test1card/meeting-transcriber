from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Losslessly group Qwen forced-aligner word tokens into timed utterances."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-gap", type=float, default=0.9)
    parser.add_argument("--max-duration", type=float, default=12.0)
    return parser.parse_args()


def effective_tokens(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = float(segment.get("start", 0))
        raw_end = float(segment.get("end", start))
        next_start = (
            float(segments[index + 1].get("start", start))
            if index + 1 < len(segments)
            else start + 0.24
        )
        if raw_end <= start:
            positive_next = next_start if next_start > start else start + 0.24
            end = min(positive_next, start + 0.4)
        else:
            # Prevent a single badly stretched aligner token from contaminating
            # many unrelated anchor turns. Text and start time are unchanged.
            end = min(raw_end, start + 3.0)
        end = max(end, start + 0.08)
        tokens.append({"start": start, "end": end, "text": text})
    return tokens


def join_text(parts: list[str]) -> str:
    text = " ".join(parts)
    text = re.sub(r"\s+([,.;:!?%])", r"\1", text)
    text = re.sub(r"([«(])\s+", r"\1", text)
    text = re.sub(r"\s+([»)])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def group_tokens(
    tokens: list[dict[str, Any]], max_gap: float, max_duration: float
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for token in tokens:
        if current:
            gap = token["start"] - current[-1]["end"]
            duration = max(token["end"], current[-1]["end"]) - current[0]["start"]
            if gap > max_gap or duration > max_duration:
                groups.append(
                    {
                        "start": current[0]["start"],
                        "end": max(item["end"] for item in current),
                        "text": join_text([item["text"] for item in current]),
                    }
                )
                current = []
        current.append(token)
    if current:
        groups.append(
            {
                "start": current[0]["start"],
                "end": max(item["end"] for item in current),
                "text": join_text([item["text"] for item in current]),
            }
        )
    return groups


def main() -> int:
    args = parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    source = transcript.get("segments", [])
    grouped = group_tokens(effective_tokens(source), args.max_gap, args.max_duration)
    metadata = dict(payload.get("metadata", {}))
    metadata["segment_normalization"] = {
        "method": "lossless-word-to-utterance-grouping",
        "source_segments": len(source),
        "output_segments": len(grouped),
        "max_gap_seconds": args.max_gap,
        "max_utterance_seconds": args.max_duration,
    }
    result = {
        "metadata": metadata,
        "transcript": {"language": transcript.get("language", "ru"), "segments": grouped},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Grouped {len(source)} Qwen tokens into {len(grouped)} utterances.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
