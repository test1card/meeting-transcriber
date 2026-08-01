from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from meeting_transcriber.summarization import LocalChatClient, parse_json_response


PROMPT_VERSION = "editorial-cleanup-v2"
WORD_RE = re.compile(
    r"[0-9A-Za-z\u0400-\u04FF]+(?:[-'][0-9A-Za-z\u0400-\u04FF]+)*"
)
CLEANUP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
            },
        }
    },
    "required": ["items"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a readable, non-verbatim transcript with an LLM."
    )
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--provider",
        choices=["ollama", "openai", "vllm", "deepseek"],
        default="deepseek",
    )
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--batch-chars", type=int, default=12_000)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-retries", type=int, default=4)
    return parser.parse_args()


def words(text: str) -> list[str]:
    return [match.group(0) for match in WORD_RE.finditer(text)]


def timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def load_segments(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    segments = transcript.get("segments", [])
    if not isinstance(segments, list) or not segments:
        raise ValueError("Transcript contains no segments")
    return payload, segments


def make_units(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"T{index:05d}",
            "start": float(segment.get("start", 0)),
            "end": float(segment.get("end", segment.get("start", 0))),
            "speaker": str(segment.get("speaker") or "Speaker"),
            "text": re.sub(r"\s+", " ", str(segment.get("text", ""))).strip(),
        }
        for index, segment in enumerate(segments, start=1)
        if str(segment.get("text", "")).strip()
    ]


def batches(units: list[dict[str, Any]], max_chars: int) -> list[list[dict[str, Any]]]:
    result: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for unit in units:
        unit_size = len(json.dumps(unit, ensure_ascii=False)) + 2
        if current and size + unit_size > max_chars:
            result.append(current)
            current, size = [], 0
        current.append(unit)
        size += unit_size
    if current:
        result.append(current)
    return result


def system_prompt() -> str:
    return (
        "You are a decisive Russian-language transcript editor. This is an "
        "EDITED READABLE TRANSCRIPT, not a summary and not a verbatim record. "
        "Return JSON only. For every input item, preserve its id and return exactly "
        "one cleaned text item. Convert meandering oral speech into concise written "
        "Russian while retaining all substantive content. Aggressively remove "
        "content-free fillers and verbal tics such as utterance-initial or redundant "
        "\"ну\", \"вот\", \"значит\", \"как бы\", \"так сказать\", "
        "\"собственно\", \"короче\", \"в принципе\", repeated \"да\", "
        "stutters, immediate repetitions, abandoned starts, self-corrections that "
        "leave the final version clear, and clauses that merely repeat the preceding "
        "clause. Do not leave a filler just because the sentence remains grammatical. "
        "Example: \"Ну, вот, значит, мы, как бы, решили\" becomes \"Мы решили\". "
        "Remove greetings, microphone checks, empty acknowledgements, jokes, and "
        "administrative chatter when they add no meeting substance; return an empty "
        "string for those items. Keep yes/no and short acknowledgements only when "
        "they establish agreement, refusal, or a decision. Improve punctuation and "
        "repair obvious grammatical fragments only when intent is unambiguous. "
        "Preserve every substantive claim, reason, qualification, negation, "
        "uncertainty, disagreement, proposal, decision, action, name, organization, "
        "number, unit, date, filename, identifier, and English technical term. "
        "Never invent facts, resolve ambiguity, or silently correct an uncertain "
        "name/number from outside the supplied text. Never merge speakers. Never "
        "change timestamps or speaker identities. Do not make speech more certain "
        "than it was. Preserve substantive examples and explanations even while "
        "tightening their wording. "
        'Required JSON example: {"items":[{"id":"T00001","text":"Очищенный текст."}]}. '
        "No Markdown and no text outside the single JSON object."
    )


def validate_response(
    raw: str, expected: list[dict[str, Any]]
) -> list[dict[str, str]]:
    parsed = parse_json_response(raw)
    values = parsed.get("items")
    if not isinstance(values, list):
        raise ValueError("Response has no items array")
    expected_ids = [unit["id"] for unit in expected]
    by_id: dict[str, str] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        item_id = str(value.get("id", ""))
        if item_id not in expected_ids or item_id in by_id:
            continue
        by_id[item_id] = re.sub(r"\s+", " ", str(value.get("text", ""))).strip()
    missing = [item_id for item_id in expected_ids if item_id not in by_id]
    if missing:
        raise ValueError(f"Response omitted IDs: {', '.join(missing[:8])}")
    return [{"id": item_id, "text": by_id[item_id]} for item_id in expected_ids]


def cleanup_messages(
    batch: list[dict[str, Any]], *, index: int, total: int
) -> list[dict[str, str]]:
    request = json.dumps({"items": batch}, ensure_ascii=False)
    return [
        {"role": "system", "content": system_prompt()},
        {
            "role": "user",
            "content": (
                f"Clean transcript batch {index}/{total}. Adjacent items are in "
                f"chronological order and provide context.\nJSON input:\n{request}"
            ),
        },
    ]


def clean_batch(
    client: LocalChatClient,
    batch: list[dict[str, Any]],
    *,
    index: int,
    total: int,
    max_retries: int,
) -> list[dict[str, str]]:
    messages = cleanup_messages(batch, index=index, total=total)
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            raw = client.chat(messages, schema=CLEANUP_SCHEMA)
            return validate_response(raw, batch)
        except Exception as error:
            last_error = error
            if attempt == max_retries:
                break
            time.sleep(min(2**attempt, 20))
    assert last_error is not None
    raise last_error


def checkpoint_fingerprint(
    model: str, batch: list[dict[str, Any]]
) -> str:
    encoded = json.dumps(
        {"version": PROMPT_VERSION, "model": model, "batch": batch},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    args = parse_args()
    api_key = os.environ.get(
        "DEEPSEEK_API_KEY" if args.provider == "deepseek" else "LLM_API_KEY"
    )
    if args.provider == "deepseek" and not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")
    input_path = args.transcript.expanduser().resolve()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    checkpoints = output / "checkpoints"
    checkpoints.mkdir(exist_ok=True)
    prompts = output / "prompts"
    prompts.mkdir(exist_ok=True)
    payload, segments = load_segments(input_path)
    units = make_units(segments)
    if args.limit:
        units = units[: args.limit]
    grouped = batches(units, args.batch_chars)
    write_json(output / "progress.json", {"status": "running", "completed": 0, "total_chunks": len(grouped)})
    client = LocalChatClient(
        provider=args.provider,
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        timeout_seconds=600,
    )
    started = time.perf_counter()
    cleaned: dict[str, str] = {}
    reused = 0
    usage_totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
    }
    try:
        for index, batch in enumerate(grouped, start=1):
            checkpoint = checkpoints / f"batch-{index:03d}.json"
            fingerprint = checkpoint_fingerprint(args.model, batch)
            write_json(
                prompts / f"batch-{index:03d}.json",
                {
                    "provider": args.provider,
                    "model": args.model,
                    "prompt_version": PROMPT_VERSION,
                    "batch_index": index,
                    "batch_total": len(grouped),
                    "fingerprint": fingerprint,
                    "messages": cleanup_messages(
                        batch, index=index, total=len(grouped)
                    ),
                },
            )
            result: list[dict[str, str]] | None = None
            usage: dict[str, int] = {}
            if checkpoint.is_file():
                cached = json.loads(checkpoint.read_text(encoding="utf-8"))
                if cached.get("fingerprint") == fingerprint:
                    result = cached.get("items")
                    usage = cached.get("usage", {})
                    reused += 1
            if result is None:
                print(
                    f"Cleanup batch {index}/{len(grouped)}: {args.provider}",
                    flush=True,
                )
                before = {
                    "prompt_tokens": client.prompt_tokens,
                    "completion_tokens": client.completion_tokens,
                    "prompt_cache_hit_tokens": client.prompt_cache_hit_tokens,
                    "prompt_cache_miss_tokens": client.prompt_cache_miss_tokens,
                }
                result = clean_batch(
                    client,
                    batch,
                    index=index,
                    total=len(grouped),
                    max_retries=args.max_retries,
                )
                usage = {
                    key: int(getattr(client, key)) - value
                    for key, value in before.items()
                }
                write_json(
                    checkpoint,
                    {
                        "fingerprint": fingerprint,
                        "usage": usage,
                        "items": result,
                    },
                )
            else:
                print(
                    f"Cleanup batch {index}/{len(grouped)}: checkpoint reused",
                    flush=True,
                )
            for item in result:
                cleaned[item["id"]] = item["text"]
            for key in usage_totals:
                usage_totals[key] += int(usage.get(key, 0))
            write_json(output / "progress.json", {"status": "running", "completed": index, "total_chunks": len(grouped)})
    finally:
        client.close()
    write_json(output / "progress.json", {"status": "complete", "completed": len(grouped), "total_chunks": len(grouped)})

    output_segments: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for unit in units:
        cleaned_text = cleaned[unit["id"]]
        original_text = unit["text"]
        output_segments.append(
            {
                "start": unit["start"],
                "end": unit["end"],
                "speaker": unit["speaker"],
                "text": cleaned_text,
            }
        )
        if cleaned_text != original_text:
            audit.append(
                {
                    "id": unit["id"],
                    "start": unit["start"],
                    "end": unit["end"],
                    "speaker": unit["speaker"],
                    "original": original_text,
                    "cleaned": cleaned_text,
                }
            )
    original_words = sum(len(words(unit["text"])) for unit in units)
    cleaned_words = sum(len(words(segment["text"])) for segment in output_segments)
    elapsed = time.perf_counter() - started
    miss_tokens = usage_totals["prompt_cache_miss_tokens"]
    hit_tokens = usage_totals["prompt_cache_hit_tokens"]
    output_tokens = usage_totals["completion_tokens"]
    cost = miss_tokens / 1_000_000 * 0.14
    cost += hit_tokens / 1_000_000 * 0.0028
    cost += output_tokens / 1_000_000 * 0.28
    if args.provider != "deepseek":
        cost = 0.0
    metadata = {
        "kind": "editorial_non_verbatim_transcript",
        "source": str(input_path),
        "provider": args.provider,
        "model": args.model,
        "prompt_version": PROMPT_VERSION,
        "segments": len(output_segments),
        "changed_segments": len(audit),
        "empty_segments": sum(not segment["text"] for segment in output_segments),
        "original_words": original_words,
        "cleaned_words": cleaned_words,
        "word_reduction_fraction": round(
            (original_words - cleaned_words) / max(1, original_words), 5
        ),
        "elapsed_seconds": round(elapsed, 3),
        "checkpoint_batches": len(grouped),
        "checkpoint_batches_reused": reused,
        "prompt_tokens": usage_totals["prompt_tokens"],
        "completion_tokens": output_tokens,
        "prompt_cache_hit_tokens": hit_tokens,
        "prompt_cache_miss_tokens": miss_tokens,
        "api_cost_usd": round(cost, 6),
        "warning": (
            "Editorial, non-verbatim derivative. Use the full transcript and audio "
            "for evidentiary verification."
        ),
    }
    result_payload = {
        "metadata": metadata,
        "transcript": {"language": "ru", "segments": output_segments},
    }
    write_json(output / "transcript-cleaned.json", result_payload)
    write_json(output / "cleanup-audit.json", {"metadata": metadata, "changes": audit})
    lines = [
        "# Редакционная стенограмма",
        "",
        "> Не дословная версия. Удалены речевой мусор, повторы и ложные старты. "
        "Для проверки фактов используйте полную стенограмму и аудиозапись.",
        "",
    ]
    for segment in output_segments:
        if segment["text"]:
            lines.append(
                f'[{timestamp(segment["start"])}] '
                f'{segment["speaker"]}: {segment["text"]}'
            )
    (output / "transcript-cleaned.md").write_text(
        "\n\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
