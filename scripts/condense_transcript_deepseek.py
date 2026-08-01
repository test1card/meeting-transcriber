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


PROMPT_VERSION = "semantic-condensation-v1"
WORD_RE = re.compile(
    r"[0-9A-Za-z\u0400-\u04FF]+(?:[-'][0-9A-Za-z\u0400-\u04FF]+)*"
)
SCHEMA: dict[str, Any] = {
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
        description="Create a shortened semantic transcript with an LLM."
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
    parser.add_argument("--max-retries", type=int, default=4)
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def load_segments(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    transcript = payload.get("transcript", payload)
    segments = transcript.get("segments", [])
    if not isinstance(segments, list) or not segments:
        raise ValueError("Transcript contains no segments")
    return [
        {
            "start": float(segment.get("start", 0)),
            "end": float(segment.get("end", segment.get("start", 0))),
            "speaker": str(segment.get("speaker") or "Speaker"),
            "text": re.sub(r"\s+", " ", str(segment.get("text", ""))).strip(),
        }
        for segment in segments
        if str(segment.get("text", "")).strip()
    ]


def merge_speaker_turns(
    segments: list[dict[str, Any]],
    *,
    max_gap: float = 3.0,
    max_chars: int = 1800,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for segment in segments:
        if (
            merged
            and merged[-1]["speaker"] == segment["speaker"]
            and segment["start"] - merged[-1]["end"] <= max_gap
            and len(merged[-1]["text"]) + len(segment["text"]) + 1 <= max_chars
        ):
            merged[-1]["end"] = segment["end"]
            merged[-1]["text"] += " " + segment["text"]
        else:
            merged.append(dict(segment))
    for index, turn in enumerate(merged, start=1):
        turn["id"] = f"C{index:05d}"
    return merged


def batches(turns: list[dict[str, Any]], max_chars: int) -> list[list[dict[str, Any]]]:
    result: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for turn in turns:
        turn_size = len(json.dumps(turn, ensure_ascii=False)) + 2
        if current and size + turn_size > max_chars:
            result.append(current)
            current, size = [], 0
        current.append(turn)
        size += turn_size
    if current:
        result.append(current)
    return result


def system_prompt() -> str:
    return (
        "You are producing a shortened semantic transcript of a Russian meeting. "
        "This is more compressed than an edited transcript but is NOT meeting "
        "minutes and must remain chronological and speaker-attributed. For every "
        "input ID return exactly one text item; an empty string is allowed when the "
        "entire turn is redundant or non-substantive. Remove repeated arguments, "
        "restatements, rhetorical questions already answered, filler, administrative "
        "chatter, and examples that add no new requirement or fact. Shorten long "
        "spoken explanations into direct written Russian. Across adjacent turns, do "
        "not repeat information already retained in the first clear occurrence. "
        "Preserve every unique fact, number, unit, date, name, organization, technical "
        "term, requirement, reason, qualification, uncertainty, proposal, decision, "
        "objection, disagreement, risk, and action item. Preserve negation and who "
        "said what. Do not invent, resolve ambiguity, or make proposals sound like "
        "decisions. Do not move content between IDs or speakers. When uncertain, keep "
        "the information. Return a single JSON object only. "
        'Required example: {"items":[{"id":"C00001","text":"Краткий '
        'содержательный текст."},{"id":"C00002","text":""}]}.'
    )


def messages(
    batch: list[dict[str, Any]], *, index: int, total: int
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt()},
        {
            "role": "user",
            "content": (
                f"Condense chronological speaker turns {index}/{total}. "
                "Adjacent turns provide context for removing repetition.\nJSON input:\n"
                + json.dumps({"items": batch}, ensure_ascii=False)
            ),
        },
    ]


def validate(raw: str, batch: list[dict[str, Any]]) -> list[dict[str, str]]:
    parsed = parse_json_response(raw)
    values = parsed.get("items")
    if not isinstance(values, list):
        raise ValueError("Response has no items array")
    expected = [turn["id"] for turn in batch]
    by_id: dict[str, str] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        item_id = str(value.get("id", ""))
        if item_id in expected and item_id not in by_id:
            by_id[item_id] = re.sub(
                r"\s+", " ", str(value.get("text", ""))
            ).strip()
    missing = [item_id for item_id in expected if item_id not in by_id]
    source_by_id = {turn["id"]: str(turn.get("text", "")).strip() for turn in batch}
    if missing:
        print(
            f"Model omitted {len(missing)} IDs; preserving their original text: "
            + ", ".join(missing[:8]),
            flush=True,
        )
        for item_id in missing:
            by_id[item_id] = source_by_id[item_id]
    return [
        {
            "id": item_id,
            "text": by_id[item_id],
            **({"fallback": "model_omitted_id"} if item_id in missing else {}),
        }
        for item_id in expected
    ]


def condense_batch(
    client: LocalChatClient,
    batch: list[dict[str, Any]],
    *,
    index: int,
    total: int,
    max_retries: int,
) -> list[dict[str, str]]:
    prompt = messages(batch, index=index, total=total)
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return validate(client.chat(prompt, schema=SCHEMA), batch)
        except Exception as error:
            last_error = error
            if attempt == max_retries:
                break
            time.sleep(min(2**attempt, 20))
    assert last_error is not None
    raise last_error


def fingerprint(model: str, batch: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            {"version": PROMPT_VERSION, "model": model, "batch": batch},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def main() -> int:
    args = parse_args()
    api_key = os.environ.get(
        "DEEPSEEK_API_KEY" if args.provider == "deepseek" else "LLM_API_KEY"
    )
    if args.provider == "deepseek" and not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")
    source = args.transcript.expanduser().resolve()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    checkpoints = output / "checkpoints"
    prompts = output / "prompts"
    checkpoints.mkdir(exist_ok=True)
    prompts.mkdir(exist_ok=True)
    source_segments = load_segments(source)
    turns = merge_speaker_turns(source_segments)
    grouped = batches(turns, args.batch_chars)
    write_json(output / "progress.json", {"status": "running", "completed": 0, "total_chunks": len(grouped)})
    client = LocalChatClient(
        provider=args.provider,
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        timeout_seconds=600,
    )
    started = time.perf_counter()
    condensed: dict[str, str] = {}
    fallback_ids: list[str] = []
    try:
        for index, batch in enumerate(grouped, start=1):
            fp = fingerprint(args.model, batch)
            write_json(
                prompts / f"batch-{index:03d}.json",
                {
                    "provider": args.provider,
                    "model": args.model,
                    "prompt_version": PROMPT_VERSION,
                    "batch_index": index,
                    "batch_total": len(grouped),
                    "fingerprint": fp,
                    "messages": messages(batch, index=index, total=len(grouped)),
                },
            )
            checkpoint = checkpoints / f"batch-{index:03d}.json"
            result = None
            if checkpoint.is_file():
                cached = json.loads(checkpoint.read_text(encoding="utf-8"))
                if cached.get("fingerprint") == fp:
                    result = cached.get("items")
            if result is None:
                print(
                    f"Condense batch {index}/{len(grouped)}: {args.provider}",
                    flush=True,
                )
                result = condense_batch(
                    client,
                    batch,
                    index=index,
                    total=len(grouped),
                    max_retries=args.max_retries,
                )
                write_json(checkpoint, {"fingerprint": fp, "items": result})
            for item in result:
                condensed[item["id"]] = item["text"]
                if item.get("fallback") == "model_omitted_id":
                    fallback_ids.append(item["id"])
            write_json(output / "progress.json", {"status": "running", "completed": index, "total_chunks": len(grouped)})
    finally:
        client.close()
    write_json(output / "progress.json", {"status": "complete", "completed": len(grouped), "total_chunks": len(grouped)})

    output_segments = [
        {
            "start": turn["start"],
            "end": turn["end"],
            "speaker": turn["speaker"],
            "text": condensed[turn["id"]],
            "source_turn_id": turn["id"],
        }
        for turn in turns
        if condensed[turn["id"]]
    ]
    source_words = sum(word_count(segment["text"]) for segment in source_segments)
    merged_words = sum(word_count(turn["text"]) for turn in turns)
    condensed_words = sum(word_count(segment["text"]) for segment in output_segments)
    elapsed = time.perf_counter() - started
    cost = client.prompt_cache_miss_tokens / 1_000_000 * 0.14
    cost += client.prompt_cache_hit_tokens / 1_000_000 * 0.0028
    cost += client.completion_tokens / 1_000_000 * 0.28
    if args.provider != "deepseek":
        cost = 0.0
    metadata = {
        "kind": "shortened_semantic_transcript",
        "source": str(source),
        "provider": args.provider,
        "model": args.model,
        "prompt_version": PROMPT_VERSION,
        "source_nonempty_segments": len(source_segments),
        "merged_speaker_turns": len(turns),
        "output_turns": len(output_segments),
        "source_words": source_words,
        "merged_words": merged_words,
        "output_words": condensed_words,
        "word_reduction_fraction": round(
            (source_words - condensed_words) / max(1, source_words), 5
        ),
        "elapsed_seconds": round(elapsed, 3),
        "prompt_tokens": client.prompt_tokens,
        "completion_tokens": client.completion_tokens,
        "prompt_cache_hit_tokens": client.prompt_cache_hit_tokens,
        "prompt_cache_miss_tokens": client.prompt_cache_miss_tokens,
        "api_cost_usd": round(cost, 6),
        "omitted_id_fallback_count": len(fallback_ids),
        "omitted_id_fallback_ids": fallback_ids,
        "warning": (
            "Shortened semantic derivative, not verbatim. Verify critical facts, "
            "names, numbers, decisions, and speaker attribution against the full "
            "transcript and audio."
        ),
    }
    write_json(
        output / "transcript-condensed.json",
        {
            "metadata": metadata,
            "transcript": {"language": "ru", "segments": output_segments},
        },
    )
    lines = [
        "# Сокращенная смысловая стенограмма",
        "",
        "> Не дословная версия. Повторы и несодержательные фрагменты сокращены. "
        "Критические факты проверяйте по полной стенограмме и аудио.",
        "",
    ]
    for segment in output_segments:
        lines.extend(
            [
                f'[{timestamp(segment["start"])}] '
                f'{segment["speaker"]}: {segment["text"]}',
                "",
            ]
        )
    (output / "transcript-condensed.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
