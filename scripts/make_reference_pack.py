from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create human-correction clips from low-agreement STT windows."
    )
    parser.add_argument("disagreements", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--minimum-gap", type=float, default=90.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output.expanduser().resolve()
    clips_dir = output_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    with args.disagreements.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows.sort(key=lambda row: float(row["mean_pair_similarity"]))
    selected: list[dict[str, str]] = []
    for row in rows:
        start = float(row["start"])
        if any(abs(start - float(existing["start"])) < args.minimum_gap for existing in selected):
            continue
        selected.append(row)
        if len(selected) >= args.count:
            break
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required")
    references: list[dict] = []
    for index, row in enumerate(selected, start=1):
        start, end = float(row["start"]), float(row["end"])
        clip_id = f"clip-{index:02d}"
        target = clips_dir / f"{clip_id}-{start:07.1f}-{end:07.1f}.wav"
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                str(start),
                "-t",
                str(end - start),
                "-i",
                str(args.audio.expanduser().resolve()),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-y",
                str(target),
            ],
            check=True,
        )
        references.append(
            {
                "id": clip_id,
                "start": start,
                "end": end,
                "audio": str(target),
                "selection_reason": "low cross-model agreement",
                "mean_pair_similarity": float(row["mean_pair_similarity"]),
                "text": "",
                "speaker_turns": [],
            }
        )
    (output_dir / "reference.json").write_text(
        json.dumps({"clips": references}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        "# Human reference pack\n\n"
        "Listen to every WAV clip and fill `text` with a faithful verbatim transcript. "
        "Fill `speaker_turns` with `{speaker, start, end, text}` entries using consistent "
        "speaker names across clips. Do not copy a model transcript without listening. "
        "Use clip-relative seconds (0.0 to 30.0) for turn boundaries; absolute recording "
        "times are also accepted. Put the exact words spoken during each turn in its "
        "`text` field, and preserve overlapping turns when two people speak together. "
        "Then run `benchmark_stt.py --reference reference.json` for WER/CER and "
        "`score_speakers.py --reference reference.json` for DER, JER, speaker-attribution "
        "accuracy, and cpWER. The bundled speaker scorer uses no boundary collar and "
        "includes overlapping speech; keep this policy fixed when comparing models.\n",
        encoding="utf-8",
    )
    print(f"Created {len(references)} human-reference clips in {clips_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
