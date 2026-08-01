from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from pathlib import Path

import torch
from qwen_asr import Qwen3ASRModel

from transcribe_qwen import (
    ALIGNER_ID,
    ALIGNER_REVISION,
    MODEL_ID,
    MODEL_REVISION,
    make_chunk,
    media_duration,
    read_glossary,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Checkpointed Qwen3-ASR transcription with Russian alignment."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--chunk-seconds", type=int, default=240)
    return parser.parse_args()


def save_partial(
    output_dir: Path,
    input_path: Path,
    segments: list[dict],
    *,
    complete_chunks: int,
    total_chunks: int,
    chunk_seconds: int,
    glossary: list[str],
    started: float,
) -> None:
    write_json(
        output_dir / "transcript.json",
        {
            "metadata": {
                "input": str(input_path),
                "backend": "qwen3-asr-checkpointed",
                "model": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "aligner": ALIGNER_ID,
                "aligner_revision": ALIGNER_REVISION,
                "language": "ru",
                "native_diarization": False,
                "chunk_seconds": chunk_seconds,
                "completed_chunks": complete_chunks,
                "total_chunks": total_chunks,
                "complete": complete_chunks == total_chunks,
                "glossary": glossary,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "peak_vram_gb": round(
                    torch.cuda.max_memory_allocated() / 1024**3, 3
                ),
            },
            "transcript": {"language": "ru", "segments": segments},
        },
    )


def main() -> int:
    args = parse_args()
    input_path = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoints = output_dir / "checkpoints"
    checkpoints.mkdir(parents=True, exist_ok=True)
    if not 30 <= args.chunk_seconds <= 295:
        raise SystemExit("--chunk-seconds must be between 30 and 295")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required")
    glossary = read_glossary(args.glossary)
    context = ", ".join(glossary)
    print(f"Loading pinned {MODEL_ID} and forced aligner...", flush=True)
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
    total_chunks = math.ceil(duration / args.chunk_seconds)
    all_segments: list[dict] = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="qwen-audio-", dir=output_dir) as temp:
        temp_dir = Path(temp)
        for index in range(total_chunks):
            checkpoint = checkpoints / f"chunk-{index:03d}.json"
            if checkpoint.is_file():
                cached = json.loads(checkpoint.read_text(encoding="utf-8"))
                all_segments.extend(cached["segments"])
                print(f"Qwen chunk {index + 1}/{total_chunks}: checkpoint reused")
                continue
            offset = float(index * args.chunk_seconds)
            length = min(float(args.chunk_seconds), duration - offset)
            write_json(
                output_dir / "progress.json",
                {
                    "status": "running",
                    "chunk": index + 1,
                    "total_chunks": total_chunks,
                    "start": offset,
                    "end": offset + length,
                },
            )
            wav = temp_dir / f"chunk-{index:03d}.wav"
            make_chunk(input_path, wav, offset, length)
            chunk_started = time.perf_counter()
            print(f"Qwen chunk {index + 1}/{total_chunks}", flush=True)
            result = model.transcribe(
                audio=str(wav),
                context=context,
                language="Russian",
                return_time_stamps=True,
            )[0]
            chunk_segments: list[dict] = []
            if result.time_stamps:
                for item in result.time_stamps:
                    text = str(item.text).strip()
                    if text:
                        chunk_segments.append(
                            {
                                "start": offset + float(item.start_time),
                                "end": offset + float(item.end_time),
                                "text": text,
                            }
                        )
            elif str(result.text).strip():
                chunk_segments.append(
                    {
                        "start": offset,
                        "end": offset + length,
                        "text": str(result.text).strip(),
                    }
                )
            write_json(
                checkpoint,
                {
                    "chunk": index + 1,
                    "offset": offset,
                    "duration": length,
                    "elapsed_seconds": round(
                        time.perf_counter() - chunk_started, 3
                    ),
                    "segments": chunk_segments,
                },
            )
            all_segments.extend(chunk_segments)
            save_partial(
                output_dir,
                input_path,
                all_segments,
                complete_chunks=index + 1,
                total_chunks=total_chunks,
                chunk_seconds=args.chunk_seconds,
                glossary=glossary,
                started=started,
            )
    write_json(
        output_dir / "progress.json",
        {
            "status": "complete",
            "chunk": total_chunks,
            "total_chunks": total_chunks,
        },
    )
    print(f"Completed {total_chunks} Qwen chunks.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
