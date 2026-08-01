from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import statistics
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


WORD_RE = re.compile(
    r"[0-9A-Za-z\u0400-\u04FF]+(?:[-'][0-9A-Za-z\u0400-\u04FF]+)*"
)
TIMESTAMP_RE = re.compile(r"\[(?:(\d{1,2}):)?(\d{2}):(\d{2})\]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate meeting STT, diarization, consensus, and summary outputs."
    )
    parser.add_argument(
        "--transcript", action="append", default=[], help="label=transcript.json"
    )
    parser.add_argument(
        "--summary", action="append", default=[], help="label=minutes.md"
    )
    parser.add_argument(
        "--summary-metrics", action="append", default=[], help="label=metrics.json"
    )
    parser.add_argument(
        "--summary-extraction", action="append", default=[], help="label=extraction.json"
    )
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--consensus-audit", type=Path)
    parser.add_argument("--speaker-clustering", type=Path)
    parser.add_argument("--cost", action="append", default=[], help="label=USD")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window-seconds", type=float, default=30.0)
    return parser.parse_args()


def specs(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Expected label=path, got {value!r}")
        label, raw_path = value.split("=", 1)
        parsed[label] = Path(raw_path).expanduser().resolve()
    return parsed


def costs(values: list[str]) -> dict[str, float]:
    parsed: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Expected label=USD, got {value!r}")
        label, raw_cost = value.split("=", 1)
        parsed[label] = float(raw_cost)
    return parsed


def words(text: str) -> list[str]:
    return [match.group(0).casefold() for match in WORD_RE.finditer(text)]


def normalized(text: str) -> str:
    return " ".join(words(text))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def union_duration(intervals: list[tuple[float, float]]) -> float:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def transcript_text_in_window(
    segments: list[dict[str, Any]], start: float, end: float
) -> str:
    return " ".join(
        str(segment.get("text", "")).strip()
        for segment in segments
        if float(segment.get("start", 0)) < end
        and float(segment.get("end", segment.get("start", 0))) > start
    ).strip()


def transcript_metrics(
    payload: dict[str, Any], duration: float, monetary_cost: float
) -> dict[str, Any]:
    transcript = payload.get("transcript", payload)
    metadata = payload.get("metadata", {})
    segments = transcript.get("segments", [])
    texts = [str(segment.get("text", "")).strip() for segment in segments]
    all_words = words(" ".join(texts))
    intervals = [
        (
            float(segment.get("start", 0)),
            float(segment.get("end", segment.get("start", 0))),
        )
        for segment in segments
    ]
    valid_intervals = [(start, end) for start, end in intervals if end > start]
    segment_durations = [end - start for start, end in valid_intervals]
    speech_seconds = union_duration(valid_intervals)
    last_timestamp = max((end for _, end in valid_intervals), default=0.0)
    speakers = Counter(
        str(segment.get("speaker"))
        for segment in segments
        if segment.get("speaker")
    )
    normalized_segments = [normalized(text) for text in texts if normalized(text)]
    duplicate_occurrences = sum(
        count - 1 for count in Counter(normalized_segments).values() if count > 1
    )
    consecutive_duplicates = sum(
        left == right and bool(left)
        for left, right in zip(normalized_segments, normalized_segments[1:])
    )
    ngrams = list(zip(*(all_words[offset:] for offset in range(5)))) if len(all_words) >= 5 else []
    repeated_ngram_occurrences = sum(
        count - 1 for count in Counter(ngrams).values() if count > 1
    )
    elapsed = metadata.get("elapsed_seconds")
    if elapsed is None and isinstance(metadata.get("consensus"), dict):
        elapsed = metadata["consensus"].get("elapsed_seconds")
    peak_vram = metadata.get("peak_vram_gb")
    if peak_vram is None and isinstance(metadata.get("consensus"), dict):
        peak_vram = metadata["consensus"].get("peak_vram_gb")
    speaker_shares = {
        speaker: count / max(1, sum(speakers.values()))
        for speaker, count in speakers.items()
    }
    return {
        "words": len(all_words),
        "segments": len(segments),
        "speakers": len(speakers),
        "speaker_segment_counts": dict(speakers),
        "tiny_speakers_under_1pct": sum(share < 0.01 for share in speaker_shares.values()),
        "invalid_or_zero_duration_segments": len(intervals) - len(valid_intervals),
        "last_timestamp": round(last_timestamp, 3),
        "timeline_coverage": round(min(last_timestamp / duration, 1.0), 5),
        "speech_union_seconds": round(speech_seconds, 3),
        "speech_coverage": round(speech_seconds / duration, 5),
        "words_per_speech_minute": round(
            len(all_words) / max(speech_seconds / 60, 1e-9), 2
        ),
        "median_segment_seconds": (
            round(statistics.median(segment_durations), 3)
            if segment_durations
            else None
        ),
        "p95_segment_seconds": (
            round(percentile(segment_durations, 0.95) or 0, 3)
            if segment_durations
            else None
        ),
        "exact_duplicate_segment_fraction": round(
            duplicate_occurrences / max(1, len(normalized_segments)), 5
        ),
        "consecutive_duplicate_fraction": round(
            consecutive_duplicates / max(1, len(normalized_segments) - 1), 5
        ),
        "repeated_5gram_fraction": round(
            repeated_ngram_occurrences / max(1, len(ngrams)), 5
        ),
        "elapsed_seconds": elapsed,
        "real_time_factor": (
            round(float(elapsed) / duration, 5) if elapsed is not None else None
        ),
        "peak_vram_gb_allocated": peak_vram,
        "marginal_or_api_cost_usd": monetary_cost,
        "speaker_requirement_pass": bool(speakers),
        "coverage_requirement_pass": last_timestamp / duration >= 0.98,
        "timing_requirement_pass": len(intervals) == len(valid_intervals),
        "standalone_required_gates_pass": (
            bool(speakers)
            and last_timestamp / duration >= 0.98
            and len(intervals) == len(valid_intervals)
        ),
    }


def agreement_metrics(
    loaded: dict[str, dict[str, Any]], duration: float, window_seconds: float
) -> dict[str, Any]:
    similarities: dict[str, list[float]] = {label: [] for label in loaded}
    windows = math.ceil(duration / window_seconds)
    for index in range(windows):
        start = index * window_seconds
        end = min(duration, start + window_seconds)
        window_text = {
            label: normalized(
                transcript_text_in_window(
                    payload.get("transcript", payload).get("segments", []), start, end
                )
            )
            for label, payload in loaded.items()
        }
        for left, right in itertools.combinations(window_text, 2):
            score = SequenceMatcher(None, window_text[left], window_text[right]).ratio()
            similarities[left].append(score)
            similarities[right].append(score)
    return {
        label: {
            "mean_pairwise_window_similarity": round(statistics.mean(values), 5),
            "p10_pairwise_window_similarity": round(percentile(values, 0.10) or 0, 5),
            "median_pairwise_window_similarity": round(statistics.median(values), 5),
        }
        for label, values in similarities.items()
        if values
    }


def consensus_metrics(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    audit = json.loads(path.read_text(encoding="utf-8"))
    units = audit.get("units", [])
    changes = 0
    support_sizes: Counter[int] = Counter()
    confidence: Counter[str] = Counter()
    anchor_edit_ratios: list[float] = []
    for unit in units:
        decision = unit.get("decision", {})
        decided_text = str(decision.get("text", ""))
        anchor_text = next(iter(unit.get("readings", {}).values()), "")
        ratio = SequenceMatcher(None, normalized(anchor_text), normalized(decided_text)).ratio()
        anchor_edit_ratios.append(1.0 - ratio)
        if normalized(anchor_text) != normalized(decided_text):
            changes += 1
        support_sizes[len(decision.get("support", []))] += 1
        confidence[str(decision.get("confidence", "unknown"))] += 1
    metrics = dict(audit.get("metrics", {}))
    metrics.update(
        {
            "changed_anchor_turns": changes,
            "changed_anchor_fraction": round(changes / max(1, len(units)), 5),
            "mean_anchor_text_edit_ratio": round(
                statistics.mean(anchor_edit_ratios), 5
            ) if anchor_edit_ratios else None,
            "confidence_distribution": dict(confidence),
            "support_size_distribution": {
                str(size): count for size, count in sorted(support_sizes.items())
            },
        }
    )
    return metrics


def clustering_metrics(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    silhouette = {
        int(key): float(value)
        for key, value in payload.get("silhouette_by_count", {}).items()
    }
    selected = int(payload.get("selected_global_speakers", 0))
    ordered = sorted(silhouette.values(), reverse=True)
    return {
        "selected_global_speakers": selected,
        "local_speaker_groups": len(payload.get("local_labels", [])),
        "selected_silhouette": silhouette.get(selected),
        "silhouette_margin_over_runner_up": (
            round(ordered[0] - ordered[1], 5) if len(ordered) >= 2 else None
        ),
        "silhouette_by_count": {str(key): value for key, value in silhouette.items()},
    }


def timestamp_seconds(match: re.Match[str]) -> int:
    hours = int(match.group(1) or 0)
    return hours * 3600 + int(match.group(2)) * 60 + int(match.group(3))


def summary_metrics(
    markdown: str,
    metric_payload: dict[str, Any],
    extraction: dict[str, Any],
    *,
    transcript_word_count: int,
    duration: float,
    monetary_cost: float,
) -> dict[str, Any]:
    summary_words = words(markdown)
    timestamps = [timestamp_seconds(match) for match in TIMESTAMP_RE.finditer(markdown)]
    valid_timestamps = [value for value in timestamps if 0 <= value <= duration]
    cited_bins = {int(value // 300) for value in valid_timestamps}
    actions = extraction.get("actions", []) if isinstance(extraction, dict) else []
    decisions = extraction.get("decisions", []) if isinstance(extraction, dict) else []
    explicit_owner = sum(
        str(item.get("owner", "")).strip().casefold()
        not in {"", "unspecified", "не указан", "не указано"}
        for item in actions
        if isinstance(item, dict)
    )
    explicit_due = sum(
        str(item.get("due", "")).strip().casefold()
        not in {"", "unspecified", "не указан", "не указано"}
        for item in actions
        if isinstance(item, dict)
    )
    evidence_complete = sum(
        bool(str(item.get("evidence", "")).strip())
        for item in actions + decisions
        if isinstance(item, dict)
    )
    return {
        **metric_payload,
        "summary_words": len(summary_words),
        "compression_ratio": round(
            len(summary_words) / max(1, transcript_word_count), 5
        ),
        "timestamp_citations": len(timestamps),
        "valid_timestamp_fraction": round(
            len(valid_timestamps) / max(1, len(timestamps)), 5
        ),
        "five_minute_source_bin_coverage": round(
            len(cited_bins) / max(1, math.ceil(duration / 300)), 5
        ),
        "actions_with_explicit_owner_fraction": round(
            explicit_owner / max(1, len(actions)), 5
        ),
        "actions_with_explicit_due_fraction": round(
            explicit_due / max(1, len(actions)), 5
        ),
        "decision_action_evidence_presence": round(
            evidence_complete / max(1, len(actions) + len(decisions)), 5
        ),
        "marginal_or_api_cost_usd": monetary_cost,
        "accuracy_status": "proxy-only until human fact/action reference is supplied",
    }


def table(headers: list[str], rows: list[list[str]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "|" + "|".join("---" for _ in headers) + "|",
            *["| " + " | ".join(row) + " |" for row in rows],
        ]
    )


def main() -> int:
    args = parse_args()
    transcript_paths = specs(args.transcript)
    summary_paths = specs(args.summary)
    summary_metric_paths = specs(args.summary_metrics)
    summary_extraction_paths = specs(args.summary_extraction)
    monetary_costs = costs(args.cost)
    loaded = {
        label: json.loads(path.read_text(encoding="utf-8"))
        for label, path in transcript_paths.items()
    }
    report: dict[str, Any] = {
        "protocol": {
            "ground_truth_primary": [
                "WER/CER",
                "cpWER or tcpWER for speaker-attributed meeting ASR",
                "DER/JER with an explicit collar and overlap policy",
                "decision/action precision, recall, and F1 against human annotations",
                "human factuality, relevance, and readability ratings",
            ],
            "reference_free_diagnostics_not_accuracy": [
                "cross-model window similarity",
                "duplicate/repeated text rates",
                "coverage and invalid timestamps",
                "consensus confidence/support/edit ratios",
                "speaker-cluster silhouette and tiny-speaker warnings",
                "summary citation, evidence, compression, and source-bin coverage",
            ],
        },
        "transcripts": {},
    }
    for label, payload in loaded.items():
        report["transcripts"][label] = transcript_metrics(
            payload, args.duration, monetary_costs.get(label, 0.0)
        )
    agreements = agreement_metrics(loaded, args.duration, args.window_seconds)
    for label, metrics in agreements.items():
        report["transcripts"][label].update(metrics)
    report["consensus"] = consensus_metrics(args.consensus_audit)
    report["speaker_clustering"] = clustering_metrics(args.speaker_clustering)

    consensus_words = report["transcripts"].get("consensus", {}).get("words", 0)
    report["summaries"] = {}
    for label, path in summary_paths.items():
        metric_payload = (
            json.loads(summary_metric_paths[label].read_text(encoding="utf-8"))
            if label in summary_metric_paths
            else {}
        )
        extraction = (
            json.loads(summary_extraction_paths[label].read_text(encoding="utf-8"))
            if label in summary_extraction_paths
            else {}
        )
        report["summaries"][label] = summary_metrics(
            path.read_text(encoding="utf-8"),
            metric_payload,
            extraction,
            transcript_word_count=consensus_words,
            duration=args.duration,
            monetary_cost=monetary_costs.get(label, 0.0),
        )

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    transcript_rows = []
    for label, metric in report["transcripts"].items():
        transcript_rows.append(
            [
                label,
                "PASS" if metric["standalone_required_gates_pass"] else "FAIL",
                str(metric["speakers"]),
                f'{metric["timeline_coverage"]:.1%}',
                str(metric["invalid_or_zero_duration_segments"]),
                str(metric["real_time_factor"] or "n/a"),
                f'{metric["mean_pairwise_window_similarity"]:.3f}',
                f'{metric["repeated_5gram_fraction"]:.3f}',
                f'${metric["marginal_or_api_cost_usd"]:.6f}'.rstrip("0").rstrip("."),
            ]
        )
    summary_rows = []
    for label, metric in report["summaries"].items():
        summary_rows.append(
            [
                label,
                f'{metric.get("elapsed_seconds", 0):.1f}s',
                str(metric.get("decisions", 0)),
                str(metric.get("actions", 0)),
                f'{metric["valid_timestamp_fraction"]:.1%}',
                f'{metric["five_minute_source_bin_coverage"]:.1%}',
                f'{metric["actions_with_explicit_owner_fraction"]:.1%}',
                f'${metric["marginal_or_api_cost_usd"]:.6f}'.rstrip("0").rstrip("."),
            ]
        )
    markdown = (
        "# Meeting pipeline evaluation\n\n"
        "## Current reference-free diagnostic scorecard\n\n"
        + table(
            [
                "Output",
                "Required gates",
                "Speakers",
                "Coverage",
                "Bad timing",
                "RTF",
                "Agreement",
                "5-gram repetition",
                "Cost",
            ],
            transcript_rows,
        )
        + "\n\nAgreement and repetition are diagnostics, not correctness scores.\n\n"
        "## Summary diagnostics\n\n"
        + table(
            [
                "Summary",
                "Runtime",
                "Decisions",
                "Actions",
                "Valid citations",
                "Source-bin coverage",
                "Explicit owners",
                "Cost",
            ],
            summary_rows,
        )
        + "\n\n## Metrics that require human ground truth\n\n"
        "- WER and CER for literal Russian transcription accuracy.\n"
        "- cpWER/tcpWER for words attributed to the correct anonymous speaker.\n"
        "- DER and JER, with the collar and overlap policy reported.\n"
        "- Decision/action precision, recall and F1.\n"
        "- Human factuality, relevance, coherence and readability.\n\n"
        "No composite quality score is reported until these human-reference metrics "
        "exist; arbitrary weights would create false precision.\n"
    )
    (args.output / "evaluation.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
