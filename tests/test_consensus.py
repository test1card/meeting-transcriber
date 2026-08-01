from pathlib import Path

from meeting_transcriber.consensus import (
    TranscriptCandidate,
    _agreed_decision,
    build_consensus_units,
)


def _candidate(label: str, segments: list[dict]) -> TranscriptCandidate:
    return TranscriptCandidate(
        label=label,
        path=Path(f"{label}.json"),
        transcript={"language": "ru", "segments": segments},
        metadata={},
    )


def test_build_units_keeps_anchor_timing_and_speaker() -> None:
    anchor = _candidate(
        "moss",
        [
            {
                "start": 0.0,
                "end": 4.0,
                "speaker": "S01",
                "text": "Запускаем Docker.",
            }
        ],
    )
    alternative = _candidate(
        "qwen",
        [{"start": 0.2, "end": 4.2, "text": "Запускаем докер."}],
    )
    selected, units = build_consensus_units(
        [anchor, alternative], anchor_label="moss"
    )
    assert selected is anchor
    assert units == [
        {
            "id": "A00001",
            "start": 0.0,
            "end": 4.0,
            "speaker": "S01",
            "readings": {
                "moss": "Запускаем Docker.",
                "qwen": "Запускаем докер.",
            },
        }
    ]


def test_exact_agreement_skips_llm() -> None:
    decision = _agreed_decision(
        {
            "id": "A00001",
            "readings": {
                "moss": "Срок — пятница.",
                "qwen": "срок пятница",
            },
        }
    )
    assert decision is not None
    assert decision["confidence"] == "high"
    assert decision["support"] == ["moss", "qwen"]


def test_different_words_require_judge() -> None:
    assert (
        _agreed_decision(
            {
                "id": "A00001",
                "readings": {
                    "moss": "не отправлять",
                    "qwen": "отправлять",
                },
            }
        )
        is None
    )
