from scripts.score_speakers import cpwer, score_model


def turn(speaker, start, end, text=""):
    return {"speaker": speaker, "start": start, "end": end, "text": text}


def test_permutation_invariant_perfect_score():
    refs = [
        turn("Alice", 0.0, 5.0, "один два"),
        turn("Bob", 5.0, 10.0, "три четыре"),
    ]
    segments = [
        turn("SPEAKER_02", 0.0, 5.0, "один два"),
        turn("SPEAKER_01", 5.0, 10.0, "три четыре"),
    ]
    result = score_model(segments, refs, [(0.0, 10.0)])
    assert result["diarization_error_rate"] == 0.0
    assert result["jaccard_error_rate"] == 0.0
    assert result["speaker_attribution_accuracy"] == 1.0
    assert result["speaker_attributed_asr"]["cpwer"] == 0.0


def test_missed_speech_counts_toward_der():
    refs = [turn("Alice", 0.0, 10.0, "один два")]
    segments = [turn("SPEAKER_01", 0.0, 5.0, "один")]
    result = score_model(segments, refs, [(0.0, 10.0)])
    assert result["missed_speech_seconds"] == 5.0
    assert result["diarization_error_rate"] == 0.5
    assert result["speaker_attribution_accuracy"] == 0.5


def test_overlap_is_scored_in_speaker_seconds():
    refs = [
        turn("Alice", 0.0, 10.0, "один"),
        turn("Bob", 5.0, 10.0, "два"),
    ]
    segments = [
        turn("SPEAKER_01", 0.0, 10.0, "один"),
        turn("SPEAKER_02", 5.0, 10.0, "два"),
    ]
    result = score_model(segments, refs, [(0.0, 10.0)])
    assert result["reference_speech_seconds"] == 15.0
    assert result["correctly_attributed_seconds"] == 15.0
    assert result["diarization_error_rate"] == 0.0
    assert result["overlap_policy"] == "included"


def test_cpwer_penalizes_unmatched_prediction_stream():
    refs = [turn("Alice", 0.0, 1.0, "один")]
    preds = [
        turn("SPEAKER_01", 0.0, 1.0, "один"),
        turn("SPEAKER_02", 1.0, 2.0, "лишнее"),
    ]
    result = cpwer(refs, preds)
    assert result is not None
    assert result["cp_word_errors"] == 1
    assert result["cp_reference_words"] == 1
    assert result["cpwer"] == 1.0
