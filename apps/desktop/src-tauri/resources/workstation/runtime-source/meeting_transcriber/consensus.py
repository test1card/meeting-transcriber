from __future__ import annotations

import json
import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .summarization import LocalChatClient, parse_json_response


CONSENSUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                    "support": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "note": {"type": "string"},
                },
                "required": ["id", "text", "confidence", "support", "note"],
            },
        }
    },
    "required": ["decisions"],
}


@dataclass(frozen=True)
class TranscriptCandidate:
    label: str
    path: Path
    transcript: dict[str, Any]
    metadata: dict[str, Any]

    @property
    def segments(self) -> list[dict[str, Any]]:
        return self.transcript.get("segments", [])


def load_candidate(path: Path, label: str) -> TranscriptCandidate:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "transcript" in payload:
        transcript = payload["transcript"]
        metadata = payload.get("metadata", {})
    else:
        transcript = payload
        metadata = {}
    if not isinstance(transcript, dict) or not isinstance(
        transcript.get("segments"), list
    ):
        raise ValueError(f"{path} does not contain transcript segments")
    return TranscriptCandidate(
        label=label,
        path=path,
        transcript=transcript,
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
    )


def _segment_bounds(segment: dict[str, Any]) -> tuple[float, float]:
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", start))
    return start, max(start, end)


def _overlap_seconds(
    first: dict[str, Any],
    second: dict[str, Any],
) -> float:
    first_start, first_end = _segment_bounds(first)
    second_start, second_end = _segment_bounds(second)
    return max(
        0.0,
        min(first_end, second_end) - max(first_start, second_start),
    )


def _candidate_text_for_anchor(
    anchor_segment: dict[str, Any],
    candidate_segments: list[dict[str, Any]],
) -> str:
    overlapping = [
        segment
        for segment in candidate_segments
        if _overlap_seconds(anchor_segment, segment) > 0
        and str(segment.get("text", "")).strip()
    ]
    overlapping.sort(key=lambda segment: _segment_bounds(segment)[0])
    return " ".join(
        re.sub(r"\s+", " ", str(segment.get("text", ""))).strip()
        for segment in overlapping
    ).strip()


def build_consensus_units(
    candidates: list[TranscriptCandidate],
    *,
    anchor_label: str,
) -> tuple[TranscriptCandidate, list[dict[str, Any]]]:
    if len(candidates) < 2:
        raise ValueError("Consensus requires at least two STT transcripts")
    labels = [candidate.label for candidate in candidates]
    if len(set(labels)) != len(labels):
        raise ValueError("STT labels must be unique")
    try:
        anchor = next(item for item in candidates if item.label == anchor_label)
    except StopIteration as exc:
        raise ValueError(f"Unknown anchor label {anchor_label!r}") from exc

    units: list[dict[str, Any]] = []
    for index, anchor_segment in enumerate(anchor.segments, start=1):
        text = re.sub(
            r"\s+", " ", str(anchor_segment.get("text", ""))
        ).strip()
        if not text:
            continue
        start, end = _segment_bounds(anchor_segment)
        readings: dict[str, str] = {anchor.label: text}
        for candidate in candidates:
            if candidate is anchor:
                continue
            candidate_text = _candidate_text_for_anchor(
                anchor_segment, candidate.segments
            )
            if candidate_text:
                readings[candidate.label] = candidate_text
        units.append(
            {
                "id": f"A{index:05d}",
                "start": start,
                "end": end,
                "speaker": str(anchor_segment.get("speaker") or "Speaker"),
                "readings": readings,
            }
        )
    if not units:
        raise ValueError("Anchor transcript contains no usable text segments")
    return anchor, units


def _comparison_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).casefold()


def _agreed_decision(unit: dict[str, Any]) -> dict[str, Any] | None:
    readings = unit["readings"]
    if len(readings) < 2:
        return None
    keys = {_comparison_key(text) for text in readings.values()}
    if len(keys) != 1:
        return None
    anchor_label = next(iter(readings))
    return {
        "id": unit["id"],
        "text": readings[anchor_label],
        "confidence": "high",
        "support": list(readings),
        "note": "All available STT readings agree after normalization.",
    }


def _batches(units: list[dict[str, Any]], max_chars: int) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_size = 0
    for unit in units:
        size = len(json.dumps(unit, ensure_ascii=False)) + 1
        if current and current_size + size > max_chars:
            batches.append(current)
            current = []
            current_size = 0
        current.append(unit)
        current_size += size
    if current:
        batches.append(current)
    return batches


def _validate_decisions(
    raw: dict[str, Any],
    units: list[dict[str, Any]],
    labels: set[str],
) -> list[dict[str, Any]]:
    expected = {unit["id"] for unit in units}
    decisions = raw.get("decisions")
    if not isinstance(decisions, list):
        decisions = []
        for decision_id in expected:
            value = raw.get(decision_id)
            if isinstance(value, str):
                value = {"decision": value}
            if not isinstance(value, dict):
                continue
            decisions.append(
                {
                    "id": decision_id,
                    "text": value.get("text") or value.get("decision") or "",
                    "confidence": value.get("confidence", "low"),
                    "support": value.get("support", []),
                    "note": value.get("note", "ID-keyed DeepSeek JSON response."),
                }
            )
        if not decisions:
            raise ValueError("Judge response has no decisions list or ID-keyed decisions")
    by_id: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        decision_id = str(decision.get("id", ""))
        if decision_id not in expected or decision_id in by_id:
            continue
        text = re.sub(r"\s+", " ", str(decision.get("text", ""))).strip()
        if not text:
            continue
        confidence = str(decision.get("confidence", "low"))
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        support = [
            str(label)
            for label in decision.get("support", [])
            if str(label) in labels
        ]
        by_id[decision_id] = {
            "id": decision_id,
            "text": text,
            "confidence": confidence,
            "support": support,
            "note": str(decision.get("note", "")).strip(),
        }
    missing = expected - set(by_id)
    if missing:
        raise ValueError(f"Judge omitted consensus units: {', '.join(sorted(missing))}")
    return [by_id[unit["id"]] for unit in units]
def _parse_judge_response(text: str) -> dict[str, Any]:
    try:
        return parse_json_response(text)
    except json.JSONDecodeError as original_error:
        cleaned = re.sub(r"```(?:json)?|```", "", text, flags=re.IGNORECASE)
        decoder = json.JSONDecoder()
        documents: list[dict[str, Any]] = []
        position = 0
        while position < len(cleaned):
            start = cleaned.find("{", position)
            if start < 0:
                break
            try:
                value, end = decoder.raw_decode(cleaned, start)
            except json.JSONDecodeError:
                position = start + 1
                continue
            if isinstance(value, dict):
                documents.append(value)
            position = end
        if not documents:
            raise original_error
        merged: dict[str, Any] = {}
        decisions: list[Any] = []
        for document in documents:
            if isinstance(document.get("decisions"), list):
                decisions.extend(document["decisions"])
            else:
                merged.update(document)
        if decisions:
            merged["decisions"] = decisions
        return merged




def _judge_batch(
    client: LocalChatClient,
    units: list[dict[str, Any]],
    *,
    language: str,
    glossary: list[str],
) -> list[dict[str, Any]]:
    system = (
        "You are a conservative speech-transcription adjudicator, not a summarizer. "
        "For each ID, reconstruct exactly what was spoken using only the competing STT "
        "readings. The meeting is predominantly Russian with occasional individual "
        "English words. Preserve supported English technical terms, names, identifiers, "
        "numbers, negation, uncertainty, and meaning. Do not translate, paraphrase, "
        "polish content, merge IDs, invent context, or add facts. Fix punctuation and "
        "obvious recognition errors only when supported by another reading or the "
        "glossary. If evidence is genuinely insufficient, retain the anchor reading and "
        "mark confidence low. Return one decision for every ID as valid JSON. "
        'Use exactly this JSON shape: {"decisions":[{"id":"A00001",'
        '"text":"faithful decided text","confidence":"high",'
        '"support":["moss","qwen"],"note":"short evidence note"}]}. '
        "The decisions array must contain every requested ID exactly once. "
        "Do not return separate JSON objects, an ID-keyed map, Markdown, or "
        "explanatory text outside the JSON object."
    )
    user_payload = {
        "primary_language": language,
        "glossary": glossary,
        "units": [
            {
                "id": unit["id"],
                "speaker": unit["speaker"],
                "start": unit["start"],
                "end": unit["end"],
                "readings": unit["readings"],
            }
            for unit in units
        ],
    }
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]
    raw_text = client.chat(messages, schema=CONSENSUS_SCHEMA)
    try:
        parsed = _parse_judge_response(raw_text)
        return _validate_decisions(
            parsed,
            units,
            {label for unit in units for label in unit["readings"]},
        )
    except (json.JSONDecodeError, ValueError) as first_error:
        repair = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Return corrected JSON only. Include exactly one decision for "
                        "every requested ID and no additional IDs."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Validation error: {first_error}\n"
                        f"Required IDs: {[unit['id'] for unit in units]}\n"
                        f"Previous response:\n{raw_text}"
                    ),
                },
            ],
            schema=CONSENSUS_SCHEMA,
        )
        return _validate_decisions(
            _parse_judge_response(repair),
            units,
            {label for unit in units for label in unit["readings"]},
        )


def _judge_batch_resilient(
    client: LocalChatClient,
    units: list[dict[str, Any]],
    *,
    language: str,
    glossary: list[str],
) -> list[dict[str, Any]]:
    validation_error: ValueError | json.JSONDecodeError | None = None
    for attempt in range(1, 4):
        try:
            return _judge_batch(
                client, units, language=language, glossary=glossary
            )
        except httpx.HTTPError as network_error:
            if attempt == 3:
                raise
            delay = 2**attempt
            print(
                f"[consensus retry] Network error ({network_error}); "
                f"retrying in {delay}s",
                flush=True,
            )
            time.sleep(delay)
        except (ValueError, json.JSONDecodeError) as error:
            validation_error = error
            break
    if validation_error is None:
        raise RuntimeError("Consensus retry loop ended without a result")
    error = validation_error
    if True:
        if len(units) == 1:
            unit = units[0]
            anchor_label, anchor_text = next(iter(unit["readings"].items()))
            print(
                f"[consensus fallback] {unit['id']}: {error}; "
                "retaining anchor with low confidence",
                flush=True,
            )
            return [
                {
                    "id": unit["id"],
                    "text": anchor_text,
                    "confidence": "low",
                    "support": [anchor_label],
                    "note": (
                        "Judge validation failed for this individual turn; "
                        "the diarized anchor reading was retained without alteration."
                    ),
                }
            ]
        midpoint = len(units) // 2
        print(
            f"[consensus split] Invalid {len(units)}-turn response ({error}); "
            f"retrying as {midpoint}+{len(units) - midpoint}",
            flush=True,
        )
        return _judge_batch_resilient(
            client,
            units[:midpoint],
            language=language,
            glossary=glossary,
        ) + _judge_batch_resilient(
            client,
            units[midpoint:],
            language=language,
            glossary=glossary,
        )


def adjudicate_transcripts(
    candidates: list[TranscriptCandidate],
    *,
    anchor_label: str,
    provider: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
    language: str = "ru",
    glossary: list[str] | None = None,
    batch_chars: int = 12_000,
    checkpoint_dir: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.perf_counter()
    glossary = glossary or []
    anchor, units = build_consensus_units(candidates, anchor_label=anchor_label)
    decided: dict[str, dict[str, Any]] = {}
    disputed: list[dict[str, Any]] = []
    for unit in units:
        agreement = _agreed_decision(unit)
        if agreement:
            decided[unit["id"]] = agreement
        else:
            disputed.append(unit)

    client = LocalChatClient(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )
    batch_count = 0
    if checkpoint_dir is not None:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    batches = _batches(disputed, max_chars=batch_chars)
    progress_path = checkpoint_dir / "progress.json" if checkpoint_dir else None
    if progress_path is not None:
        progress_path.write_text(
            json.dumps(
                {"status": "running", "completed": 0, "total_chunks": len(batches)},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
    try:
        for batch_count, batch in enumerate(batches, start=1):
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "provider": provider,
                        "model": model,
                        "language": language,
                        "glossary": glossary,
                        "batch": batch,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            checkpoint = (
                checkpoint_dir / f"batch-{batch_count:03d}.json"
                if checkpoint_dir is not None
                else None
            )
            decisions = None
            if checkpoint is not None and checkpoint.is_file():
                cached = json.loads(checkpoint.read_text(encoding="utf-8"))
                if cached.get("fingerprint") == fingerprint:
                    decisions = _validate_decisions(
                        {"decisions": cached.get("decisions")},
                        batch,
                        {label for unit in batch for label in unit["readings"]},
                    )
                    print(f"[consensus {batch_count}/{len(batches)}] checkpoint reused")
            print(
                f"[consensus {batch_count}/{len(batches)}] Judge {model!r}: "
                f"resolving {len(batch)} disputed turns"
            )
            if decisions is None:
                decisions = _judge_batch_resilient(
                    client, batch, language=language, glossary=glossary
                )
                if checkpoint is not None:
                    checkpoint.write_text(
                        json.dumps(
                            {"fingerprint": fingerprint, "decisions": decisions},
                            ensure_ascii=False,
                            indent=2,
                        ) + "\n",
                        encoding="utf-8",
                    )
            for decision in decisions:
                decided[decision["id"]] = decision
            if progress_path is not None:
                progress_path.write_text(
                    json.dumps(
                        {
                            "status": "running",
                            "completed": batch_count,
                            "total_chunks": len(batches),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ) + "\n",
                    encoding="utf-8",
                )
    finally:
        client.close()
    if progress_path is not None:
        progress_path.write_text(
            json.dumps(
                {
                    "status": "complete",
                    "completed": len(batches),
                    "total_chunks": len(batches),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    output_segments: list[dict[str, Any]] = []
    audit_units: list[dict[str, Any]] = []
    for unit in units:
        decision = decided[unit["id"]]
        output_segments.append(
            {
                "start": unit["start"],
                "end": unit["end"],
                "speaker": unit["speaker"],
                "text": decision["text"],
                "consensus": {
                    "confidence": decision["confidence"],
                    "support": decision["support"],
                },
            }
        )
        audit_units.append({**unit, "decision": decision})

    transcript = {
        "language": language,
        "segments": output_segments,
    }
    audit = {
        "anchor": anchor.label,
        "anchor_path": str(anchor.path),
        "candidates": [
            {"label": candidate.label, "path": str(candidate.path)}
            for candidate in candidates
        ],
        "judge": {"provider": provider, "model": model},
        "glossary": glossary,
        "units": audit_units,
        "metrics": {
            "total_units": len(units),
            "automatic_agreements": len(units) - len(disputed),
            "llm_disputes": len(disputed),
            "low_confidence": sum(
                decision["confidence"] == "low" for decision in decided.values()
            ),
            "judge_batches": batch_count,
            "prompt_tokens": client.prompt_tokens,
            "prompt_cache_hit_tokens": client.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": client.prompt_cache_miss_tokens,
            "completion_tokens": client.completion_tokens,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        },
    }
    return transcript, audit
