from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SUPPORT_WEIGHTS = {
    "supported": 1.0,
    "partial": 0.5,
    "unsupported": 0.0,
    "unclear": 0.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score a completed blinded human summary-review pack."
    )
    parser.add_argument("review", type=Path)
    parser.add_argument("--key", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def harmonic_mean(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def is_specific(value: Any) -> bool:
    return str(value or "").strip().casefold() not in {
        "",
        "unspecified",
        "unknown",
        "не указано",
        "не определен",
        "не определено",
    }


def score_section(
    candidates: list[dict[str, Any]], gold: list[dict[str, Any]]
) -> dict[str, Any]:
    reviewed = [
        item
        for item in candidates
        if str(item.get("review", {}).get("support", "")).casefold()
        in SUPPORT_WEIGHTS
    ]
    weights = [
        SUPPORT_WEIGHTS[str(item["review"]["support"]).casefold()]
        for item in reviewed
    ]
    precision = sum(weights) / max(1, len(reviewed))
    gold_ids = {
        str(item.get("id", "")).strip()
        for item in gold
        if str(item.get("id", "")).strip()
    }
    matched: dict[str, float] = {}
    for item, weight in zip(reviewed, weights):
        gold_id = str(item["review"].get("matched_gold_id", "")).strip()
        if gold_id in gold_ids:
            matched[gold_id] = max(matched.get(gold_id, 0.0), weight)
    recall = (
        sum(matched.values()) / len(gold_ids)
        if gold_ids
        else None
    )
    unsupported = sum(
        str(item["review"]["support"]).casefold() == "unsupported"
        for item in reviewed
    )
    unclear = sum(
        str(item["review"]["support"]).casefold() == "unclear"
        for item in reviewed
    )
    return {
        "candidate_items": len(candidates),
        "reviewed_items": len(reviewed),
        "review_completion": round(len(reviewed) / max(1, len(candidates)), 5),
        "gold_items": len(gold_ids),
        "claim_precision": round(precision, 5),
        "gold_recall": round(recall, 5) if recall is not None else None,
        "f1": round(harmonic_mean(precision, recall), 5) if recall is not None else None,
        "unsupported_claim_rate": round(unsupported / max(1, len(reviewed)), 5),
        "unclear_claim_rate": round(unclear / max(1, len(reviewed)), 5),
    }


def field_accuracy(
    candidates: list[dict[str, Any]], field: str, review_field: str
) -> dict[str, Any]:
    claims = [
        item
        for item in candidates
        if is_specific(item.get(field))
        and isinstance(item.get("review", {}).get(review_field), bool)
    ]
    correct = sum(bool(item["review"][review_field]) for item in claims)
    return {
        "reviewed_specific_claims": len(claims),
        "accuracy": round(correct / max(1, len(claims)), 5) if claims else None,
    }


def validate_completed(pack: dict[str, Any]) -> None:
    errors: list[str] = []
    gold_ids: dict[str, set[str]] = {}
    for section in ("decisions", "actions"):
        ids = [
            str(item.get("id", "")).strip()
            for item in pack.get("gold", {}).get(section, [])
        ]
        if not ids or any(not value for value in ids):
            errors.append(f"gold.{section} must contain non-empty IDs")
        if len(ids) != len(set(ids)):
            errors.append(f"gold.{section} IDs must be unique")
        gold_ids[section] = set(ids)
    for blind_id, sections in pack.get("systems", {}).items():
        for section, candidates in sections.items():
            for item in candidates:
                item_id = item.get("id", f"{blind_id}:{section}")
                support = str(item.get("review", {}).get("support", "")).casefold()
                if support not in SUPPORT_WEIGHTS:
                    errors.append(f"{item_id} has not been reviewed")
                    continue
                if section in gold_ids and SUPPORT_WEIGHTS[support] > 0:
                    match = str(
                        item.get("review", {}).get("matched_gold_id", "")
                    ).strip()
                    if match not in gold_ids[section]:
                        errors.append(
                            f"{item_id} needs a valid matched_gold_id for {section}"
                        )
    if errors:
        preview = "; ".join(errors[:8])
        suffix = f"; plus {len(errors) - 8} more" if len(errors) > 8 else ""
        raise ValueError(f"Incomplete human review: {preview}{suffix}")


def score_pack(pack: dict[str, Any], key: dict[str, str] | None = None) -> dict:
    results: dict[str, Any] = {}
    blind_key = key or {}
    for blind_id, sections in pack.get("systems", {}).items():
        decisions = score_section(
            sections.get("decisions", []), pack.get("gold", {}).get("decisions", [])
        )
        actions = score_section(
            sections.get("actions", []), pack.get("gold", {}).get("actions", [])
        )
        results[blind_id] = {
            "system": blind_key.get(blind_id, blind_id),
            "decisions": decisions,
            "actions": actions,
            "risks": score_section(sections.get("risks", []), []),
            "open_questions": score_section(
                sections.get("open_questions", []), []
            ),
            "owner_claims": field_accuracy(
                [*sections.get("decisions", []), *sections.get("actions", [])],
                "owner",
                "owner_correct",
            ),
            "deadline_claims": field_accuracy(
                sections.get("actions", []), "due", "due_correct"
            ),
            "decision_action_macro_f1": round(
                (float(decisions["f1"]) + float(actions["f1"])) / 2, 5
            ),
        }
    return {"systems": results}


def markdown(report: dict[str, Any]) -> str:
    rows = [
        "| System | Decision P/R/F1 | Action P/R/F1 | Owner accuracy | "
        "Deadline accuracy | Review complete |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in report["systems"].values():
        decision, action = result["decisions"], result["actions"]
        owner, due = result["owner_claims"], result["deadline_claims"]
        completion = min(
            decision["review_completion"], action["review_completion"]
        )
        rows.append(
            f'| {result["system"]} | '
            f'{decision["claim_precision"]:.1%} / {decision["gold_recall"]:.1%} / '
            f'{decision["f1"]:.1%} | '
            f'{action["claim_precision"]:.1%} / {action["gold_recall"]:.1%} / '
            f'{action["f1"]:.1%} | '
            f'{owner["accuracy"] if owner["accuracy"] is not None else "n/a"} | '
            f'{due["accuracy"] if due["accuracy"] is not None else "n/a"} | '
            f"{completion:.1%} |"
        )
    return (
        "# Human summary correctness\n\n"
        + "\n".join(rows)
        + "\n\nPrecision measures supported candidate claims; recall measures coverage "
        "of an independently authored gold list. Partial support receives 0.5. "
        "Runtime and cost are intentionally not folded into these correctness scores.\n"
    )


def main() -> int:
    args = parse_args()
    pack = json.loads(args.review.read_text(encoding="utf-8"))
    try:
        validate_completed(pack)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    key = None
    if args.key:
        key = json.loads(args.key.read_text(encoding="utf-8")).get(
            "blind_system_key", {}
        )
    report = score_pack(pack, key)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary-review-scores.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "summary-review-scores.md").write_text(
        markdown(report), encoding="utf-8"
    )
    print(f"Scored summary review in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
