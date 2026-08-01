from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from meeting_transcriber.cli import PROJECT_ROOT
from meeting_transcriber.formatting import chunk_lines, safe_slug, transcript_lines, write_json
from meeting_transcriber.model_tuned_profiles import MODEL_TUNED_PROMPTS
from meeting_transcriber.refined_profiles import REFINED_PROMPTS
from meeting_transcriber.iterative_profiles import ITERATIVE_PROMPTS
from meeting_transcriber.iterative_round2_profiles import ROUND2_PROMPTS
from meeting_transcriber.iterative_round3_profiles import ROUND3_PROMPTS
from meeting_transcriber.iterative_round4_profiles import ROUND4_PROMPTS
from meeting_transcriber.iterative_round5_profiles import ROUND5_PROMPTS
from meeting_transcriber.iterative_round6_profiles import ROUND6_PROMPTS
from meeting_transcriber.iterative_round7_profiles import ROUND7_PROMPTS
from meeting_transcriber.iterative_round8_profiles import ROUND8_PROMPTS
from meeting_transcriber.iterative_round9_profiles import ROUND9_PROMPTS
from meeting_transcriber.summarization import LocalChatClient, parse_json_response


PROTOCOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "date": {"type": "string"},
        "time": {"type": "string"},
        "location": {"type": "string"},
        "attendees": {"type": "array", "items": {"type": "string"}},
        "agenda": {"type": "array", "items": {"type": "string"}},
        "discussed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["item", "evidence"],
            },
        },
        "resolved": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "owner": {"type": "string"},
                    "due": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["task", "owner", "due", "evidence"],
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title", "date", "time", "location", "attendees", "agenda",
        "discussed", "resolved", "notes",
    ],
}

SHAPE = (
    'Return exactly one JSON object with keys: '
    '{"title":"...","date":"DD.MM.YYYY or unspecified",'
    '"time":"HH:MM or unspecified","location":"... or unspecified",'
    '"attendees":["name"],"agenda":["item"],'
    '"discussed":[{"item":"supported fact","evidence":"[HH:MM:SS]"}],'
    '"resolved":[{"task":"infinitive action","owner":"name or unspecified",'
    '"due":"date or unspecified","evidence":"[HH:MM:SS]"}],'
    '"notes":["material uncertainty"]}. Return JSON only.'
)

PROFILES: dict[str, dict[str, str]] = {
    "p0_minimal": {
        "label": "Minimal schema",
        "extract": (
            "Extract meeting protocol data from the transcript. Use only transcript facts. "
            "Write Russian. Include evidence timestamps. " + SHAPE
        ),
        "synthesize": (
            "Merge the extracted meeting data, remove duplicates, and return one final "
            "Russian protocol data object. Use only supplied facts. " + SHAPE
        ),
    },
    "p1_secretary_structure": {
        "label": "Russian secretary structure",
        "extract": (
            "You are the secretary of a Russian scientific and engineering organization. "
            "Extract source data for a formal meeting protocol with the sections ПОВЕСТКА, "
            "ПРИСУТСТВОВАЛИ, ОБСУДИЛИ and ПО РЕЗУЛЬТАТАМ СОВЕЩАНИЯ РЕШИЛИ. "
            "In discussed, retain technical requirements, exact parameters and units, "
            "schedule, contractual constraints, work categories, financing, and status. "
            "In resolved, include assignments and adopted decisions only. Write resolution "
            "tasks with an infinitive verb. Use only transcript facts. " + SHAPE
        ),
        "synthesize": (
            "Act as a formal Russian meeting secretary. Consolidate the extracts into the "
            "data for a concise official protocol: agenda, attendees, discussed facts and "
            "resolutions. Merge repetitions but preserve every material number, unit, date, "
            "contractual restriction and assigned task. " + SHAPE
        ),
    },
    "p2_strict_grounding": {
        "label": "Strict fact and resolution gate",
        "extract": (
            "You are a conservative Russian meeting secretary. Every output claim must be "
            "traceable to the transcript. A proposal, question, forecast, opinion or discussed "
            "option is NOT a resolution. Put an item in resolved only when participants "
            "explicitly adopt it, assign it, or a person explicitly commits to it. Never infer "
            "an owner from proximity. Never invent a deadline. Use unspecified when absent. "
            "Copy names, numbers, dimensions, units, dates, organizations and contract IDs "
            "exactly; if recognition is contradictory, record the uncertainty in notes instead "
            "of silently choosing. Exclude greetings, audibility checks, jokes and repetition. "
            "Write Russian. " + SHAPE
        ),
        "synthesize": (
            "Produce conservative data for a formal Russian protocol. Enforce the resolution "
            "gate again: proposals/questions/options stay in discussed or are omitted; only "
            "explicit adopted decisions, assignments and commitments stay in resolved. Do not "
            "invent owners or deadlines. Deduplicate without dropping technical parameters, "
            "schedule, constraints, work categories, funding and application status. " + SHAPE
        ),
    },
    "p3_human_fidelity": {
        "label": "Human protocol fidelity",
        "extract": (
            "Prepare structured source data that a professional human secretary would use for "
            "a short official Russian protocol. Do not write an executive summary, risks, "
            "blockers, open questions or a chronological retelling. Extract only load-bearing "
            "content. ОБСУДИЛИ must be a compact thematic record of technical requirements, "
            "exact dimensions/power/heat values, completion dates, contractual location "
            "constraints, capital-repair versus reconstruction categories, funding sources, "
            "and power-application status. РЕШИЛИ must contain only concrete approved actions "
            "or assignments, phrased with an infinitive verb, with owner and due date only when "
            "explicit. Attendees must contain only real names explicitly present in the source, "
            "never Speaker labels. Preserve exact Russian organization names and Latin technical "
            "terms. Keep evidence timestamps for audit; they will not be printed in Word. "
            "Exclude speech noise and unsupported detail. " + SHAPE
        ),
        "synthesize": (
            "You are the final editor of an official Russian meeting protocol. Match the terse "
            "style of a competent human secretary: no executive prose, no risk/question sections, "
            "no speaker-by-speaker narrative, no timestamps in visible wording. Keep a compact "
            "ПОВЕСТКА, factual ОБСУДИЛИ, and actionable РЕШИЛИ. Preserve material technical "
            "numbers, units, dates, organizations, contract constraints and work categories. "
            "Resolution tasks start with an infinitive verb. Apply a strict no-invention rule to "
            "attendees, owners and deadlines. Evidence remains in its JSON field for audit. " + SHAPE
        ),
    },
    "p4_human_plus_metadata": {
        "label": "Human fidelity plus clerk metadata",
        "extract": (
            "Use the supplied clerk metadata as authoritative for title, date, time, location, "
            "attendees and agenda. Extract the remaining protocol content like a professional "
            "Russian scientific-organization secretary. Do not create executive summary, risks, "
            "open questions or transcript retelling. Preserve load-bearing technical parameters, "
            "dates, constraints, work categories, funding and status in discussed. Put only "
            "explicit approved actions/assignments in resolved, using infinitive verbs. Never "
            "invent owners or due dates. Evidence timestamps are audit-only. " + SHAPE
        ),
        "synthesize": (
            "Create final structured data for a terse official Russian protocol. Copy supplied "
            "clerk metadata exactly. Consolidate discussed facts and strict resolutions, preserve "
            "technical values and omit speech noise, executive prose, risks and open questions. "
            "Never invent missing owners/deadlines. " + SHAPE
        ),
    },
}


for refined_profile, refined_prompts in REFINED_PROMPTS.items():
    PROFILES[refined_profile] = {
        **refined_prompts,
        "extract": refined_prompts["extract"] + SHAPE,
        "synthesize": refined_prompts["synthesize"] + SHAPE,
    }

for tuned_profile, tuned_prompts in MODEL_TUNED_PROMPTS.items():
    PROFILES[tuned_profile] = {
        **tuned_prompts,
        "extract": tuned_prompts["extract"] + SHAPE,
        "synthesize": tuned_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ITERATIVE_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ROUND2_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ROUND3_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ROUND4_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ROUND5_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ROUND6_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ROUND7_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ROUND8_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

for iterative_profile, iterative_prompts in ROUND9_PROMPTS.items():
    PROFILES[iterative_profile] = {
        **iterative_prompts,
        "extract": iterative_prompts["extract"] + SHAPE,
        "synthesize": iterative_prompts["synthesize"] + SHAPE,
    }

def normalize(value: str) -> str:
    value = value.lower().replace("ё", "е").replace("×", "x")
    value = re.sub(r"[^a-zа-я0-9.,]+", " ", value)
    return " ".join(value.split())


def char_ngrams(value: str, n: int = 3) -> Counter[str]:
    compact = re.sub(r"\s+", " ", normalize(value))
    return Counter(compact[i:i+n] for i in range(max(0, len(compact) - n + 1)))


def cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(count * b.get(key, 0) for key, count in a.items())
    aa = math.sqrt(sum(count * count for count in a.values()))
    bb = math.sqrt(sum(count * count for count in b.values()))
    return dot / (aa * bb) if aa and bb else 0.0


def token_f1(a: str, b: str) -> float:
    left, right = Counter(normalize(a).split()), Counter(normalize(b).split())
    common = sum((left & right).values())
    if not left or not right or not common:
        return 0.0
    precision = common / sum(left.values())
    recall = common / sum(right.values())
    return 2 * precision * recall / (precision + recall)


def similarity(a: str, b: str) -> float:
    return 0.65 * cosine(char_ngrams(a), char_ngrams(b)) + 0.35 * token_f1(a, b)


def greedy_matches(generated: list[str], gold: list[str], threshold: float = 0.28) -> list[dict[str, Any]]:
    candidates = sorted(
        (
            (similarity(generated[gi], gold[ri]), gi, ri)
            for gi in range(len(generated))
            for ri in range(len(gold))
        ),
        reverse=True,
    )
    used_g: set[int] = set()
    used_r: set[int] = set()
    matches: list[dict[str, Any]] = []
    for score, gi, ri in candidates:
        if score < threshold or gi in used_g or ri in used_r:
            continue
        used_g.add(gi)
        used_r.add(ri)
        matches.append({"generated": gi, "gold": ri, "similarity": round(score, 5)})
    return sorted(matches, key=lambda item: item["gold"])


def prf(generated: list[str], gold: list[str], threshold: float = 0.18) -> dict[str, Any]:
    generated_best = [max((similarity(item, ref) for ref in gold), default=0.0) for item in generated]
    gold_best: list[dict[str, Any]] = []
    for ri, ref in enumerate(gold):
        candidates = [(similarity(item, ref), gi) for gi, item in enumerate(generated)]
        score, gi = max(candidates, default=(0.0, -1))
        gold_best.append({"generated": gi, "gold": ri, "similarity": round(score, 5)})
    matches = [item for item in gold_best if item["similarity"] >= threshold]
    precision = sum(score >= threshold for score in generated_best) / len(generated) if generated else (1.0 if not gold else 0.0)
    recall = len(matches) / len(gold) if gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "precision": round(precision, 5),
        "recall": round(recall, 5),
        "f1": round(f1, 5),
        "matches": matches,
        "generated_best_similarity": [round(value, 5) for value in generated_best],
        "generated_count": len(generated),
        "gold_count": len(gold),
        "threshold": threshold,
    }

def numbers(value: str) -> set[str]:
    return {item.replace(",", ".") for item in re.findall(r"\d+(?:[.,]\d+)?", value)}


def numeric_fidelity(generated: list[str], gold: list[str], matches: list[dict[str, Any]]) -> float:
    scores: list[float] = []
    for match in matches:
        left = numbers(generated[match["generated"]])
        right = numbers(gold[match["gold"]])
        if not left and not right:
            continue
        scores.append(len(left & right) / len(left | right) if left | right else 1.0)
    return round(sum(scores) / len(scores), 5) if scores else 0.0


def valid_evidence_fraction(items: list[dict[str, Any]], duration: float) -> float:
    if not items:
        return 1.0
    valid = 0
    for item in items:
        match = re.fullmatch(r"\[(\d{2}):(\d{2}):(\d{2})\]", str(item.get("evidence", "")).strip())
        if not match:
            continue
        hours, minutes, seconds = map(int, match.groups())
        if hours * 3600 + minutes * 60 + seconds <= duration + 2:
            valid += 1
    return round(valid / len(items), 5)


def protocol_markdown(value: dict[str, Any]) -> str:
    lines = [f"# {value.get('title') or 'ПРОТОКОЛ СОВЕЩАНИЯ'}", ""]
    meta = " · ".join(str(value.get(key) or "unspecified") for key in ("date", "time", "location"))
    lines += [meta, "", "## ПОВЕСТКА СОВЕЩАНИЯ", ""]
    lines += [f"{index}. {item}" for index, item in enumerate(value.get("agenda", []), 1)] or ["Не указана"]
    lines += ["", "## ПРИСУТСТВОВАЛИ", ""]
    lines += [f"- {item}" for item in value.get("attendees", [])] or ["Не указаны"]
    lines += ["", "## ОБСУДИЛИ", ""]
    lines += [f"{index}. {item.get('item', '')}" for index, item in enumerate(value.get("discussed", []), 1)] or ["Нет подтвержденных пунктов"]
    lines += ["", "## ПО РЕЗУЛЬТАТАМ СОВЕЩАНИЯ РЕШИЛИ", "", "| № | Поручение | Ответственный | Срок |", "|---:|---|---|---|"]
    for index, item in enumerate(value.get("resolved", []), 1):
        lines.append(f"| {index} | {item.get('task', '')} | {item.get('owner', 'unspecified')} | {item.get('due', 'unspecified')} |")
    if not value.get("resolved"):
        lines.append("| — | Нет подтвержденных поручений | — | — |")
    return "\n".join(lines) + "\n"


def score_result(result: dict[str, Any], gold: dict[str, Any], duration: float) -> dict[str, Any]:
    generated_discussed = [str(item.get("item", "")) for item in result.get("discussed", []) if isinstance(item, dict)]
    generated_resolved = [str(item.get("task", "")) for item in result.get("resolved", []) if isinstance(item, dict)]
    gold_discussed = [item["text"] for item in gold["discussed"]]
    gold_resolved = [item["task"] for item in gold["resolved"]]
    raw_discussed = prf(generated_discussed, gold_discussed, threshold=0.18)
    raw_resolved = prf(generated_resolved, gold_resolved, threshold=0.16)
    grounded_discussed_items = [item for item in gold["discussed"] if item["transcript_availability"] == "full"]
    grounded_resolved_items = [item for item in gold["resolved"] if item["task_availability"] == "full"]
    grounded_discussed = prf(generated_discussed, [item["text"] for item in grounded_discussed_items], threshold=0.18)
    grounded_resolved = prf(generated_resolved, [item["task"] for item in grounded_resolved_items], threshold=0.16)

    attendee_score = prf([str(x) for x in result.get("attendees", [])], gold["attendees"], threshold=0.38)
    agenda_text = " ".join(str(x) for x in result.get("agenda", []))
    agenda_similarity = similarity(agenda_text, " ".join(gold["agenda"]))
    metadata_scores = {
        key: similarity(str(result.get(key, "")), str(gold["metadata"][key]))
        for key in ("title", "date", "time", "location")
    }
    metadata_mean = sum(metadata_scores.values()) / len(metadata_scores)

    owner_scores: list[float] = []
    due_scores: list[float] = []
    for match in raw_resolved["matches"]:
        generated_item = result["resolved"][match["generated"]]
        gold_item = gold["resolved"][match["gold"]]
        owner_scores.append(similarity(str(generated_item.get("owner", "")), gold_item["owner"]))
        due_scores.append(similarity(str(generated_item.get("due", "")), gold_item["due"]))
    owner_accuracy = sum(owner_scores) / len(owner_scores) if owner_scores else 0.0
    due_accuracy = sum(due_scores) / len(due_scores) if due_scores else 0.0

    all_generated = generated_discussed + generated_resolved
    all_gold = gold_discussed + gold_resolved
    all_coverage = prf(all_generated, all_gold, threshold=0.18)
    numeric = numeric_fidelity(all_generated, all_gold, all_coverage["matches"])
    evidence = valid_evidence_fraction(
        [*result.get("discussed", []), *result.get("resolved", [])], duration
    )
    required = set(PROTOCOL_SCHEMA["required"])
    structure = len(required & set(result)) / len(required)
    field_accuracy = (owner_accuracy + due_accuracy) / 2
    discussed_count_closeness = math.exp(-abs(math.log((len(generated_discussed) + 1) / (len(gold_discussed) + 1))))
    resolved_count_closeness = math.exp(-abs(math.log((len(generated_resolved) + 1) / (len(gold_resolved) + 1))))
    attendees = [str(item) for item in result.get("attendees", [])]
    speaker_label_fraction = sum(bool(re.search(r"\bspeaker\s*\d+", item, re.I)) for item in attendees) / len(attendees) if attendees else 0.0
    human_style = 0.45 * discussed_count_closeness + 0.35 * resolved_count_closeness + 0.20 * (1.0 - speaker_label_fraction)
    human_similarity = (
        0.22 * raw_discussed["f1"]
        + 0.28 * raw_resolved["f1"]
        + 0.08 * attendee_score["f1"]
        + 0.07 * agenda_similarity
        + 0.07 * metadata_mean
        + 0.10 * numeric
        + 0.05 * field_accuracy
        + 0.13 * human_style
    )
    grounded_quality = (
        0.36 * grounded_discussed["f1"]
        + 0.39 * grounded_resolved["f1"]
        + 0.10 * evidence
        + 0.05 * structure
        + 0.10 * human_style
    )
    return {
        "human_similarity_score": round(human_similarity, 5),
        "transcript_grounded_score": round(grounded_quality, 5),
        "human_style_score": round(human_style, 5),
        "speaker_label_fraction_in_attendees": round(speaker_label_fraction, 5),
        "discussed_count_closeness": round(discussed_count_closeness, 5),
        "resolved_count_closeness": round(resolved_count_closeness, 5),
        "discussed_vs_human": raw_discussed,
        "resolved_vs_human": raw_resolved,
        "discussed_groundable_only": grounded_discussed,
        "resolved_groundable_only": grounded_resolved,
        "attendees_vs_human": attendee_score,
        "agenda_similarity": round(agenda_similarity, 5),
        "metadata_similarity": round(metadata_mean, 5),
        "metadata_fields": {key: round(value, 5) for key, value in metadata_scores.items()},
        "owner_similarity_on_matched_resolutions": round(owner_accuracy, 5),
        "due_similarity_on_matched_resolutions": round(due_accuracy, 5),
        "numeric_fidelity_on_matched_items": numeric,
        "valid_evidence_fraction": evidence,
        "structure_compliance": round(structure, 5),
    }

def call_json(client: LocalChatClient, messages: list[dict[str, str]], archive: Path) -> dict[str, Any]:
    archive.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"messages": messages, "schema": PROTOCOL_SCHEMA}
    started = time.perf_counter()
    raw = client.chat(messages, schema=PROTOCOL_SCHEMA)
    payload["response"] = raw
    payload["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    try:
        value = parse_json_response(raw)
    except Exception:
        repair_messages = [
            {"role": "system", "content": "Repair into one valid JSON object matching the supplied protocol schema. JSON only."},
            {"role": "user", "content": raw},
        ]
        payload["repair_messages"] = repair_messages
        repaired = client.chat(repair_messages, schema=PROTOCOL_SCHEMA)
        payload["repair_response"] = repaired
        value = parse_json_response(repaired)
    write_json(archive, payload)
    return value


def metadata_context(profile: str, gold: dict[str, Any]) -> dict[str, Any]:
    if profile != "p4_human_plus_metadata":
        return {}
    return {
        **gold["metadata"],
        "attendees": gold["attendees"],
        "agenda": gold["agenda"],
    }


def ollama_residency(client: LocalChatClient, model: str) -> dict[str, Any]:
    """Capture Ollama CPU/GPU residency while the model is loaded."""
    if client.provider != "ollama":
        return {}
    try:
        response = client.client.get(f"{client.base_url}/api/ps", timeout=10)
        response.raise_for_status()
        candidates = response.json().get("models", [])
        entry = next(
            (
                item for item in candidates
                if item.get("name") == model or item.get("model") == model
            ),
            candidates[0] if len(candidates) == 1 else None,
        )
        if not entry:
            return {}
        total = int(entry.get("size") or 0)
        vram = int(entry.get("size_vram") or 0)
        return {
            "ollama_model_resident_bytes": total,
            "ollama_vram_bytes": vram,
            "ollama_cpu_offload_bytes": max(0, total - vram),
            "ollama_gpu_residency_fraction": round(vram / total, 4) if total else 0.0,
        }
    except Exception as exc:
        return {"ollama_residency_error": str(exc)}


def run_profile(
    *, transcript_path: Path, output: Path, gold: dict[str, Any], provider: str,
    base_url: str, model: str, api_key: str | None, profile: str,
    chunk_chars: int, force: bool,
) -> Path:
    run_dir = output / "runs" / safe_slug(model) / profile
    result_path = run_dir / "result.json"
    if result_path.is_file() and not force:
        print(f"SKIP {model} {profile}: cached")
        return run_dir
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    segments = transcript.get("segments", [])
    lines = transcript_lines(segments)
    chunks = chunk_lines(lines, max_chars=chunk_chars)
    context = metadata_context(profile, gold)
    client = LocalChatClient(provider=provider, base_url=base_url, model=model, api_key=api_key)
    started = time.perf_counter()
    try:
        extracted: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks, 1):
            print(f"{model} {profile}: extract {index}/{len(chunks)}")
            user_payload = {
                "clerk_metadata": context or None,
                "transcript_section": f"{index}/{len(chunks)}",
                "transcript": chunk,
            }
            messages = [
                {"role": "system", "content": PROFILES[profile]["extract"]},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ]
            extracted.append(call_json(client, messages, run_dir / "prompts" / f"extract-{index:03d}.json"))
        synthesis_payload = {"clerk_metadata": context or None, "section_extracts": extracted}
        messages = [
            {"role": "system", "content": PROFILES[profile]["synthesize"]},
            {"role": "user", "content": json.dumps(synthesis_payload, ensure_ascii=False)},
        ]
        result = call_json(client, messages, run_dir / "prompts" / "synthesis.json")
        residency = ollama_residency(client, model)
        duration = max(float(item.get("end") or 0) for item in segments) if segments else 0.0
        score = score_result(result, gold, duration)
        metrics = {
            "provider": provider,
            "model": model,
            "profile": profile,
            "profile_label": PROFILES[profile]["label"],
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "chunks": len(chunks),
            "prompt_tokens": client.prompt_tokens,
            "completion_tokens": client.completion_tokens,
            "prompt_cache_hit_tokens": client.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": client.prompt_cache_miss_tokens,
            "metadata_supplied": bool(context),
            **residency,
            **score,
        }
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(result_path, result)
        write_json(run_dir / "metrics.json", metrics)
        (run_dir / "protocol.md").write_text(protocol_markdown(result), encoding="utf-8")
        print(f"DONE {model} {profile}: human={score['human_similarity_score']:.3f} grounded={score['transcript_grounded_score']:.3f}")
        return run_dir
    finally:
        client.close()


def rescore_all(output: Path, gold: dict[str, Any], transcript_path: Path) -> None:
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    segments = transcript.get("segments", [])
    duration = max((float(item.get("end") or 0) for item in segments), default=0.0)
    for result_path in sorted((output / "runs").glob("*/*/result.json")):
        metrics_path = result_path.with_name("metrics.json")
        if not metrics_path.is_file():
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        score_keys = set(score_result(result, gold, duration))
        for key in score_keys:
            metrics.pop(key, None)
        metrics.update(score_result(result, gold, duration))
        write_json(metrics_path, metrics)

def write_matrix(output: Path) -> None:
    rows = []
    for path in sorted((output / "runs").glob("*/*/metrics.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    if not rows:
        return
    write_json(output / "matrix.json", {"profiles": PROFILES, "runs": rows})
    headers = ["Model", "Profile", "Human", "Grounded", "Discuss F1", "Resolve F1", "Owners", "Due", "Numbers", "Evidence", "Time"]
    lines = ["# Minutes prompt sensitivity matrix", "", "| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in sorted(rows, key=lambda x: (x["model"], x["profile"])):
        lines.append("| " + " | ".join([
            row["model"], row["profile"], f"{row['human_similarity_score']:.3f}",
            f"{row['transcript_grounded_score']:.3f}", f"{row['discussed_vs_human']['f1']:.3f}",
            f"{row['resolved_vs_human']['f1']:.3f}", f"{row['owner_similarity_on_matched_resolutions']:.3f}",
            f"{row['due_similarity_on_matched_resolutions']:.3f}", f"{row['numeric_fidelity_on_matched_items']:.3f}",
            f"{row['valid_evidence_fraction']:.3f}", f"{row['elapsed_seconds']:.1f}s",
        ]) + " |")
    lines += ["", "## Sensitivity relative to p0_minimal", ""]
    by_model: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)
    for model, model_rows in sorted(by_model.items()):
        baseline = next((row for row in model_rows if row["profile"] == "p0_minimal"), None)
        if not baseline:
            continue
        lines += [f"### {model}", "", "| Profile | Δ human | Δ grounded |", "|---|---:|---:|"]
        for row in sorted(model_rows, key=lambda x: x["profile"]):
            lines.append(
                f"| {row['profile']} | {row['human_similarity_score'] - baseline['human_similarity_score']:+.3f} | "
                f"{row['transcript_grounded_score'] - baseline['transcript_grounded_score']:+.3f} |"
            )
        lines.append("")
    (output / "matrix.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=["ollama", "deepseek"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--profiles", default=",".join(PROFILES))
    parser.add_argument("--chunk-chars", type=int, default=16000)
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    profiles = [item.strip() for item in args.profiles.split(",") if item.strip()]
    unknown = set(profiles) - set(PROFILES)
    if unknown:
        raise ValueError(f"Unknown profiles: {sorted(unknown)}")
    if args.provider == "deepseek":
        base_url = args.base_url or "https://api.deepseek.com"
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
    else:
        base_url = args.base_url or "http://127.0.0.1:11434"
        api_key = None
    for profile in profiles:
        run_profile(
            transcript_path=args.transcript.resolve(), output=args.output.resolve(), gold=gold,
            provider=args.provider, base_url=base_url, model=args.model, api_key=api_key,
            profile=profile, chunk_chars=args.chunk_chars, force=args.force,
        )
        rescore_all(args.output.resolve(), gold, args.transcript.resolve())
        write_matrix(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
