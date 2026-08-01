from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import torch
from qwen_asr import Qwen3ASRModel


MODEL_ID = "Qwen/Qwen3-ASR-1.7B"
MODEL_REVISION = "7278e1e70fe206f11671096ffdd38061171dd6e5"
ALIGNER_ID = "Qwen/Qwen3-ForcedAligner-0.6B"
ALIGNER_REVISION = "c7cbfc2048c462b0d63a45797104fc9db3ad62b7"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe a Russian meeting with Qwen3-ASR and forced alignment."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--chunk-seconds", type=int, default=240)
    return parser.parse_args()


def read_glossary(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def media_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required and was not found on PATH")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(completed.stdout.strip())


def make_chunk(source: Path, target: Path, start: float, duration: float) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required and was not found on PATH")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-i",
            str(source),
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


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input does not exist: {input_path}")
    if not 30 <= args.chunk_seconds <= 295:
        raise SystemExit("--chunk-seconds must be between 30 and 295")
    output_dir.mkdir(parents=True, exist_ok=True)
    glossary = read_glossary(args.glossary)
    context = ", ".join(glossary)

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this configured Qwen runner")
    started = time.perf_counter()
    print(f"Loading {MODEL_ID} with {ALIGNER_ID}...", flush=True)
    model = Qwen3ASRModel.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        dtype=torch.bfloat16,
        device_map="cuda:0",
        max_inference_batch_size=1,
        max_new_tokens=2048,
        forced_aligner=ALIGNER_ID,
        forced_aligner_kwargs={
            "revision": ALIGNER_REVISION,
            "dtype": torch.bfloat16,
            "device_map": "cuda:0",
        },
    )
    duration = media_duration(input_path)
    segments: list[dict[str, object]] = []
    chunks = max(1, int((duration + args.chunk_seconds - 1) // args.chunk_seconds))
    with tempfile.TemporaryDirectory(prefix="qwen-asr-", dir=output_dir) as temp:
        temp_dir = Path(temp)
        for index in range(chunks):
            offset = float(index * args.chunk_seconds)
            length = min(float(args.chunk_seconds), duration - offset)
            chunk_path = temp_dir / f"chunk-{index:04d}.wav"
            print(
                f"Qwen chunk {index + 1}/{chunks}: "
                f"{offset:.1f}s to {offset + length:.1f}s",
                flush=True,
            )
            make_chunk(input_path, chunk_path, offset, length)
            result = model.transcribe(
                audio=str(chunk_path),
                context=context,
                language="Russian",
                return_time_stamps=True,
            )[0]
            timestamps = result.time_stamps or []
            if timestamps:
                for item in timestamps:
                    text = str(item.text).strip()
                    if text:
                        segments.append(
                            {
                                "start": offset + float(item.start_time),
                                "end": offset + float(item.end_time),
                                "text": text,
                            }
                        )
            elif str(result.text).strip():
                segments.append(
                    {
                        "start": offset,
                        "end": offset + length,
                        "text": str(result.text).strip(),
                    }
                )

    payload = {
        "metadata": {
            "input": str(input_path),
            "backend": "qwen3-asr",
            "model": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "aligner": ALIGNER_ID,
            "aligner_revision": ALIGNER_REVISION,
            "language": "ru",
            "native_diarization": False,
            "chunk_seconds": args.chunk_seconds,
            "glossary": glossary,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "gpu": torch.cuda.get_device_name(0),
        },
        "transcript": {"language": "ru", "segments": segments},
    }
    write_json(output_dir / "transcript.json", payload)
    print(f"Wrote {len(segments)} aligned Qwen segments to {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
