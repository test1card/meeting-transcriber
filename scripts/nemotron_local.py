"""Offline Nemotron stage. Audio and checkpoint stay local."""
import argparse
import json
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    args = parser.parse_args()
    import soundfile as sf
    import torch
    from transformers import AutoProcessor, AutoModelForAudioFrameClassification

    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("GPU unavailable. Restore NVIDIA access before running diarization.")
    audio, sr = sf.read(args.audio, dtype="float32")
    if sr != 16000 or audio.ndim != 1 or len(audio) == 0:
        raise SystemExit("Expected nonempty mono 16 kHz WAV.")
    started = time.monotonic()
    processor = AutoProcessor.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForAudioFrameClassification.from_pretrained(
        args.model, local_files_only=True,
        dtype=torch.bfloat16 if args.device == "cuda" else torch.float32,
    ).to(args.device).eval()
    print("Nemotron: processing with offline chunk/cache configuration", flush=True)
    inputs = processor(audio, sampling_rate=sr, return_tensors="pt").to(args.device)
    inputs["input_features"] = inputs["input_features"].to(model.dtype)
    with torch.inference_mode():
        output = model(**inputs)
    turns = processor.extract_speaker_dict(output.logits, inputs.attention_mask)[0]
    data = {"segments": [{"start": float(t["Start"]), "end": float(t["End"]),
                          "speaker": f"SPEAKER_{int(t['Speaker']):02d}"} for t in turns],
            "metadata": {"model": str(args.model), "device": args.device,
                         "elapsed_seconds": time.monotonic() - started,
                         "duration_seconds": len(audio) / sr}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temp.replace(args.output)
    print(f"Nemotron complete: {len(turns)} turns", flush=True)


if __name__ == "__main__":
    main()
