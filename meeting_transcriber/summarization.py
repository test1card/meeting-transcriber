from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .formatting import chunk_lines
from .protocol_final import (
    FINAL_PROTOCOL_SCHEMA,
    render_protocol_markdown,
    sanitize_final_protocol,
    synthesis_source,
)
from .protocol_model_prompts import protocol_model_suffix
from .protocol_guardrails import sanitize_protocol_extraction


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "summary": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic", "summary", "evidence"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string"},
                    "owner": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["decision", "owner", "evidence"],
            },
        },
        "actions": {
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
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "risk": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["risk", "evidence"],
            },
        },
        "open_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["question", "evidence"],
            },
        },
    },
    "required": ["overview", "topics", "decisions", "actions", "risks", "open_questions"],
}


PROTOCOL_EXTRACTION_SYSTEM = (
    "You are preparing structured source material for a short official Russian "
    "meeting protocol written in the style of a competent human secretary. "
    "Extract only load-bearing content supported by the transcript. Exclude "
    "greetings, audibility checks, jokes, speech repairs, repeated wording and "
    "chronological narration. Discover the meeting's subjects from the transcript; "
    "do not force a predefined industry or topic list. Preserve material confirmed "
    "facts and status, exact quantitative values and units, dates, named entities, "
    "alternatives, constraints, dependencies and assumptions when they affect the "
    "meaning or outcome. Omit any category that is absent from the source. Each "
    "topic entry must state one self-contained verifiable fact with only the context "
    "needed to interpret it; do not bundle unrelated claims. Apply these generic "
    "contrasts: a suggestion such as maybe we should do X is discussion, while an "
    "explicit statement that X was decided is a decision; a date for a meeting or "
    "event is not a task deadline, while a date explicitly linked to completing a "
    "task is; mentioning a person is not assigning them, while a direct assignment "
    "or explicit commitment is. A proposal, question, forecast or discussed option "
    "is not a decision. Put an "
    "item in decisions or actions only when it was explicitly adopted, assigned, "
    "or committed to. If one passage contains several independent assignments or "
    "commitments, emit one action for every one of them; never merge, rank or cap "
    "explicit actions during extraction because the final editor selects material ones. "
    "Never infer an owner or deadline; use \"unspecified\" when "
    "absent. Every material item must retain an evidence timestamp. Preserve names "
    "and organization names as heard, and preserve Latin technical terms without "
    "translation or transliteration. Return exactly one JSON object matching the "
    "requested schema and no text outside it."
)

PROTOCOL_SYNTHESIS_SYSTEM = (
    "You are the final editor of an official Russian meeting protocol. Return one "
    "JSON object only; the application will deterministically render it into the "
    "visible sections ПОВЕСТКА СОВЕЩАНИЯ, ОБСУДИЛИ and ПО РЕЗУЛЬТАТАМ СОВЕЩАНИЯ "
    "РЕШИЛИ. Use only supplied extracted facts and verify every retained claim against "
    "its source_context when present. Select the smallest set that retains the "
    "substantive purpose, confirmed status, material quantitative values, constraints, "
    "adopted decisions and consequential assignments. Agenda is a high-level list of "
    "independent projects or outcomes, not a list of technical, financial or schedule "
    "subtopics. Use one agenda item when those aspects all serve one overall purpose; "
    "a deliverable and the contract, client or program governing that same deliverable "
    "are context for one purpose, not independent agenda items. Use multiple items only "
    "when either could stand alone as a separate meeting with a separate outcome. Merge repetition "
    "without combining facts that require different evidence. Do not include separate "
    "risk, blocker or open-question inventories. Before retaining a resolution, verify "
    "that it is an explicit commitment required to change or unblock the substantive "
    "project or operational outcome. Omit meeting logistics, drafting these minutes, "
    "and exploratory internal calculations unless that administrative process is the "
    "meeting's principal subject. "
    "A proposal, forecast, external confirmation or statement that no decision was "
    "made belongs in discussed, not resolutions. Each discussed item and resolution "
    "must copy supporting timestamps from the supplied source. If one discussed sentence "
    "combines facts from different passages, put every required timestamp in its evidence "
    "string separated by commas; otherwise split it into independently supported items. "
    "When later evidence revises an earlier estimate, state the change once and never present "
    "the superseded estimate again as current. If an ASR phrase is visibly garbled or its "
    "meaning is uncertain, omit that fragment rather than polishing it into a new claim. Resolution "
    "tasks begin with an infinitive verb. For every resolution, set basis to assigned, "
    "committed or adopted and copy a short verbatim basis_quote from the evidence passage "
    "that proves the assignment, commitment or adoption. A planned event or status report "
    "without such language is not a resolution. Do not invent names, owners or deadlines; use "
    "\"unspecified\" when absent. Copy stated values only and perform no arithmetic. "
    "Return exactly keys agenda, discussed and resolutions matching this JSON shape: "
    "{\"agenda\":[\"...\"],\"discussed\":[{\"item\":\"...\","
    "\"evidence\":\"[HH:MM:SS], [HH:MM:SS]\"}],\"resolutions\":[{\"task\":\"...\","
    "\"owner\":\"unspecified\",\"due\":\"unspecified\","
    "\"evidence\":\"[HH:MM:SS]\",\"basis\":\"assigned\","
    "\"basis_quote\":\"short exact source quote\"}]}"
)

@dataclass
class ModelResult:
    provider: str
    model: str
    summary_markdown: str
    extraction: dict[str, Any]
    elapsed_seconds: float
    chunk_count: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0

    @property
    def metrics(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "chunks": self.chunk_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "prompt_cache_hit_tokens": self.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": self.prompt_cache_miss_tokens,
            "summary_characters": len(self.summary_markdown),
            "topics": len(self.extraction.get("topics", [])),
            "decisions": len(self.extraction.get("decisions", [])),
            "actions": len(self.extraction.get("actions", [])),
            "risks": len(self.extraction.get("risks", [])),
            "open_questions": len(self.extraction.get("open_questions", [])),
        }


class LocalChatClient:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 1800,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.ollama_num_ctx = int(os.getenv("MEETING_OLLAMA_NUM_CTX", "32768"))
        self.client = httpx.Client(timeout=timeout_seconds)
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.prompt_cache_hit_tokens = 0
        self.prompt_cache_miss_tokens = 0

    def close(self) -> None:
        if self.provider == "ollama":
            try:
                self.client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "keep_alive": 0},
                    timeout=30,
                )
            except Exception:
                pass
        self.client.close()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
    ) -> str:
        if self.provider == "ollama":
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "keep_alive": "10m",
                "think": False,
                "options": {"temperature": 0.0, "num_ctx": self.ollama_num_ctx},
            }
            if schema:
                payload["format"] = schema
            response = self.client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code == 400 and "think" in payload:
                payload.pop("think", None)
                response = self.client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            self.prompt_tokens += int(data.get("prompt_eval_count") or 0)
            self.completion_tokens += int(data.get("eval_count") or 0)
            return data["message"]["content"].strip()

        if self.provider in {"openai", "vllm"}:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.0,
            }
            if schema:
                payload["response_format"] = {"type": "json_object"}
            endpoint = (
                f"{self.base_url}/chat/completions"
                if self.base_url.endswith("/v1")
                else f"{self.base_url}/v1/chat/completions"
            )
            response = self.client.post(
                endpoint,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage") or {}
            self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(usage.get("completion_tokens") or 0)
            return data["choices"][0]["message"]["content"].strip()

        if self.provider == "deepseek":
            if not self.api_key:
                raise ValueError("DEEPSEEK_API_KEY is not configured")
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.0,
                "stream": False,
                "thinking": {
                    "type": (
                        "disabled"
                        if self.model.endswith("-flash")
                        else "enabled"
                    )
                },
                "max_tokens": 8192,
            }
            if not self.model.endswith("-flash"):
                payload["reasoning_effort"] = "high"
            if schema:
                payload["response_format"] = {"type": "json_object"}
            response = self.client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage") or {}
            self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.completion_tokens += int(usage.get("completion_tokens") or 0)
            self.prompt_cache_hit_tokens += int(
                usage.get("prompt_cache_hit_tokens") or 0
            )
            self.prompt_cache_miss_tokens += int(
                usage.get("prompt_cache_miss_tokens") or 0
            )
            return data["choices"][0]["message"]["content"].strip()

        raise ValueError(f"Unsupported LLM provider: {self.provider}")


def parse_json_response(text: str) -> dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Model returned JSON that is not an object")
    return value


def clean_markdown_response(text: str) -> str:
    text = text.strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", text, flags=re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    return text + "\n"


def _extract_chunk(
    client: LocalChatClient,
    chunk: str,
    *,
    chunk_index: int,
    chunk_total: int,
    summary_language: str,
) -> dict[str, Any]:
    system = (
        PROTOCOL_EXTRACTION_SYSTEM
        + protocol_model_suffix(provider=client.provider, model=client.model, stage="extract")
        + f" Write in {summary_language}. "
        "Use exactly the following JSON shape; empty arrays are allowed: "
        '{"overview":"supported overview","topics":[{"topic":"topic",'
        '"summary":"supported summary","evidence":["[00:01:02]"]}],'
        '"decisions":[{"decision":"explicit decision","owner":"unspecified",'
        '"evidence":"[00:01:02]"}],"actions":[{"task":"explicit task",'
        '"owner":"unspecified","due":"unspecified","evidence":"[00:01:02]"}],'
        '"risks":[{"risk":"supported risk","evidence":"[00:01:02]"}],'
        '"open_questions":[{"question":"unresolved question",'
        '"evidence":"[00:01:02]"}]}. '
        "Do not return Markdown, separate JSON objects, an alternative schema, "
        "or text outside the single JSON object."
    )
    user = (
        f"Transcript section {chunk_index}/{chunk_total}:\n\n{chunk}\n\n"
        "Extract an overview, topics, explicit decisions, action items, risks/blockers, "
        "and unresolved questions according to the requested JSON schema."
    )
    raw = client.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        schema=EXTRACTION_SCHEMA,
    )
    try:
        return parse_json_response(raw)
    except (json.JSONDecodeError, ValueError):
        correction = client.chat(
            [
                {"role": "system", "content": "Repair the following into valid JSON only."},
                {"role": "user", "content": raw},
            ],
            schema=EXTRACTION_SCHEMA,
        )
        return parse_json_response(correction)


def combine_extractions(parts: list[dict[str, Any]]) -> dict[str, Any]:
    combined: dict[str, Any] = {
        "overview": [part.get("overview", "") for part in parts if part.get("overview")],
        "topics": [],
        "decisions": [],
        "actions": [],
        "risks": [],
        "open_questions": [],
    }
    for field in ("topics", "decisions", "actions", "risks", "open_questions"):
        for part in parts:
            values = part.get(field, [])
            if isinstance(values, list):
                combined[field].extend(values)
    return combined


def summarize_with_model(
    lines: list[str],
    *,
    provider: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
    summary_language: str = "the same language as the transcript",
    chunk_chars: int = 16_000,
) -> ModelResult:
    started = time.perf_counter()
    chunks = chunk_lines(lines, max_chars=chunk_chars)
    client = LocalChatClient(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
    )
    try:
        parts: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks, start=1):
            print(f"  {model}: extracting section {index}/{len(chunks)}")
            parts.append(
                _extract_chunk(
                    client,
                    chunk,
                    chunk_index=index,
                    chunk_total=len(chunks),
                    summary_language=summary_language,
                )
            )
        extraction = sanitize_protocol_extraction(combine_extractions(parts), lines)
        synthesis_system = (
            PROTOCOL_SYNTHESIS_SYSTEM
            + protocol_model_suffix(provider=provider, model=model, stage="synthesis")
            + f" Write in {summary_language}."
        )
        synthesis_user = json.dumps(
            synthesis_source(extraction, lines),
            ensure_ascii=False,
        )
        print(f"  {model}: synthesizing final minutes")
        synthesis_raw = client.chat(
            [
                {"role": "system", "content": synthesis_system},
                {"role": "user", "content": synthesis_user},
            ],
            schema=FINAL_PROTOCOL_SCHEMA,
        )
        final_protocol = sanitize_final_protocol(
            parse_json_response(synthesis_raw),
            lines,
            require_resolution_basis=True,
            fallback_actions=extraction.get("actions", []),
        )
        extraction["_final_protocol"] = final_protocol
        summary = render_protocol_markdown(final_protocol)
        return ModelResult(
            provider=provider,
            model=model,
            summary_markdown=summary,
            extraction=extraction,
            elapsed_seconds=time.perf_counter() - started,
            chunk_count=len(chunks),
            prompt_tokens=client.prompt_tokens,
            completion_tokens=client.completion_tokens,
            prompt_cache_hit_tokens=client.prompt_cache_hit_tokens,
            prompt_cache_miss_tokens=client.prompt_cache_miss_tokens,
        )
    finally:
        client.close()


def render_metrics_markdown(results: list[ModelResult]) -> str:
    headers = [
        "Provider",
        "Model",
        "Runtime",
        "Input tokens",
        "Output tokens",
        "Topics",
        "Decisions",
        "Actions",
        "Risks",
        "Questions",
    ]
    rows = [
        [
            result.provider,
            result.model,
            f'{result.elapsed_seconds:.1f}s',
            str(result.prompt_tokens or "n/a"),
            str(result.completion_tokens or "n/a"),
            str(len(result.extraction.get("topics", []))),
            str(len(result.extraction.get("decisions", []))),
            str(len(result.extraction.get("actions", []))),
            str(len(result.extraction.get("risks", []))),
            str(len(result.extraction.get("open_questions", []))),
        ]
        for result in results
    ]
    output = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    output.extend("| " + " | ".join(row) + " |" for row in rows)
    output.append(
        "\nCounts measure extraction coverage, not correctness. Review each item against "
        "its timestamp in the canonical transcript."
    )
    return "\n".join(output) + "\n"
