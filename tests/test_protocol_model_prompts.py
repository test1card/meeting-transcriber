from meeting_transcriber.protocol_model_prompts import protocol_model_suffix


def test_production_protocol_prompts_are_model_specific() -> None:
    variants = {
        model: protocol_model_suffix(
            provider="deepseek" if model.startswith("deepseek") else "ollama",
            model=model,
            stage="synthesis",
        )
        for model in (
            "deepseek-v4-flash",
            "gemma4:12b",
            "gemma4:26b",
            "gemma4:31b",
            "gemma4:e4b",
        )
    }
    assert len(set(variants.values())) == len(variants)
    assert "human-secretary compression" in variants["deepseek-v4-flash"]
    assert "detailed base instruction" in variants["gemma4:12b"]
    assert "numbers and units" in variants["gemma4:26b"]
    assert "Compress aggressively" in variants["gemma4:31b"]
    assert "limited recall" in variants["gemma4:e4b"]


def test_local_owner_and_deadline_guards_are_explicit() -> None:
    for model in ("gemma4:12b", "gemma4:26b", "gemma4:31b", "gemma4:e4b"):
        suffix = protocol_model_suffix(
            provider="ollama",
            model=model,
            stage="extract",
        )
        assert "Speaker labels are never" in suffix
        assert "deadline" in suffix or "due date" in suffix
