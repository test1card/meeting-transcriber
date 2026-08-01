from __future__ import annotations

import copy
import re
from typing import Any


TIMESTAMP_RE = re.compile(r"\[(\d{2}):(\d{2}):(\d{2})\]")
TIMESTAMP_FLEX_RE = re.compile(
    r"\[\s*[\"']?(\d{2}):(\d{2}):(\d{2})[\"']?\s*\]"
)
SPEAKER_RE = re.compile(r"^\s*speaker(?:\s+\d+)?\s*$", re.IGNORECASE)
UNSUPPORTED_OWNER_RE = re.compile(
    r"^\s*(?:я|ты|он|она|мы|вы|они|кто-то|кто-нибудь|"
    r"неизвестно|не указан(?:о|а)?|unspecified)\s*$",
    re.IGNORECASE,
)
DEADLINE_CUE_RE = re.compile(
    r"(?:\bдо\b|\bк\b|не позднее|в течение|"
    r"срок(?:\s+выполнения)?|дедлайн)",
    re.IGNORECASE,
)
DECISION_CUE_RE = re.compile(
    r"(?:реш(?:или|ено)|принят\w*\s+решени|утверд\w*|согласовал\w*|"
    r"постанов\w*|одобр\w*|отклонил\w*|договорил\w*|"
    r"выбираем|выбрали|отказываемся|отказались)",
    re.IGNORECASE,
)
NUMBER_RE = re.compile(
    r"(?<![\w:])\d+(?:[.,]\d+)?(?:\s*[-–—]\s*\d+(?:[.,]\d+)?)?"
)
ACTION_EVIDENCE_CUE_RE = re.compile(
    r"(?:\b(?:поруч\w*|решили|договорились|давайте|необходимо|нужно|надо|прошу)\b|"
    r"\b(?:ты|вы)\b.{0,55}\b[а-яё-]+(?:йте|ите|ьте|ай|уй|и|ь)\b|"
    r"\b(?:проговорю|подготовлю|уточню|проверю|сделаю|проведу|отправлю|направлю|передам|рассчитаю|посчитаю|оценю|выясню|узнаю|поинтересуюсь|согласую|закажу|куплю|позвоню|напишу|свяжусь|обращусь|доложу|представлю|проговорим|подготовим|уточним|проверим|сделаем|проведем|отправим|направим|передадим|рассчитаем|посчитаем|оценим|выясним|узнаем|согласуем|закажем|купим|позвоним|напишем|свяжемся|обратимся|доложим|представим)\b)",
    re.IGNORECASE,
)
STRONG_ASSIGNMENT_CUE_RE = re.compile(
    r"(?:\b(?:поруч\w*|решили|договорились|давайте|необходимо|нужно|надо|прошу)\b|"
    r"\b(?:ты|вы)\b.{0,55}\b[а-яё-]+(?:йте|ите|ьте|ай|уй|и|ь)\b)",
    re.IGNORECASE,
)
PLANNED_STATUS_RE = re.compile(
    r"(?:\bпредстоит\b|\bпланиру\w*|\bсобира\w*|\bбудет\b.{0,35}\b(?:едет|поедет|встреча)\b)",
    re.IGNORECASE,
)


def _seconds(value: str) -> int | None:
    match = TIMESTAMP_RE.search(value)
    if not match:
        return None
    hours, minutes, seconds = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _line_seconds(line: str) -> int | None:
    return _seconds(line)


def evidence_context(
    evidence: str,
    transcript_lines: list[str],
    *,
    radius_seconds: int = 45,
) -> str:
    target = _seconds(evidence)
    if target is None:
        return ""
    selected = [
        line
        for line in transcript_lines
        if (line_time := _line_seconds(line)) is not None
        and abs(line_time - target) <= radius_seconds
    ]
    return "\n".join(selected)


def _stem_tokens(value: str) -> set[str]:
    return {
        token[:4]
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", value.casefold())
        if len(token) >= 4 and not token.isdigit()
    }


def action_evidence_supported(
    task: str,
    evidence: str,
    transcript_lines: list[str],
) -> bool:
    """Return True when a nearby source line explicitly commits to the task."""
    task_tokens = _stem_tokens(task)
    if not task_tokens:
        return False
    context = evidence_context(evidence, transcript_lines)
    for line in context.splitlines():
        if not ACTION_EVIDENCE_CUE_RE.search(line):
            continue
        planned = PLANNED_STATUS_RE.search(line)
        if planned:
            nearby = line[
                max(0, planned.start() - 30) : min(len(line), planned.end() + 90)
            ]
            if not STRONG_ASSIGNMENT_CUE_RE.search(nearby):
                continue
        overlap = task_tokens & _stem_tokens(line)
        required = 2 if len(task_tokens) >= 3 else 1
        if len(overlap) >= required:
            return True
    return False


def _literal_in_context(value: str, context: str) -> bool:
    return bool(
        re.search(
            rf"(?<!\w){re.escape(value.strip())}(?!\w)",
            context,
            flags=re.IGNORECASE,
        )
    )


def _inflected_tokens_in_context(value: str, context: str) -> bool:
    value_tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", value.casefold())
    context_tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", context.casefold())
    if not value_tokens:
        return False
    for token in value_tokens:
        if not any(
            candidate == token
            or (
                len(token) >= 5
                and len(candidate) >= 5
                and candidate[:5] == token[:5]
            )
            for candidate in context_tokens
        ):
            return False
    return True


def _inflected_sequence_in_context(value: str, context: str) -> bool:
    value_tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", value.casefold())
    context_tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", context.casefold())
    if not value_tokens:
        return False

    def matches(expected: str, actual: str) -> bool:
        return expected == actual or (
            len(expected) >= 5
            and len(actual) >= 5
            and expected[:5] == actual[:5]
        )

    width = len(value_tokens)
    return any(
        all(
            matches(expected, actual)
            for expected, actual in zip(
                value_tokens,
                context_tokens[start : start + width],
            )
        )
        for start in range(max(0, len(context_tokens) - width + 1))
    )


def _supported_owner(owner: str, context: str) -> bool:
    owner = owner.strip()
    if (
        not owner
        or SPEAKER_RE.fullmatch(owner)
        or UNSUPPORTED_OWNER_RE.fullmatch(owner)
    ):
        return False
    if not context:
        return False
    owner_tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", owner)
    owner_pattern = r"\s+".join(
        rf"{re.escape(token[:4])}[A-Za-zА-Яа-яЁё0-9-]*"
        for token in owner_tokens
    )
    explicit_relation = re.compile(
        r"(?:поруч(?:ить|аю|ено)|ответственн\w*|назнач\w*|"
        r"сделает|выполнит|подготовит|рассчитает|оценит)\W{0,45}$",
        re.IGNORECASE,
    )
    for line in context.splitlines():
        for match in re.finditer(owner_pattern, line, flags=re.IGNORECASE):
            before = line[max(0, match.start() - 70) : match.start()]
            after = line[match.end() : match.end() + 90]
            if explicit_relation.search(before):
                return True
            if re.match(
                r"\s*[,—:-]\s*[а-яё-]+(?:йте|ите|ьте|ай|уй|и|ь)\b",
                after,
                flags=re.IGNORECASE,
            ):
                return True
            prefix = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", line)
            if re.match(owner_pattern + r"\s*:", prefix, flags=re.IGNORECASE):
                if ACTION_EVIDENCE_CUE_RE.search(line):
                    return True
    return False


def _supported_due(due: str, context: str) -> bool:
    due = due.strip()
    if not due or due.casefold() in {"unspecified", "не указан", "не указано"}:
        return False
    if not context:
        return False
    matches = list(re.finditer(re.escape(due), context, flags=re.IGNORECASE))
    if not matches and _inflected_tokens_in_context(due, context):
        cue = DEADLINE_CUE_RE.search(context)
        matches = [cue] if cue is not None else []
    if not matches:
        return False
    for match in matches:
        nearby = context[max(0, match.start() - 120) : match.end() + 40]
        if DEADLINE_CUE_RE.search(nearby):
            return True
    return False


def _canonical_evidence(value: Any) -> str:
    match = TIMESTAMP_FLEX_RE.search(str(value or ""))
    return f"[{match.group(1)}:{match.group(2)}:{match.group(3)}]" if match else ""


def _normalized_numbers(value: str) -> set[str]:
    return {
        re.sub(r"\s+", "", match.group(0))
        .replace(",", ".")
        .replace("–", "-")
        .replace("—", "-")
        for match in NUMBER_RE.finditer(value)
    }


def _numbers_supported(value: str, context: str) -> bool:
    claimed = _normalized_numbers(value)
    if not claimed:
        return True
    return claimed <= _normalized_numbers(context)


def _is_nondecision_status(value: str) -> bool:
    if re.search(r"принят\w*\s+решени", value, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"решени\w*.{0,80}(?:не\s+принят|не\s+принима|отлож)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _content_tokens(value: str) -> set[str]:
    stop = {"решение", "решили", "поручение", "поручить", "срок"}
    return {
        token
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9-]+", value.casefold())
        if len(token) >= 4 and token not in stop
    }


def _duplicates_action(decision: dict[str, Any], actions: list[dict[str, Any]]) -> bool:
    decision_tokens = _content_tokens(str(decision.get("decision") or ""))
    if not decision_tokens:
        return False
    for action in actions:
        if action.get("evidence") != decision.get("evidence"):
            continue
        action_tokens = _content_tokens(str(action.get("task") or ""))
        if action_tokens and len(decision_tokens & action_tokens) / min(
            len(decision_tokens), len(action_tokens)
        ) >= 0.75:
            return True
    return False


def sanitize_protocol_extraction(
    extraction: dict[str, Any],
    transcript_lines: list[str],
) -> dict[str, Any]:
    """Apply deterministic evidence, identity, and deadline guardrails."""
    cleaned = copy.deepcopy(extraction)
    kept_topics: list[dict[str, Any]] = []
    for topic in cleaned.get("topics", []):
        if not isinstance(topic, dict):
            continue
        item = dict(topic)
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = [evidence]
        item["evidence"] = [
            canonical
            for raw in evidence
            if (canonical := _canonical_evidence(raw))
        ]
        contexts = [
            evidence_context(reference, transcript_lines)
            for reference in item["evidence"]
        ]
        if item["evidence"] and _numbers_supported(
            str(item.get("summary") or ""),
            "\n".join(contexts),
        ):
            kept_topics.append(item)
    cleaned["topics"] = kept_topics
    for field in ("decisions", "actions"):
        kept: list[dict[str, Any]] = []
        for raw_item in cleaned.get(field, []):
            if not isinstance(raw_item, dict):
                continue
            item = dict(raw_item)
            item["evidence"] = _canonical_evidence(item.get("evidence"))
            context = evidence_context(str(item.get("evidence") or ""), transcript_lines)
            content_value = str(
                item.get("decision")
                if field == "decisions"
                else item.get("task") or ""
            )
            if not item["evidence"] or not _numbers_supported(content_value, context):
                continue
            owner = str(item.get("owner") or "")
            if not _supported_owner(owner, context):
                item["owner"] = "unspecified"
            if field == "decisions" and not DECISION_CUE_RE.search(context):
                continue
            if field == "actions":
                due = str(item.get("due") or "")
                if not _supported_due(due, context):
                    item["due"] = "unspecified"
            kept.append(item)
        cleaned[field] = kept
    actions = [
        item for item in cleaned.get("actions", []) if isinstance(item, dict)
    ]
    cleaned["decisions"] = [
        item
        for item in cleaned.get("decisions", [])
        if not _is_nondecision_status(str(item.get("decision") or ""))
        and not _duplicates_action(item, actions)
    ]
    for field in ("risks", "open_questions"):
        for item in cleaned.get(field, []):
            if isinstance(item, dict):
                item["evidence"] = _canonical_evidence(item.get("evidence"))
    return cleaned