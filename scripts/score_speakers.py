from __future__ import annotations

import argparse
import itertools
import re
import json
from pathlib import Path
from typing import Any

WORD_RE = re.compile(
    r"[0-9A-Za-z\u0400-\u04FF]+(?:[-'][0-9A-Za-z\u0400-\u04FF]+)*"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Score anonymous speaker labels against manually labeled reference clips. "
            "Uses an exact one-to-one speaker mapping and duration-weighted metrics."
        )
    )
    parser.add_argument(
        "transcripts",
        nargs="+",
        help="Inputs as label=path/to/transcript.json",
    )
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def reference_turns(clips: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[tuple[float, float]]]:
    turns: list[dict[str, Any]] = []
    windows: list[tuple[float, float]] = []
    for clip in clips:
        clip_start = float(clip["start"])
        clip_end = float(clip["end"])
        duration = clip_end - clip_start
        clip_turns = clip.get("speaker_turns", [])
        if not clip_turns:
            continue
        windows.append((clip_start, clip_end))
        for turn in clip_turns:
            start = float(turn["start"])
            end = float(turn["end"])
            # Human references may use clip-relative or recording-absolute times.
            if 0 <= start <= duration and 0 <= end <= duration:
                start += clip_start
                end += clip_start
            start = max(start, clip_start)
            end = min(end, clip_end)
            if end > start:
                turns.append(
                    {
                        "speaker": str(turn["speaker"]),
                        "start": start,
                        "end": end,
                        "text": str(turn.get("text", "")).strip(),
                    }
                )
    return turns, windows


def predicted_turns(
    segments: list[dict[str, Any]], windows: list[tuple[float, float]]
) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for segment in segments:
        speaker = segment.get("speaker")
        if not speaker:
            continue
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start))
        midpoint = (start + end) / 2
        for window_start, window_end in windows:
            clipped_start = max(start, window_start)
            clipped_end = min(end, window_end)
            if clipped_end > clipped_start:
                turns.append(
                    {
                        "speaker": str(speaker),
                        "start": clipped_start,
                        "end": clipped_end,
                        "text": (
                            str(segment.get("text", "")).strip()
                            if window_start <= midpoint < window_end
                            else ""
                        ),
                    }
                )
    return turns


def union_duration(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def best_mapping(
    ref_speakers: list[str],
    pred_speakers: list[str],
    overlaps: dict[tuple[str, str], float],
) -> tuple[dict[str, str], float]:
    if not ref_speakers or not pred_speakers:
        return {}, 0.0
    if len(pred_speakers) >= len(ref_speakers):
        mappings = (
            dict(zip(ref_speakers, permutation))
            for permutation in itertools.permutations(pred_speakers, len(ref_speakers))
        )
    else:
        mappings = (
            dict(zip(permutation, pred_speakers))
            for permutation in itertools.permutations(ref_speakers, len(pred_speakers))
        )
    best: dict[str, str] = {}
    best_score = -1.0
    for mapping in mappings:
        score = sum(overlaps.get((ref, pred), 0.0) for ref, pred in mapping.items())
        if score > best_score:
            best, best_score = mapping, score
    return best, max(0.0, best_score)


def normalized_words(text: str) -> list[str]:
    return [match.group(0).casefold() for match in WORD_RE.finditer(text)]


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for row, expected in enumerate(reference, start=1):
        current = [row]
        for column, actual in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected != actual),
                )
            )
        previous = current
    return previous[-1]


def speaker_streams(turns: list[dict[str, Any]]) -> dict[str, list[str]]:
    streams: dict[str, list[str]] = {}
    for turn in sorted(turns, key=lambda value: (value["start"], value["end"])):
        text_words = normalized_words(str(turn.get("text", "")))
        if text_words:
            streams.setdefault(turn["speaker"], []).extend(text_words)
    return streams


def cpwer(
    refs: list[dict[str, Any]], preds: list[dict[str, Any]]
) -> dict[str, Any] | None:
    reference = speaker_streams(refs)
    predicted = speaker_streams(preds)
    if not reference:
        return None
    ref_labels = sorted(reference)
    pred_labels = sorted(predicted)
    total_reference_words = sum(len(value) for value in reference.values())
    if not predicted:
        return {
            "cpwer": 1.0,
            "cp_word_errors": total_reference_words,
            "cp_reference_words": total_reference_words,
            "cp_mapping_reference_to_prediction": {},
        }
    best_errors: int | None = None
    best_map: dict[str, str] = {}
    if len(pred_labels) >= len(ref_labels):
        mappings = (
            dict(zip(ref_labels, permutation))
            for permutation in itertools.permutations(pred_labels, len(ref_labels))
        )
    else:
        mappings = (
            dict(zip(permutation, pred_labels))
            for permutation in itertools.permutations(ref_labels, len(pred_labels))
        )
    for mapping in mappings:
        errors = sum(
            edit_distance(reference[ref], predicted[pred])
            for ref, pred in mapping.items()
        )
        errors += sum(
            len(reference[ref]) for ref in ref_labels if ref not in mapping
        )
        used_predictions = set(mapping.values())
        errors += sum(
            len(predicted[pred]) for pred in pred_labels if pred not in used_predictions
        )
        if best_errors is None or errors < best_errors:
            best_errors, best_map = errors, mapping
    assert best_errors is not None
    return {
        "cpwer": round(best_errors / max(1, total_reference_words), 5),
        "cp_word_errors": best_errors,
        "cp_reference_words": total_reference_words,
        "cp_mapping_reference_to_prediction": best_map,
    }


def jaccard_error_rate(
    refs: list[dict[str, Any]],
    preds: list[dict[str, Any]],
    overlaps: dict[tuple[str, str], float],
) -> tuple[float, dict[str, str]]:
    ref_labels = sorted({turn["speaker"] for turn in refs})
    pred_labels = sorted({turn["speaker"] for turn in preds})
    ref_duration = {
        label: union_duration(
            [(turn["start"], turn["end"]) for turn in refs if turn["speaker"] == label]
        )
        for label in ref_labels
    }
    pred_duration = {
        label: union_duration(
            [(turn["start"], turn["end"]) for turn in preds if turn["speaker"] == label]
        )
        for label in pred_labels
    }
    jaccard = {
        (ref, pred): overlaps.get((ref, pred), 0.0)
        / max(
            1e-9,
            ref_duration[ref] + pred_duration[pred] - overlaps.get((ref, pred), 0.0),
        )
        for ref in ref_labels
        for pred in pred_labels
    }
    mapping, score = best_mapping(ref_labels, pred_labels, jaccard)
    denominator = max(1, len(ref_labels), len(pred_labels))
    return round(1.0 - score / denominator, 5), mapping


def score_model(
    segments: list[dict[str, Any]],
    refs: list[dict[str, Any]],
    windows: list[tuple[float, float]],
) -> dict[str, Any]:
    preds = predicted_turns(segments, windows)
    ref_speakers = sorted({turn["speaker"] for turn in refs})
    pred_speakers = sorted({turn["speaker"] for turn in preds})
    overlaps: dict[tuple[str, str], float] = {}
    for ref in refs:
        for pred in preds:
            seconds = overlap_seconds(
                ref["start"], ref["end"], pred["start"], pred["end"]
            )
            if seconds:
                key = (ref["speaker"], pred["speaker"])
                overlaps[key] = overlaps.get(key, 0.0) + seconds

    jer, jer_mapping = jaccard_error_rate(refs, preds, overlaps)
    cpwer_metrics = cpwer(refs, preds)

    mapping, _ = best_mapping(ref_speakers, pred_speakers, overlaps)
    boundaries = sorted(
        {
            value
            for turn in [*refs, *preds]
            for value in (turn["start"], turn["end"])
        }
    )
    ref_time = pred_time = correct = 0.0
    missed = false_alarm = confusion = 0.0
    for start, end in zip(boundaries, boundaries[1:]):
        if end <= start:
            continue
        midpoint = (start + end) / 2
        ref_active = {
            turn["speaker"] for turn in refs if turn["start"] <= midpoint < turn["end"]
        }
        pred_active = {
            turn["speaker"] for turn in preds if turn["start"] <= midpoint < turn["end"]
        }
        seconds = end - start
        mapped_reference = {
            mapping[speaker] for speaker in ref_active if speaker in mapping
        }
        correct_count = len(mapped_reference & pred_active)
        ref_count, pred_count = len(ref_active), len(pred_active)
        ref_time += seconds * ref_count
        pred_time += seconds * pred_count
        correct += seconds * correct_count
        missed += seconds * max(0, ref_count - pred_count)
        false_alarm += seconds * max(0, pred_count - ref_count)
        confusion += seconds * max(0, min(ref_count, pred_count) - correct_count)
    return {
        "reference_speakers": len(ref_speakers),
        "predicted_speakers": len(pred_speakers),
        "mapping_reference_to_prediction": mapping,
        "reference_speech_seconds": round(ref_time, 3),
        "predicted_speech_seconds": round(pred_time, 3),
        "correctly_attributed_seconds": round(correct, 3),
        "speaker_attribution_accuracy": round(correct / max(ref_time, 1e-9), 5),
        "missed_speech_seconds": round(missed, 3),
        "jaccard_error_rate": jer,
        "jer_mapping_reference_to_prediction": jer_mapping,
        **({"speaker_attributed_asr": cpwer_metrics} if cpwer_metrics else {}),
        "false_alarm_seconds": round(false_alarm, 3),
        "speaker_confusion_seconds": round(confusion, 3),
        "collar_seconds": 0.0,
        "overlap_policy": "included",
        "diarization_error_rate": round(
            (missed + false_alarm + confusion) / max(ref_time, 1e-9), 5
        ),
    }


def main() -> int:
    args = parse_args()
    payload = json.loads(args.reference.read_text(encoding="utf-8"))
    clips = payload.get("clips", payload)
    refs, windows = reference_turns(clips)
    if not refs:
        raise SystemExit(
            "No speaker_turns found in the reference. Listen to and label the clips first."
        )
    report: dict[str, Any] = {"reference": str(args.reference), "models": {}}
    for spec in args.transcripts:
        if "=" not in spec:
            raise SystemExit(f"Expected label=path, got {spec!r}")
        label, path = spec.split("=", 1)
        model_payload = json.loads(Path(path).read_text(encoding="utf-8"))
        transcript = model_payload.get("transcript", model_payload)
        report["models"][label] = score_model(
            transcript.get("segments", []), refs, windows
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
