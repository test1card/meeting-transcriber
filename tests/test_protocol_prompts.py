from __future__ import annotations

from meeting_transcriber.protocol_model_prompts import protocol_model_suffix
from meeting_transcriber.summarization import (
    PROTOCOL_EXTRACTION_SYSTEM,
    PROTOCOL_SYNTHESIS_SYSTEM,
)


def test_production_prompts_do_not_contain_development_meeting_facts() -> None:
    suffixes = [
        protocol_model_suffix(provider="deepseek", model="deepseek-v4-flash", stage=stage)
        for stage in ("extract", "synthesis")
    ]
    for model in ("gemma4:e4b", "gemma4:12b", "gemma4:26b", "gemma4:31b"):
        suffixes.extend(
            protocol_model_suffix(provider="ollama", model=model, stage=stage)
            for stage in ("extract", "synthesis")
        )
    text = "\n".join(
        [PROTOCOL_EXTRACTION_SYSTEM, PROTOCOL_SYNTHESIS_SYSTEM, *suffixes]
    ).casefold()
    banned = (
        "пущино",
        "троицк",
        "росатом",
        "роскосмос",
        "17 августа",
        "фундамент",
        "капремонт",
        "реконструкц",
        "электросет",
        "дгу",
    )
    assert not [token for token in banned if token in text]


def test_universal_prompt_defines_general_contrasts() -> None:
    text = PROTOCOL_EXTRACTION_SYSTEM.casefold()
    assert "one self-contained verifiable fact" in text
    assert "date for a meeting or event is not a task deadline" in text
    assert "mentioning a person is not assigning them" in text
    assert "do not force a predefined industry or topic list" in text