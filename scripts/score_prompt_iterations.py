from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


TIMESTAMP = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]$")
SPEAKER = re.compile(r"\bspeaker\s*\d*\b", re.IGNORECASE)
META_TASK = re.compile(
    r"подготов\w*\s+(?:проект\s+)?протокол|командировоч|домашн\w+\s+задан",
    re.IGNORECASE,
)


def visible_strings(result: dict[str, Any]) -> list[str]:
    values = [
        result.get("title", ""),
        result.get("date", ""),
        result.get("time", ""),
        result.get("location", ""),
        *result.get("attendees", []),
        *result.get("agenda", []),
        *result.get("notes", []),
    ]
    values.extend(item.get("item", "") for item in result.get("discussed", []))
    for item in result.get("resolved", []):
        values.extend([item.get("task", ""), item.get("owner", ""), item.get("due", "")])
    return [str(value) for value in values]


def latin_word_fraction(strings: list[str]) -> float:
    words = re.findall(r"[A-Za-zА-Яа-яЁё]+", " ".join(strings))
    if not words:
        return 0.0
    latin = sum(bool(re.fullmatch(r"[A-Za-z]+", word)) for word in words)
    return round(latin / len(words), 5)


def exact_evidence_fraction(result: dict[str, Any]) -> float:
    evidence = [
        str(item.get("evidence", ""))
        for group in ("discussed", "resolved")
        for item in result.get(group, [])
    ]
    if not evidence:
        return 0.0
    return round(sum(bool(TIMESTAMP.fullmatch(value)) for value in evidence) / len(evidence), 5)


def score_run(metrics: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    strings = visible_strings(result)
    discussed = result.get("discussed", [])
    resolved = result.get("resolved", [])
    speaker_hits = sum(len(SPEAKER.findall(value)) for value in strings)
    owner_specific = sum(
        str(item.get("owner", "")).strip().lower() not in {"", "unspecified"}
        for item in resolved
    )
    due_specific = sum(
        str(item.get("due", "")).strip().lower() not in {"", "unspecified"}
        for item in resolved
    )
    meta_task_hits = sum(bool(META_TASK.search(str(item.get("task", "")))) for item in resolved)
    exact_evidence = exact_evidence_fraction(result)
    latin_fraction = latin_word_fraction(strings)
    content_score = (
        0.30 * metrics["human_similarity_score"]
        + 0.25 * metrics["transcript_grounded_score"]
        + 0.15 * metrics["numeric_fidelity_on_matched_items"]
        + 0.10 * metrics["discussed_vs_human"]["f1"]
        + 0.05 * metrics["resolved_vs_human"]["f1"]
        + 0.05 * metrics["valid_evidence_fraction"]
        + 0.10 * metrics["human_style_score"]
    )
    hard_gate = (
        speaker_hits == 0
        and not result.get("attendees")
        and owner_specific == 0
        and due_specific == 0
        and meta_task_hits == 0
        and latin_fraction <= 0.08
        and 8 <= len(discussed) <= 16
        and 1 <= len(resolved) <= 4
        and exact_evidence >= 0.80
    )
    return {
        "model": metrics["model"],
        "profile": metrics["profile"],
        "content_score": round(content_score, 5),
        "raw_hard_gate_pass": hard_gate,
        "human": metrics["human_similarity_score"],
        "grounded": metrics["transcript_grounded_score"],
        "numbers": metrics["numeric_fidelity_on_matched_items"],
        "discuss_f1": metrics["discussed_vs_human"]["f1"],
        "resolve_f1": metrics["resolved_vs_human"]["f1"],
        "style": metrics["human_style_score"],
        "seconds": metrics["elapsed_seconds"],
        "discussed_count": len(discussed),
        "resolved_count": len(resolved),
        "attendee_count": len(result.get("attendees", [])),
        "speaker_hits": speaker_hits,
        "specific_owner_count": owner_specific,
        "specific_due_count": due_specific,
        "meta_task_count": meta_task_hits,
        "notes_count": len(result.get("notes", [])),
        "latin_word_fraction": latin_fraction,
        "exact_evidence_fraction": exact_evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evaluation_root", type=Path)
    args = parser.parse_args()
    root = args.evaluation_root.resolve()
    rows: list[dict[str, Any]] = []
    for metrics_path in sorted((root / "runs").glob("*/*/metrics.json")):
        result_path = metrics_path.with_name("result.json")
        if not result_path.is_file():
            continue
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        rows.append(score_run(metrics, result))
    rows.sort(key=lambda row: (row["model"], -row["content_score"], row["profile"]))
    (root / "iteration-scorecard.json").write_text(
        json.dumps({"criteria_version": 1, "runs": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    headers = [
        "Model", "Profile", "Content", "Gate", "Human", "Grounded", "Numbers",
        "Discuss", "Resolve", "D/R", "Speaker", "Owner", "Due", "Meta", "Evidence", "Time",
    ]
    lines = [
        "# Iterative prompt scorecard",
        "",
        "Content score is a screening score; manual reading decides the winner.",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join([
            row["model"], row["profile"], f"{row['content_score']:.3f}",
            "PASS" if row["raw_hard_gate_pass"] else "FAIL",
            f"{row['human']:.3f}", f"{row['grounded']:.3f}", f"{row['numbers']:.3f}",
            f"{row['discuss_f1']:.3f}", f"{row['resolve_f1']:.3f}",
            f"{row['discussed_count']}/{row['resolved_count']}",
            str(row["speaker_hits"]), str(row["specific_owner_count"]),
            str(row["specific_due_count"]), str(row["meta_task_count"]),
            f"{row['exact_evidence_fraction']:.2f}", f"{row['seconds']:.1f}s",
        ]) + " |")
    (root / "iteration-scorecard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
