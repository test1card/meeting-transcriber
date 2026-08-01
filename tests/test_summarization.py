from meeting_transcriber.summarization import (
    PROTOCOL_EXTRACTION_SYSTEM,
    PROTOCOL_SYNTHESIS_SYSTEM,
    clean_markdown_response,
    combine_extractions,
    parse_json_response,
)


def test_protocol_prompt_uses_human_secretary_profile() -> None:
    assert "load-bearing content" in PROTOCOL_EXTRACTION_SYSTEM
    assert "audibility checks" in PROTOCOL_EXTRACTION_SYSTEM
    assert "ПОВЕСТКА СОВЕЩАНИЯ" in PROTOCOL_SYNTHESIS_SYSTEM
    assert "ОБСУДИЛИ" in PROTOCOL_SYNTHESIS_SYSTEM
    assert "РЕШИЛИ" in PROTOCOL_SYNTHESIS_SYSTEM
    assert "Do not invent names" in PROTOCOL_SYNTHESIS_SYSTEM


def test_parse_json_response_accepts_fenced_json() -> None:
    assert parse_json_response('```json\n{"overview":"ok"}\n```') == {"overview": "ok"}


def test_clean_markdown_response_removes_outer_fence() -> None:
    assert clean_markdown_response("```markdown\n# Minutes\n\nText\n```") == (
        "# Minutes\n\nText\n"
    )


def test_combine_extractions_keeps_supported_items() -> None:
    combined = combine_extractions(
        [
            {
                "overview": "First",
                "topics": [{"topic": "A"}],
                "decisions": [],
                "actions": [{"task": "Ship"}],
                "risks": [],
                "open_questions": [],
            },
            {
                "overview": "Second",
                "topics": [{"topic": "B"}],
                "decisions": [{"decision": "Yes"}],
                "actions": [],
                "risks": [{"risk": "Delay"}],
                "open_questions": [{"question": "When?"}],
            },
        ]
    )
    assert combined["overview"] == ["First", "Second"]
    assert len(combined["topics"]) == 2
    assert combined["actions"] == [{"task": "Ship"}]
    assert combined["decisions"] == [{"decision": "Yes"}]
