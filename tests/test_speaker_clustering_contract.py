from pathlib import Path


def test_speechbrain_model_files_are_copied_instead_of_symlinked() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "cluster_moss_speakers.py"
    ).read_text(encoding="utf-8")

    assert "from speechbrain.utils.fetching import LocalStrategy" in source
    assert "local_strategy=LocalStrategy.COPY" in source
