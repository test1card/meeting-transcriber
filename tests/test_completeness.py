import pytest
from meeting_transcriber.completeness import union_intervals, uncovered_intervals, normalize_words, owned_word


def test_overlapping_speakers_are_not_double_counted():
    assert union_intervals([(0, 2), (1, 3), (3, 4)]) == [[0, 4]]


def test_missing_speech_including_tail_and_nested_transcripts():
    assert uncovered_intervals([(0, 10)], [(1, 3), (2, 4), (6, 8)]) == [[0, 1], [4, 6], [8, 10]]


def test_no_transcript_and_no_speech():
    assert uncovered_intervals([(1, 2)], []) == [[1, 2]]
    assert uncovered_intervals([], [(1, 2)]) == []


def test_invalid_interval():
    with pytest.raises(ValueError):
        union_intervals([(1, float('nan'))])


def test_normalization_preserves_word_repetition():
    assert normalize_words('Да, да. Ёлка 2025!') == ['да', 'да', 'елка', '2025']


def test_overlapping_windows_own_boundary_word_once():
    word = {'timestamp': [4.9, 5.1], 'text': 'да'}
    assert owned_word(word, 15, 0, 20) is None
    assert owned_word(word, 15, 20, 40) == {'start': 19.9, 'end': 20.1, 'text': 'да'}
    assert owned_word({'timestamp': [None, 2], 'text': 'да'}, 0, 0, 20) is None
