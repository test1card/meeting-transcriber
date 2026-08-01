from __future__ import annotations

import argparse
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import av
import numpy as np
import torch
from huggingface_hub import snapshot_download
from scipy.spatial.distance import pdist, squareform
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import silhouette_score
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy


MODEL_ID = "speechbrain/spkrec-ecapa-voxceleb"
MODEL_REVISION = "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
SAMPLE_RATE = 16000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map chunk-local MOSS labels to global meeting speaker IDs."
    )
    parser.add_argument("transcript", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--num-speakers", type=int)
    parser.add_argument("--max-speakers", type=int, default=8)
    parser.add_argument("--max-audio-per-local-speaker", type=float, default=35.0)
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_audio(path: Path) -> np.ndarray:
    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = next(stream for stream in container.streams if stream.type == "audio")
        resampler = av.audio.resampler.AudioResampler(
            format="fltp", layout="mono", rate=SAMPLE_RATE
        )
        for frame in container.decode(stream):
            frames = resampler.resample(frame)
            if frames is None:
                continue
            if not isinstance(frames, list):
                frames = [frames]
            for resampled in frames:
                chunks.append(
                    resampled.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                )
        tail = resampler.resample(None)
        if tail is not None:
            if not isinstance(tail, list):
                tail = [tail]
            for resampled in tail:
                chunks.append(
                    resampled.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                )
    return np.concatenate(chunks)


def select_audio(
    waveform: np.ndarray,
    segments: list[dict],
    *,
    max_seconds: float,
) -> np.ndarray:
    candidates = sorted(
        segments,
        key=lambda segment: float(segment["end"]) - float(segment["start"]),
        reverse=True,
    )
    selected: list[np.ndarray] = []
    total = 0.0
    for segment in candidates:
        start = max(0.0, float(segment["start"]) + 0.05)
        end = min(len(waveform) / SAMPLE_RATE, float(segment["end"]) - 0.05)
        length = end - start
        if length < 0.25:
            continue
        allowed = min(length, 12.0, max_seconds - total)
        if allowed < 0.25:
            break
        first = int(start * SAMPLE_RATE)
        last = int((start + allowed) * SAMPLE_RATE)
        selected.append(waveform[first:last])
        selected.append(np.zeros(int(0.1 * SAMPLE_RATE), dtype=np.float32))
        total += allowed
        if total >= max_seconds:
            break
    if not selected:
        raise ValueError("No usable audio for a local speaker")
    sample = np.concatenate(selected)
    minimum_samples = SAMPLE_RATE
    if len(sample) < minimum_samples:
        sample = np.pad(sample, (0, minimum_samples - len(sample)))
    return sample


def choose_speaker_count(
    embeddings: np.ndarray,
    *,
    requested: int | None,
    maximum: int,
) -> tuple[int, dict[str, float]]:
    samples = len(embeddings)
    if requested is not None:
        if not 1 <= requested <= samples:
            raise ValueError("--num-speakers must not exceed local speaker groups")
        return requested, {}
    if samples == 1:
        return 1, {}
    candidates: dict[str, float] = {}
    upper = min(maximum, samples - 1)
    for count in range(2, upper + 1):
        labels = AgglomerativeClustering(
            n_clusters=count,
            metric="cosine",
            linkage="average",
        ).fit_predict(embeddings)
        candidates[str(count)] = float(
            silhouette_score(embeddings, labels, metric="cosine")
        )
    if not candidates:
        return min(2, samples), candidates
    best = max(candidates, key=candidates.get)
    return int(best), candidates


def main() -> int:
    args = parse_args()
    transcript_path = args.transcript.expanduser().resolve()
    audio_path = args.audio.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    segments = transcript["segments"]
    grouped: dict[str, list[dict]] = defaultdict(list)
    for segment in segments:
        grouped[str(segment.get("speaker") or "unknown")].append(segment)
    if not grouped:
        raise SystemExit("No MOSS speaker turns found")

    started = time.perf_counter()
    print("Decoding meeting audio for speaker embeddings...", flush=True)
    waveform = load_audio(audio_path)
    model_path = snapshot_download(repo_id=MODEL_ID, revision=MODEL_REVISION)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    encoder = EncoderClassifier.from_hparams(
        source=model_path,
        savedir=str(output_dir / "ecapa-model"),
        run_opts={"device": device},
        local_strategy=LocalStrategy.COPY,
    )
    local_labels = sorted(
        grouped,
        key=lambda label: min(float(segment["start"]) for segment in grouped[label]),
    )
    embeddings: list[np.ndarray] = []
    durations: dict[str, float] = {}
    for index, label in enumerate(local_labels, start=1):
        sample = select_audio(
            waveform,
            grouped[label],
            max_seconds=args.max_audio_per_local_speaker,
        )
        durations[label] = len(sample) / SAMPLE_RATE
        signal = torch.from_numpy(sample).unsqueeze(0).to(device)
        with torch.inference_mode():
            embedding = encoder.encode_batch(signal).squeeze().detach().cpu().numpy()
        embedding = embedding / max(np.linalg.norm(embedding), 1e-12)
        embeddings.append(embedding)
        print(
            f"Embedded local speaker {index}/{len(local_labels)}: {label}",
            flush=True,
        )
    matrix = np.stack(embeddings)
    count, silhouette = choose_speaker_count(
        matrix,
        requested=args.num_speakers,
        maximum=args.max_speakers,
    )
    if count == 1:
        raw_clusters = np.zeros(len(local_labels), dtype=int)
    else:
        raw_clusters = AgglomerativeClustering(
            n_clusters=count,
            metric="cosine",
            linkage="average",
        ).fit_predict(matrix)

    first_seen = {
        cluster: min(
            float(grouped[label][0]["start"])
            for label, assigned in zip(local_labels, raw_clusters)
            if int(assigned) == int(cluster)
        )
        for cluster in set(raw_clusters)
    }
    stable_clusters = {
        cluster: index + 1
        for index, cluster in enumerate(
            sorted(first_seen, key=lambda value: first_seen[value])
        )
    }
    mapping = {
        label: f"Speaker {stable_clusters[int(cluster)]}"
        for label, cluster in zip(local_labels, raw_clusters)
    }
    global_segments = [
        {**segment, "speaker": mapping[str(segment.get("speaker") or "unknown")]}
        for segment in segments
    ]
    metadata = dict(payload.get("metadata", {}))
    metadata["speaker_clustering"] = {
        "model": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "global_speakers": count,
        "local_speaker_groups": len(local_labels),
        "selection": "fixed" if args.num_speakers else "best-silhouette",
        "silhouette_by_count": silhouette,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    output_payload = {
        "metadata": metadata,
        "transcript": {
            "language": transcript.get("language", "ru"),
            "segments": global_segments,
        },
    }
    write_json(output_dir / "transcript.json", output_payload)
    cosine_distances = squareform(pdist(matrix, metric="cosine")).tolist()
    write_json(
        output_dir / "speaker-clustering.json",
        {
            "mapping": mapping,
            "sample_seconds": durations,
            "cosine_distance_matrix": cosine_distances,
            "local_labels": local_labels,
            "selected_global_speakers": count,
            "silhouette_by_count": silhouette,
        },
    )
    print(f"Mapped {len(local_labels)} local labels to {count} global speakers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
