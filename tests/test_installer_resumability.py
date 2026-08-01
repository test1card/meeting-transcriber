import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "installer" / "Workstation.Common.psm1"
INSTALLER = ROOT / "installer" / "Install-Workstation.ps1"


def _powershell(script: str) -> str:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


@pytest.mark.skipif(os.name != "nt", reason="Windows installer contract")
def test_model_marker_must_match_all_pinned_revisions(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    markers = runtime / ".installed-models"
    markers.mkdir(parents=True)
    model = {
        "id": "speech-test",
        "provider": "huggingface-wsl",
        "locator": "example/speech",
        "revision": "primary-revision",
        "additional_revisions": ["aligner-revision"],
    }
    model_path = tmp_path / "model.json"
    model_path.write_text(json.dumps(model), encoding="utf-8")
    marker_path = markers / "speech-test.json"

    def detected(marker: dict) -> bool:
        marker_path.write_text(json.dumps(marker), encoding="utf-8")
        command = (
            f"Import-Module '{MODULE}' -Force; "
            f"$model=Get-Content -Raw '{model_path}'|ConvertFrom-Json; "
            f"Test-WorkstationModelInstalled -Model $model -RuntimeRoot '{runtime}'"
        )
        return _powershell(command).lower() == "true"

    base = {
        "id": model["id"],
        "locator": model["locator"],
        "revision": model["revision"],
        "additional_revisions": model["additional_revisions"],
    }
    assert detected(base)
    assert not detected({**base, "revision": "stale"})
    assert not detected({**base, "additional_revisions": ["stale-aligner"]})


@pytest.mark.skipif(os.name != "nt", reason="Windows installer contract")
def test_ollama_detection_normalizes_latest_tag(tmp_path: Path) -> None:
    command = (
        f"Import-Module '{MODULE}' -Force; "
        "$model=[pscustomobject]@{id='local';provider='ollama';locator='gemma4:e4b'}; "
        f"Test-WorkstationModelInstalled -Model $model -RuntimeRoot '{tmp_path}' "
        "-OllamaModels @('gemma4:e4b:latest','other:latest')"
    )
    assert _powershell(command).lower() == "true"


def test_installer_aggregates_model_failures_instead_of_fail_fast() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    loop_start = source.index("for ($index = 0; $index -lt $downloadModels.Count; $index++)")
    verification = source.index('Update-State -Stage "verification"', loop_start)
    model_loop = source[loop_start:verification]
    assert "try {" in model_loop
    assert "catch {" in model_loop


def test_wsl_preload_uses_stdin_and_ollama_path_is_resolved_portably() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert "base64 -d | /opt/meeting-documents/venv/bin/python -" in source
    assert 'python_code=`$(' not in source
    assert "$ollama.FullName" not in source
    assert '@("Source", "Path", "FullName")' in source
    assert "WhisperX model preload failed: $summary" in source
    assert "[whisperx] $line" in source


def test_parallel_setup_does_not_overwrite_the_active_setup_state() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    mutex_start = source.index("$mutex = [Threading.Mutex]")
    setup_start = source.index("$needsElevation", mutex_start)
    mutex_guard = source[mutex_start:setup_start]
    assert "catch [Threading.AbandonedMutexException]" in mutex_guard
    assert "exit 3" in mutex_guard
    assert 'throw "Another workstation setup process is already running."' not in mutex_guard
