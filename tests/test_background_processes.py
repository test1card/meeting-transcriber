from __future__ import annotations

import os
from pathlib import Path

import pytest

from meeting_transcriber import sidecar


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="Windows process flags")
def test_worker_is_hidden_without_detached_process() -> None:
    flags = sidecar._background_creation_flags()
    assert flags & sidecar.subprocess.CREATE_NO_WINDOW
    assert flags & sidecar.subprocess.CREATE_NEW_PROCESS_GROUP
    assert not flags & sidecar.subprocess.DETACHED_PROCESS


def test_tauri_sidecar_poll_is_hidden() -> None:
    source = (ROOT / "apps" / "desktop" / "src-tauri" / "src" / "lib.rs").read_text(
        encoding="utf-8"
    )
    start = source.index("fn sidecar_json")
    end = source.index("#[tauri::command", start)
    function = source[start:end]
    assert "command.creation_flags(0x08000000);" in function

def test_elevated_setup_process_is_hidden() -> None:
    source = (ROOT / "installer" / "Install-Workstation.ps1").read_text(
        encoding="utf-8"
    )
    start = source.index("function Start-ElevatedCopy")
    end = source.index("$modelResults", start)
    function = source[start:end]
    assert "-Verb RunAs `\n        -WindowStyle Hidden `" in function