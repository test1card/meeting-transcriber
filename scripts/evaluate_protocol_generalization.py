from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from meeting_transcriber.cli import PROJECT_ROOT
from meeting_transcriber.formatting import safe_slug, write_json
from meeting_transcriber.protocol_guardrails import sanitize_protocol_extraction
from meeting_transcriber.summarization import LocalChatClient, _extract_chunk


CASES_PATH = PROJECT_ROOT / "tests" / "fixtures" / "protocol_generalization_cases.json"


def _normalize(value: Any) -> str:
    return " ".join(str(value).casefold().replace("ё", "е").split())


def _normalize_due(value: Any) -> str:
    text = _normalize(value)
    for prefix in ("не позднее ", "до ", "к "):
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _owner_matches(actual: Any, expected: Any) -> bool:
    left_tokens = _normalize(actual).split()
    right_tokens = _normalize(expected).split()
    if len(left_tokens) != len(right_tokens):
        return False
    for left, right in zip(left_tokens, right_tokens):
        if left == right:
            continue
        if len(left) < 5 or len(right) < 5 or left[:5] != right[:5]:
            return False
    return True


def _contains_value(serialized: str, value: Any) -> bool:
    target = _normalize(value)
    if target and all(char.isdigit() or char in ".,–-" for char in target):
        import re

        return bool(
            re.search(
                rf"(?<![\d.,]){re.escape(target)}(?![\d.,])", serialized
            )
        )
    return target in serialized


class RecordingClient(LocalChatClient):
    def __init__(self, *, audit_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.audit_dir = audit_dir
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.case_id = "unknown"
        self.request_index = 0

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        schema: dict[str, Any] | None = None,
    ) -> str:
        started = time.perf_counter()
        response = super().chat(messages, schema=schema)
        self.request_index += 1
        write_json(
            self.audit_dir / f"{self.request_index:03d}-{self.case_id}.json",
            {
                "provider": self.provider,
                "model": self.model,
                "messages": messages,
                "schema": schema,
                "response": response,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
            },
        )
        return response


def _evidence_is_valid(extraction: dict[str, Any], transcript: list[str]) -> bool:
    timestamps = {
        line.split("]", 1)[0] + "]"
        for line in transcript
        if line.startswith("[") and "]" in line
    }
    values: list[str] = []
    for topic in extraction.get("topics", []):
        values.extend(str(item) for item in topic.get("evidence", []))
    for field in ("decisions", "actions", "risks", "open_questions"):
        values.extend(str(item.get("evidence", "")) for item in extraction.get(field, []))
    return bool(values) and all(value in timestamps for value in values)


def _score_case(case: dict[str, Any], extraction: dict[str, Any]) -> dict[str, Any]:
    expected = case["expected"]
    decisions = extraction.get("decisions", [])
    actions = extraction.get("actions", [])
    serialized = _normalize(json.dumps(extraction, ensure_ascii=False))
    checks: dict[str, bool] = {
        "decision_count": len(decisions) == expected["decision_count"],
        "action_count": len(actions) == expected["action_count"],
        "evidence_valid": _evidence_is_valid(extraction, case["transcript"]),
    }
    decision_text = _normalize(
        " ".join(str(item.get("decision", "")) for item in decisions)
    )
    for index, term in enumerate(expected.get("decision_terms", []), start=1):
        checks[f"decision_term_{index}"] = _normalize(term) in decision_text

    for index, target in enumerate(expected.get("actions", []), start=1):
        best = max(
            actions,
            key=lambda action: sum(
                _normalize(term) in _normalize(action.get("task", ""))
                for term in target["terms"]
            ),
            default={},
        )
        task_text = _normalize(best.get("task", ""))
        checks[f"action_{index}_terms"] = all(
            _normalize(term) in task_text for term in target["terms"]
        )
        checks[f"action_{index}_owner"] = _owner_matches(
            best.get("owner", ""), target["owner"]
        )
        checks[f"action_{index}_due"] = _owner_matches(
            _normalize_due(best.get("due", "")),
            _normalize_due(target["due"]),
        )

    owners = {_normalize(item.get("owner", "")) for item in actions}
    dues = {_normalize_due(item.get("due", "")) for item in actions}
    for index, value in enumerate(expected.get("forbidden_owner", []), start=1):
        checks[f"forbidden_owner_{index}"] = _normalize(value) not in owners
    for index, value in enumerate(expected.get("forbidden_due", []), start=1):
        checks[f"forbidden_due_{index}"] = _normalize_due(value) not in dues
    for index, value in enumerate(expected.get("required_values", []), start=1):
        checks[f"required_value_{index}"] = _contains_value(serialized, value)
    for index, value in enumerate(expected.get("forbidden_values", []), start=1):
        checks[f"forbidden_value_{index}"] = not _contains_value(serialized, value)

    passed = sum(checks.values())
    return {
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "score": round(passed / len(checks), 6),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["ollama", "deepseek"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--prompt-tag", default="universal-v1")
    return parser


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = build_parser().parse_args()
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    run_dir = args.output.resolve() / safe_slug(args.model) / args.prompt_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.provider == "deepseek":
        import os

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")
        base_url = args.base_url or "https://api.deepseek.com"
    else:
        api_key = None
        base_url = args.base_url or "http://127.0.0.1:11434"

    client = RecordingClient(
        audit_dir=run_dir / "_audit" / "prompts",
        provider=args.provider,
        base_url=base_url,
        model=args.model,
        api_key=api_key,
    )
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    try:
        for index, case in enumerate(payload["cases"], start=1):
            client.case_id = case["id"]
            transcript = case["transcript"]
            try:
                raw = _extract_chunk(
                    client,
                    "\n".join(transcript),
                    chunk_index=index,
                    chunk_total=len(payload["cases"]),
                    summary_language="Russian",
                )
                extraction = sanitize_protocol_extraction(raw, transcript)
                score = _score_case(case, extraction)
                results.append(
                    {
                        "id": case["id"],
                        "extraction": extraction,
                        **score,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "id": case["id"],
                        "error": f"{type(exc).__name__}: {exc}",
                        "checks": {},
                        "passed": 0,
                        "total": 1,
                        "score": 0.0,
                    }
                )
    finally:
        client.close()

    passed = sum(item["passed"] for item in results)
    total = sum(item["total"] for item in results)
    report = {
        "provider": args.provider,
        "model": args.model,
        "prompt_tag": args.prompt_tag,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "prompt_tokens": client.prompt_tokens,
        "completion_tokens": client.completion_tokens,
        "passed": passed,
        "total": total,
        "score": round(passed / total, 6),
        "cases": results,
    }
    write_json(run_dir / "result.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if all("error" not in item for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
