from meeting_transcriber.model_tuned_profiles import MODEL_TUNED_PROMPTS


def test_each_supported_minutes_model_has_a_distinct_tuned_prompt() -> None:
    expected = {
        "p5_deepseek_tuned",
        "p5_gemma12_tuned",
        "p5_gemma26_tuned",
        "p5_gemma31_tuned",
        "p5_e4b_tuned",
    }
    assert set(MODEL_TUNED_PROMPTS) == expected
    extracts = [profile["extract"] for profile in MODEL_TUNED_PROMPTS.values()]
    syntheses = [profile["synthesize"] for profile in MODEL_TUNED_PROMPTS.values()]
    assert len(set(extracts)) == len(extracts)
    assert len(set(syntheses)) == len(syntheses)
    assert all("deadline" in text.lower() for text in extracts)
    assert all("deadline" in text.lower() or "due" in text.lower() for text in syntheses)
