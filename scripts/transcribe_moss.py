from __future__ import annotations

import argparse
import json
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
        description="Transcribe and diarize a Russian meeting with pinned MOSS."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--max-new-tokens", type=int, default=32768)
    return parser.parse_args()


def read_glossary(path: Path | None) -> list[str]:
    if path is None:
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


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
    output_dir.mkdir(parents=True, exist_ok=True)
    glossary = read_glossary(args.glossary)
    prompt = DEFAULT_PROMPT
    if glossary:
        prompt += " 热词提示：" + ", ".join(glossary)

    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required for this configured MOSS runner")
    device = torch.device("cuda:0")
    dtype = torch.bfloat16
    # Long-form audio requires a fused/memory-efficient SDPA kernel. The math
    # fallback materializes the full attention matrix and cannot fit meetings.
    torch.backends.cuda.enable_flash_sdp(True)
    torch.backends.cuda.enable_mem_efficient_sdp(True)
    torch.backends.cuda.enable_math_sdp(False)
    print(f"Loading {MODEL_ID} at pinned revision {MODEL_REVISION}...", flush=True)
    started = time.perf_counter()
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

    last_report = 0

    def progress(tokens: int) -> None:
        nonlocal last_report
        if tokens - last_report >= 256:
            print(f"MOSS generated {tokens} tokens...", flush=True)
            last_report = tokens

    result = generate_transcription(
        model,
        processor,
        build_transcription_messages(input_path, prompt),
        max_length=131072,
        max_new_tokens=args.max_new_tokens,
        do_sample=False,
        device=device,
        dtype=dtype,
        token_callback=progress,
    )
    parsed = parse_transcript(result["text"])
    segments = [
        {
            "start": segment.start,
            "end": segment.end,
            "speaker": segment.speaker,
            "text": segment.text,
        }
        for segment in parsed
    ]
    payload = {
        "metadata": {
            "input": str(input_path),
            "backend": "moss-transcribe-diarize",
            "model": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "language": "ru",
            "native_diarization": True,
            "glossary": glossary,
            "prompt_tokens": int(result["prompt_len"]),
            "generated_tokens": int(result["generated_tokens"]),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "gpu": torch.cuda.get_device_name(0),
        },
        "transcript": {"language": "ru", "segments": segments},
    }
    write_json(output_dir / "transcript.json", payload)
    (output_dir / "raw-moss.txt").write_text(result["text"] + "\n", encoding="utf-8")
    print(f"Wrote {len(segments)} MOSS speaker turns to {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
