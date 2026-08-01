from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import torch
from moss_transcribe_diarize import parse_transcript
from moss_transcribe_diarize.inference_utils import (
    DEFAULT_PROMPT,
    build_transcription_messages,
    generate_transcription,
)
from transformers import AutoModelForCausalLM, AutoProcessor


MODEL_ID = "OpenMOSS-Team/MOSS-Transcribe-Diarize"
MODEL_REVISION = "e5118b411bf5a77d7a90c4941066bec93c967312"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Checkpointed long-form MOSS transcription for Russian meetings."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--chunk-seconds", type=int, default=600)
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_glossary(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def duration(path: Path) -> float:
    completed = subprocess.run(
        [
            shutil.which("ffprobe") or "ffprobe",
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


def extract_audio(
    source: Path,
    target: Path,
    *,
    start: float,
    length: float,
) -> None:
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(start),
            "-t",
            str(length),
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


def save_partial(
    output_dir: Path,
    input_path: Path,
    segments: list[dict[str, object]],
    *,
    completed_chunks: int,
    total_chunks: int,
    started: float,
    glossary: list[str],
) -> None:
    payload = {
        "metadata": {
            "input": str(input_path),
            "backend": "moss-transcribe-diarize-checkpointed",
            "model": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "language": "ru",
            "native_diarization": True,
            "speaker_scope": "chunk-local-pending-global-clustering",
            "completed_chunks": completed_chunks,
            "total_chunks": total_chunks,
            "complete": completed_chunks == total_chunks,
            "glossary": glossary,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        },
        "transcript": {"language": "ru", "segments": segments},
    }
    write_json(output_dir / "transcript.json", payload)


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoints = output_dir / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    glossary = read_glossary(args.glossary)
    prompt = DEFAULT_PROMPT
    if glossary:
        prompt += " 热词提示：" + ", ".join(glossary)
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required")

    device = torch.device("cuda:0")
    dtype = torch.bfloat16
    torch.backends.cuda.enable_flash_sdp(True)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cuda.enable_math_sdp(False)
    print(f"Loading pinned MOSS {MODEL_REVISION}...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=True,
        dtype="auto",
    ).to(dtype=dtype).to(device).eval()
    processor = AutoProcessor.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=True,
        fix_mistral_regex=True,
    )

    media_seconds = duration(input_path)
    total_chunks = math.ceil(media_seconds / args.chunk_seconds)
    all_segments: list[dict[str, object]] = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="moss-audio-", dir=output_dir) as temp:
        temp_dir = Path(temp)
        for index in range(total_chunks):
            checkpoint = checkpoints / f"chunk-{index:03d}.json"
            offset = float(index * args.chunk_seconds)
            length = min(float(args.chunk_seconds), media_seconds - offset)
            if checkpoint.is_file():
                cached = json.loads(checkpoint.read_text(encoding="utf-8"))
                all_segments.extend(cached["segments"])
                print(f"MOSS chunk {index + 1}/{total_chunks}: checkpoint reused", flush=True)
                continue
            wav = temp_dir / f"chunk-{index:03d}.wav"
            extract_audio(input_path, wav, start=offset, length=length)
            progress_path = output_dir / "progress.json"
            chunk_started = time.perf_counter()
            last_progress_token = 0

            def progress(tokens: int) -> None:
                nonlocal last_progress_token
                if tokens - last_progress_token < 32:
                    return
                last_progress_token = tokens
                try:
                    write_json(
                    progress_path,
                    {
                        "status": "running",
                        "chunk": index + 1,
                        "total_chunks": total_chunks,
                        "generated_tokens": tokens,
                        "max_new_tokens": args.max_new_tokens,
                        "chunk_elapsed_seconds": round(
                            time.perf_counter() - chunk_started, 2
                        ),
                    },
                )
                except PermissionError:
                    # A concurrent progress reader may briefly hold the file on Windows.
                    pass

            print(
                f"MOSS chunk {index + 1}/{total_chunks}: "
                f"{offset:.1f}s–{offset + length:.1f}s",
                flush=True,
            )
            result = generate_transcription(
                model,
                processor,
                build_transcription_messages(wav, prompt),
                max_length=131072,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                device=device,
                dtype=dtype,
                token_callback=progress,
            )
            parsed = parse_transcript(result["text"])
            chunk_segments = [
                {
                    "start": offset + segment.start,
                    "end": offset + segment.end,
                    "speaker": f"C{index + 1:02d}-{segment.speaker}",
                    "text": segment.text,
                }
                for segment in parsed
            ]
            checkpoint_payload = {
                "chunk": index + 1,
                "offset": offset,
                "duration": length,
                "generated_tokens": int(result["generated_tokens"]),
                "elapsed_seconds": round(time.perf_counter() - chunk_started, 3),
                "raw_text": result["text"],
                "segments": chunk_segments,
            }
            write_json(checkpoint, checkpoint_payload)
            all_segments.extend(chunk_segments)
            save_partial(
                output_dir,
                input_path,
                all_segments,
                completed_chunks=index + 1,
                total_chunks=total_chunks,
                started=started,
                glossary=glossary,
            )

    write_json(
        output_dir / "progress.json",
        {
            "status": "complete",
            "chunk": total_chunks,
            "total_chunks": total_chunks,
        },
    )
    print(f"Completed {total_chunks} MOSS chunks with checkpoints.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
