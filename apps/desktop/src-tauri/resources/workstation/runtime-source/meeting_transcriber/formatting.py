from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def timestamp(seconds: float, *, milliseconds: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    total_ms = round(seconds * 1000)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    if milliseconds:
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def normalize_speakers(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map arbitrary diarization labels to stable, human-friendly labels."""
    mapping: dict[str, str] = {}
    normalized: list[dict[str, Any]] = []
    for segment in segments:
        copy = dict(segment)
        original = str(copy.get("speaker") or "Speaker")
        if original == "Speaker":
            friendly = original
        else:
            friendly = mapping.setdefault(original, f"Speaker {len(mapping) + 1}")
        copy["speaker"] = friendly
        normalized.append(copy)
    return normalized


def merge_segments(
    segments: list[dict[str, Any]],
    *,
    max_gap_seconds: float = 1.5,
    max_chars: int = 900,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for segment in normalize_speakers(segments):
        text = re.sub(r"\s+", " ", str(segment.get("text", ""))).strip()
        if not text:
            continue
        item = {
            "start": float(segment.get("start", 0.0)),
            "end": float(segment.get("end", segment.get("start", 0.0))),
            "speaker": segment.get("speaker", "Speaker"),
            "text": text,
        }
        if merged:
            previous = merged[-1]
            same_speaker = previous["speaker"] == item["speaker"]
            close_enough = item["start"] - previous["end"] <= max_gap_seconds
            short_enough = len(previous["text"]) + len(item["text"]) + 1 <= max_chars
            if same_speaker and close_enough and short_enough:
                previous["end"] = item["end"]
                previous["text"] = f'{previous["text"]} {item["text"]}'
                continue
        merged.append(item)
    return merged


def transcript_lines(segments: list[dict[str, Any]]) -> list[str]:
    return [
        f'[{timestamp(segment["start"])}] {segment["speaker"]}: {segment["text"]}'
        for segment in merge_segments(segments)
    ]


def render_transcript(
    segments: list[dict[str, Any]],
    *,
    source_name: str,
    language: str | None,
) -> str:
    language_line = language or "auto-detected"
    body = "\n\n".join(transcript_lines(segments))
    return (
        f"# Transcript: {source_name}\n\n"
        f"- Language: {language_line}\n"
        f"- Timestamps refer to the original recording.\n\n"
        f"{body}\n"
    )


def render_srt(segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(normalize_speakers(segments), start=1):
        text = re.sub(r"\s+", " ", str(segment.get("text", ""))).strip()
        if not text:
            continue
        start = timestamp(float(segment.get("start", 0.0)), milliseconds=True)
        end = timestamp(float(segment.get("end", 0.0)), milliseconds=True)
        blocks.append(f"{index}\n{start} --> {end}\n{segment['speaker']}: {text}")
    return "\n\n".join(blocks) + "\n"


def chunk_lines(lines: Iterable[str], max_chars: int = 16_000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in lines:
        line_size = len(line) + 1
        if current and current_size + line_size > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_size = 0
        current.append(line)
        current_size += line_size
    if current:
        chunks.append("\n".join(current))
    return chunks


def safe_slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()
    return value or "model"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return str(value)


def render_comparison_html(
    entries: list[tuple[str, str, str]],
    metrics_markdown: str,
) -> str:
    panels = "\n".join(
        (
            f"<article><h2>{html.escape(model)}</h2>"
            f"<div class=\"provider\">{html.escape(provider)}</div>"
            f"<pre>{html.escape(markdown)}</pre></article>"
        )
        for provider, model, markdown in entries
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meeting summary comparison</title>
<style>
:root {{ color-scheme: light dark; --bg:#f4f6fb; --panel:#fff; --ink:#172033;
        --muted:#667085; --line:#d9deea; --accent:#5b5bd6; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#11131a; --panel:#1a1e29; --ink:#eef1f7; --muted:#aab1c2;
          --line:#32394b; --accent:#a8a8ff; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.55 Inter,Segoe UI,system-ui,sans-serif; }}
header {{ padding:28px 32px 12px; }}
h1 {{ margin:0 0 8px; font-size:28px; }}
.sub {{ color:var(--muted); }}
.metrics {{ margin:16px 32px; padding:18px 22px; border:1px solid var(--line);
            border-radius:14px; background:var(--panel); white-space:pre-wrap; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; padding:0 32px 32px; }}
article {{ min-width:0; border:1px solid var(--line); border-radius:14px;
           background:var(--panel); overflow:hidden; }}
article h2 {{ position:sticky; top:0; margin:0; padding:16px 20px;
              background:var(--panel);
              color:var(--accent); font-size:18px; }}
.provider {{ padding:0 20px 12px; border-bottom:1px solid var(--line);
             color:var(--muted); text-transform:uppercase; font-size:11px;
             letter-spacing:.08em; }}
pre {{ margin:0; padding:20px; white-space:pre-wrap; overflow-wrap:anywhere;
       font:14px/1.58 Inter,Segoe UI,system-ui,sans-serif; }}
@media (max-width:900px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<header><h1>Meeting summary comparison</h1>
<div class="sub">Independent summaries generated from the same transcript.</div></header>
<section class="metrics">{html.escape(metrics_markdown)}</section>
<main class="grid">
{panels}
</main>
</body>
</html>
"""
