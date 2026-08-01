from __future__ import annotations

import copy
import re
from typing import Any

from .protocol_guardrails import (
    action_evidence_supported,
    evidence_context,
    sanitize_protocol_extraction,
)


FINAL_PROTOCOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
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
        "resolutions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "owner": {"type": "string"},
                    "due": {"type": "string"},
                    "evidence": {"type": "string"},
                    "basis": {
                        "type": "string",
                        "enum": ["assigned", "committed", "adopted"],
                    },
                    "basis_quote": {"type": "string"},
                },
                "required": [
                    "task",
                    "owner",
                    "due",
                    "evidence",
                    "basis",
                    "basis_quote",
                ],
            },
        },
    },
    "required": ["agenda", "discussed", "resolutions"],
}


EVIDENCE_RE = re.compile(r"\[\s*[\"']?(\d{2}):(\d{2}):(\d{2})[\"']?\s*\]")
ACTION_BASIS_RE = re.compile(
    r"(?:\b(?:поруч\w*|решили|договорились|давайте|необходимо|нужно|надо)\b|"
    r"\b(?:ты|вы)\b.{0,55}\b[а-яё-]+(?:йте|ите|ьте|ай|уй|и|ь)\b|"
    r"\b(?:проговорю|подготовлю|уточню|проверю|сделаю|проведу|отправлю|направлю|передам|рассчитаю|посчитаю|оценю|выясню|узнаю|поинтересуюсь|согласую|закажу|куплю|позвоню|напишу|свяжусь|обращусь|доложу|представлю|проговорим|подготовим|уточним|проверим|сделаем|проведем|отправим|направим|передадим|рассчитаем|посчитаем|оценим|выясним|узнаем|согласуем|закажем|купим|позвоним|напишем|свяжемся|обратимся|доложим|представим)\b)",
    re.IGNORECASE,
)
ANON_SPEAKER_RE = re.compile(r"\bspeaker\s*\d*\b", re.IGNORECASE)
ROUTINE_ADMIN_RE = re.compile(
    r"(?:"
    r"(?:подготов|состав|оформ)\w*.{0,35}(?:протокол|стенограмм)\w*.{0,35}(?:совещ|засед)\w*|"
    r"(?:назнач|провест|организ|заплан)\w*.{0,35}(?:следующ|повторн)\w*.{0,20}(?:совещ|встреч)\w*|"
    r"(?:встрет|собрат)\w*.{0,60}(?:итогов|окончательн)\w*.{0,25}решени\w*|"
    r"(?:подготов|посчит|оцен)\w*.{0,40}командировоч\w*"
    r")",
    re.IGNORECASE,
)


def _evidence_values(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        matches = list(EVIDENCE_RE.finditer(text))
        if matches:
            result.extend(
                f"[{match.group(1)}:{match.group(2)}:{match.group(3)}]"
                for match in matches
            )
        elif text:
            result.append(text)
    return list(dict.fromkeys(result))


def _with_source_context(
    items: Any,
    transcript_lines: list[str],
) -> list[Any]:
    enriched: list[Any] = []
    for raw in items if isinstance(items, list) else []:
        if not isinstance(raw, dict):
            enriched.append(raw)
            continue
        item = copy.deepcopy(raw)
        contexts: list[str] = []
        context_characters = 0
        for evidence in _evidence_values(item.get("evidence"))[:4]:
            context = evidence_context(
                evidence,
                transcript_lines,
                radius_seconds=18,
            ).strip()
            remaining = 2200 - context_characters
            if context and remaining > 0:
                excerpt = context[:remaining]
                contexts.append(excerpt)
                context_characters += len(excerpt)
        if contexts:
            item["source_context"] = "\n---\n".join(contexts)
        enriched.append(item)
    return enriched


def synthesis_source(
    extraction: dict[str, Any],
    transcript_lines: list[str] | None = None,
) -> dict[str, Any]:
    """Expose material fields and compact verbatim evidence to the final editor."""
    lines = transcript_lines or []
    return {
        "overview": extraction.get("overview", []),
        "topics": _with_source_context(extraction.get("topics", []), lines),
        "decisions": _with_source_context(extraction.get("decisions", []), lines),
        "actions": _with_source_context(extraction.get("actions", []), lines),
    }


def _first_evidence(value: Any) -> str:
    values = _evidence_values(value)
    return values[0] if values else ""


def _normalize_discussed_item(item: dict[str, Any]) -> dict[str, Any]:
    text = str(item.get("item") or item.get("summary") or "").strip()
    if not text:
        subject = str(item.get("subject") or item.get("topic") or "").strip()
        details = str(item.get("details") or "").strip()
        text = ": ".join(part for part in (subject, details) if part)
    return {
        "item": text,
        "evidence": _evidence_values(item.get("evidence")),
    }


def _normalize_resolution(item: dict[str, Any]) -> dict[str, str]:
    return {
        "task": str(
            item.get("task")
            or item.get("action")
            or item.get("resolution")
            or ""
        ).strip(),
        "owner": str(
            item.get("owner")
            or item.get("responsible")
            or item.get("assignee")
            or "unspecified"
        ).strip(),
        "due": str(
            item.get("due")
            or item.get("deadline")
            or item.get("term")
            or "unspecified"
        ).strip(),
        "evidence": _first_evidence(item.get("evidence")),
        "basis": str(item.get("basis") or "").strip().casefold(),
        "basis_quote": str(item.get("basis_quote") or "").strip(),
    }


def _is_routine_admin_resolution(
    item: dict[str, str],
    transcript_lines: list[str],
) -> bool:
    task = item.get("task", "")
    quote = item.get("basis_quote", "")
    direct = "\n".join((task, quote))
    if ROUTINE_ADMIN_RE.search(direct):
        return True
    if not re.search(
        r"(?:протокол|стенограмм|совещ|встреч|командировоч)",
        task,
        flags=re.IGNORECASE,
    ):
        return False
    context = evidence_context(item.get("evidence", ""), transcript_lines)
    return bool(ROUTINE_ADMIN_RE.search("\n".join((direct, context))))


def _resolution_basis_supported(
    item: dict[str, str],
    transcript_lines: list[str],
) -> bool:
    if item["basis"] not in {"assigned", "committed", "adopted"}:
        return False
    quote = item["basis_quote"]
    if not quote or len(quote.split()) > 24 or not ACTION_BASIS_RE.search(quote):
        return False
    context = evidence_context(item["evidence"], transcript_lines)
    normalized_quote = " ".join(quote.casefold().split())
    normalized_context = " ".join(context.casefold().split())
    if normalized_quote not in normalized_context:
        return False
    task_tokens = {
        token[:5]
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", item["task"].casefold())
        if len(token) >= 4
    }
    quote_tokens = {
        token[:5]
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", quote.casefold())
        if len(token) >= 4
    }
    return bool(task_tokens & quote_tokens)


def _resolution_duplicate(
    task: str,
    resolutions: list[dict[str, str]],
) -> bool:
    task_tokens = {
        token[:5]
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", task.casefold())
        if len(token) >= 4
    }
    if not task_tokens:
        return False
    for resolution in resolutions:
        other_tokens = {
            token[:5]
            for token in re.findall(
                r"[A-Za-zА-Яа-яЁё0-9-]+",
                resolution["task"].casefold(),
            )
            if len(token) >= 4
        }
        if other_tokens and len(task_tokens & other_tokens) / min(
            len(task_tokens),
            len(other_tokens),
        ) >= 0.65:
            return True
    return False


def _evidence_seconds(value: str) -> int | None:
    match = EVIDENCE_RE.search(value)
    if not match:
        return None
    hours, minutes, seconds = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _fallback_cluster(
    candidates: list[dict[str, str]],
    resolutions: list[dict[str, str]],
    *,
    window_seconds: int = 120,
) -> list[dict[str, str]]:
    if not candidates:
        return []
    reference_times = [
        seconds
        for item in resolutions
        if (seconds := _evidence_seconds(item["evidence"])) is not None
    ]
    timed = [
        (seconds, item)
        for item in candidates
        if (seconds := _evidence_seconds(item["evidence"])) is not None
    ]
    groups = [
        [item for seconds, item in timed if start <= seconds <= start + window_seconds]
        for start, _ in timed
    ]
    best = max(groups, key=len, default=[])
    if reference_times:
        near_existing = [
            item
            for seconds, item in timed
            if any(abs(seconds - reference) <= window_seconds for reference in reference_times)
        ]
        return near_existing if len(near_existing) >= len(best) else best
    return best if len(best) > 1 else candidates


def sanitize_final_protocol(
    protocol: dict[str, Any],
    transcript_lines: list[str],
    *,
    include_routine_admin: bool = False,
    require_resolution_basis: bool = False,
    fallback_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_agenda = protocol.get("agenda", [])
    if isinstance(raw_agenda, str):
        raw_agenda = [raw_agenda]
    agenda = [str(item).strip() for item in raw_agenda if str(item).strip()]
    discussed_source = [
        normalized
        for item in protocol.get("discussed", [])
        if isinstance(item, dict)
        and (normalized := _normalize_discussed_item(item))["item"]
        and not ANON_SPEAKER_RE.search(normalized["item"])
    ]
    resolution_source = [
        normalized
        for item in protocol.get("resolutions", [])
        if isinstance(item, dict)
        and (normalized := _normalize_resolution(item))["task"]
        and (
            not require_resolution_basis
            or _resolution_basis_supported(normalized, transcript_lines)
        )
        and (
            include_routine_admin
            or not _is_routine_admin_resolution(normalized, transcript_lines)
        )
    ]
    proxy = {
        "topics": [
            {
                "topic": "",
                "summary": item["item"],
                "evidence": item["evidence"],
            }
            for item in discussed_source
        ],
        "decisions": [],
        "actions": resolution_source,
        "risks": [],
        "open_questions": [],
    }
    cleaned = sanitize_protocol_extraction(proxy, transcript_lines)
    discussed = [
        {
            "item": item["summary"],
            "evidence": item.get("evidence", [""])[0]
            if item.get("evidence")
            else "",
        }
        for item in cleaned["topics"]
        if item.get("summary") and item.get("evidence")
    ]
    resolutions = [
        {
            "task": str(item.get("task") or "").strip(),
            "owner": str(item.get("owner") or "unspecified").strip(),
            "due": str(item.get("due") or "unspecified").strip(),
            "evidence": str(item.get("evidence") or "").strip(),
        }
        for item in cleaned["actions"]
        if str(item.get("task") or "").strip() and item.get("evidence")
    ]
    if fallback_actions:
        fallback_proxy = {
            "topics": [],
            "decisions": [],
            "actions": [
                _normalize_resolution(item)
                for item in fallback_actions
                if isinstance(item, dict)
            ],
            "risks": [],
            "open_questions": [],
        }
        fallback_cleaned = sanitize_protocol_extraction(
            fallback_proxy,
            transcript_lines,
        )
        verified_fallback: list[dict[str, str]] = []
        for item in fallback_cleaned["actions"]:
            task = str(item.get("task") or "").strip()
            evidence = str(item.get("evidence") or "").strip()
            if (
                not task
                or not evidence
                or (not include_routine_admin and _is_routine_admin_resolution(item, transcript_lines))
                or not action_evidence_supported(task, evidence, transcript_lines)
                or _resolution_duplicate(task, resolutions)
            ):
                continue
            verified_fallback.append(
                {
                    "task": task,
                    "owner": str(item.get("owner") or "unspecified").strip(),
                    "due": str(item.get("due") or "unspecified").strip(),
                    "evidence": evidence,
                }
            )
        for item in _fallback_cluster(verified_fallback, resolutions):
            if not _resolution_duplicate(item["task"], resolutions):
                resolutions.append(item)
    return {
        "agenda": agenda,
        "discussed": discussed,
        "resolutions": resolutions,
    }


def _cell(value: str) -> str:
    value = value.strip().replace("\n", " ").replace("|", "\\|")
    if value.casefold() in {"", "unspecified", "не указан", "не указано"}:
        return "не указан"
    return value


def render_protocol_markdown(protocol: dict[str, Any]) -> str:
    lines = ["## ПОВЕСТКА СОВЕЩАНИЯ", ""]
    agenda = protocol.get("agenda", [])
    lines.extend(
        f"{index}. {str(item).strip()}"
        for index, item in enumerate(agenda, start=1)
        if str(item).strip()
    )
    if not agenda:
        lines.append("Не указана.")

    lines.extend(["", "## ОБСУДИЛИ", ""])
    discussed = protocol.get("discussed", [])
    lines.extend(
        f"- {str(item.get('item') or '').strip()}"
        for item in discussed
        if str(item.get("item") or "").strip()
    )
    if not discussed:
        lines.append("Содержательные вопросы не выделены.")

    lines.extend(
        [
            "",
            "## ПО РЕЗУЛЬТАТАМ СОВЕЩАНИЯ РЕШИЛИ",
            "",
            "| Поручение | Ответственный | Срок |",
            "|---|---|---|",
        ]
    )
    resolutions = protocol.get("resolutions", [])
    lines.extend(
        f"| {_cell(str(item.get('task') or ''))} "
        f"| {_cell(str(item.get('owner') or ''))} "
        f"| {_cell(str(item.get('due') or ''))} |"
        for item in resolutions
        if str(item.get("task") or "").strip()
    )
    if not resolutions:
        lines.append("| Решения и поручения не зафиксированы | не указан | не указан |")
    return "\n".join(lines).rstrip() + "\n"
