from meeting_transcriber.formatting import chunk_lines, merge_segments, timestamp


def test_timestamp_formats_hours_and_milliseconds() -> None:
    assert timestamp(3661.25) == "01:01:01"
    assert timestamp(3661.25, milliseconds=True) == "01:01:01,250"


def test_merge_segments_uses_friendly_speaker_names() -> None:
    segments = [
        {"start": 0, "end": 1, "speaker": "SPEAKER_07", "text": "Hello"},
        {"start": 1.2, "end": 2, "speaker": "SPEAKER_07", "text": "again."},
        {"start": 2.1, "end": 3, "speaker": "SPEAKER_02", "text": "Hi."},
    ]
    merged = merge_segments(segments)
    assert merged == [
        {"start": 0.0, "end": 2.0, "speaker": "Speaker 1", "text": "Hello again."},
        {"start": 2.1, "end": 3.0, "speaker": "Speaker 2", "text": "Hi."},
    ]


def test_chunk_lines_preserves_every_line() -> None:
    lines = ["a" * 6, "b" * 6, "c" * 6]
    assert chunk_lines(lines, max_chars=14) == ["a" * 6 + "\n" + "b" * 6, "c" * 6]

