from __future__ import annotations

import json
from pathlib import Path


CASES_PATH = Path(__file__).parent / "fixtures" / "protocol_generalization_cases.json"


def test_generalization_cases_are_valid_and_meeting_agnostic() -> None:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len(cases) >= 8
    assert len({case["id"] for case in cases}) == len(cases)
    text = CASES_PATH.read_text(encoding="utf-8").casefold()
    for token in ("пущино", "росатом", "роскосмос", "кубик", "дгу"):
        assert token not in text


def test_metamorphic_pair_changes_entities_but_not_structure() -> None:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    pair = [case for case in cases if case.get("pair") == "entity_swap"]
    assert len(pair) == 2
    assert pair[0]["expected"]["action_count"] == pair[1]["expected"]["action_count"]
    assert pair[0]["expected"]["decision_count"] == pair[1]["expected"]["decision_count"]
