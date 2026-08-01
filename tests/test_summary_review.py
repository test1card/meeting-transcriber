import pytest

from scripts.score_summary_review import (
    field_accuracy,
    score_section,
    validate_completed,
)


def item(support, gold_id="", **fields):
    return {
        **fields,
        "review": {
            "support": support,
            "matched_gold_id": gold_id,
            "owner_correct": fields.pop("owner_correct", None),
        },
    }


def test_claim_precision_recall_and_partial_credit():
    candidates = [
        item("supported", "D01"),
        item("partial", "D02"),
        item("unsupported"),
    ]
    gold = [{"id": "D01"}, {"id": "D02"}, {"id": "D03"}]
    result = score_section(candidates, gold)
    assert result["claim_precision"] == 0.5
    assert result["gold_recall"] == 0.5
    assert result["f1"] == 0.5
    assert result["unsupported_claim_rate"] == pytest.approx(1 / 3, abs=1e-5)


def test_duplicate_match_does_not_inflate_recall():
    candidates = [
        item("supported", "D01"),
        item("supported", "D01"),
    ]
    result = score_section(candidates, [{"id": "D01"}, {"id": "D02"}])
    assert result["claim_precision"] == 1.0
    assert result["gold_recall"] == 0.5


def test_field_accuracy_only_scores_specific_reviewed_claims():
    candidates = [
        {"owner": "Иван", "review": {"owner_correct": True}},
        {"owner": "Петр", "review": {"owner_correct": False}},
        {"owner": "unspecified", "review": {"owner_correct": True}},
    ]
    result = field_accuracy(candidates, "owner", "owner_correct")
    assert result["reviewed_specific_claims"] == 2
    assert result["accuracy"] == 0.5


def test_section_without_gold_reports_precision_only():
    result = score_section([item("supported")], [])
    assert result["claim_precision"] == 1.0
    assert result["gold_recall"] is None
    assert result["f1"] is None


def test_incomplete_pack_is_rejected():
    pack = {
        "gold": {"decisions": [], "actions": []},
        "systems": {
            "A": {
                "decisions": [item("")],
                "actions": [],
                "risks": [],
                "open_questions": [],
            }
        },
    }
    with pytest.raises(ValueError, match="Incomplete human review"):
        validate_completed(pack)
