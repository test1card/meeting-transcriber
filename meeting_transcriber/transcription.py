from __future__ import annotations

import gc
import os
import time
from pathlib import Path
from typing import Any


def _clear_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def transcribe_recording(
    input_path: Path,
    *,
    model_name: str = "large-v3",
    language: str | None = None,
    device: str = "cuda",
    compute_type: str = "float16",
    batch_size: int = 8,
    align: bool = True,
    diarize: bool = True,
    hf_token: str | None = None,
    min_speakers: int | None = None,
    max_speakers: int | None = None,
    cache_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import torch
    import whisperx

    started = time.perf_counter()
    cache_dir = cache_dir or Path.home() / ".cache" / "meeting-transcriber"
    cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"[1/3] Loading WhisperX model {model_name!r} on {device}...")
    model = whisperx.load_model(
        model_name,
        device,
        compute_type=compute_type,
        language=language,
        vad_method="silero",
        download_root=str(cache_dir),
    )
    audio = whisperx.load_audio(str(input_path))
    print("[1/3] Transcribing...")
    result = model.transcribe(
        audio,
        batch_size=batch_size,
        language=language,
        print_progress=True,
    )
    detected_language = result.get("language") or language
    del model
    _clear_gpu()

    warnings: list[str] = []
    if align and detected_language:
        try:
            print(f"[2/3] Aligning words for language {detected_language!r}...")
            align_model, metadata = whisperx.load_align_model(
                language_code=detected_language,
                device=device,
                model_dir=str(cache_dir / "alignment"),
            )
            result = whisperx.align(
                result["segments"],
                align_model,
                metadata,
                audio,
                device,
                return_char_alignments=False,
                print_progress=True,
            )
            result["language"] = detected_language
            del align_model
            _clear_gpu()
        except Exception as exc:
            warning = f"Alignment skipped after error: {exc}"
            warnings.append(warning)
            print(f"WARNING: {warning}")

    if diarize:
        token = hf_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        if not token:
            warning = (
                "Speaker diarization skipped: HF_TOKEN is not configured. "
                "The transcript is still complete."
            )
            warnings.append(warning)
            print(f"WARNING: {warning}")
        else:
            print("[3/3] Identifying speaker turns with pyannote...")
            try:
                from whisperx.diarize import DiarizationPipeline

                diarizer = DiarizationPipeline(
                    model_name="pyannote/speaker-diarization-community-1",
                    token=token,
                    device=device,
                    cache_dir=str(cache_dir / "diarization"),
                )
                diarization = diarizer(
                    audio,
                    min_speakers=min_speakers,
                    max_speakers=max_speakers,
                )
                result = whisperx.assign_word_speakers(
                    diarization,
                    result,
                    fill_nearest=True,
                )
                del diarizer
                _clear_gpu()
            except Exception as exc:
                warning = f"Speaker diarization skipped after error: {exc}"
                warnings.append(warning)
                print(f"WARNING: {warning}")
    else:
        print("[3/3] Speaker diarization disabled.")

    metadata = {
        "input": str(input_path),
        "model": model_name,
        "language": detected_language,
        "device": device,
        "compute_type": compute_type,
        "batch_size": batch_size,
        "aligned": align,
        "diarization_requested": diarize,
        "warnings": warnings,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }
    return result, metadata

