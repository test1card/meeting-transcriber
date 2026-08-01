from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run.ps1"
SIDECAR = ROOT / "meeting_transcriber" / "sidecar.py"
RUST = ROOT / "apps" / "desktop" / "src-tauri" / "src" / "lib.rs"


def test_windows_sidecar_protocol_forces_utf8(tmp_path: Path) -> None:
    job_dir = tmp_path / "russian-job"
    job_dir.mkdir()
    status = {"state": "FAILED", "message": "Русский путь и сообщение"}
    (job_dir / "status.json").write_text(
        json.dumps(status, ensure_ascii=False), encoding="utf-8"
    )
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp1252"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "meeting_transcriber.sidecar",
            "status",
            "--job-dir",
            str(job_dir),
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert json.loads(completed.stdout.decode("utf-8")) == status


def test_windows_to_wsl_paths_use_ascii_base64_transport() -> None:
    source = RUNNER.read_text(encoding="utf-8-sig")
    assert "ConvertTo-Base64Utf8" in source
    assert "ConvertTo-BashDecodedUtf8" in source
    assert "$wslScript" in source
    assert "|base64 -d|bash" in source
    assert "$inputWsl" not in source
    assert "$outputWsl" not in source
    assert 'printf %s "$1"' not in source
    assert "shift 3" not in source


@pytest.mark.skipif(os.name != "nt", reason="Windows/WSL Unicode contract")
def test_russian_path_round_trips_through_wsl(tmp_path: Path) -> None:
    target = tmp_path / "русская запись.mp4"
    target.write_bytes(b"probe")
    encoded = base64.b64encode(str(target).encode("utf-8")).decode("ascii")
    script = tmp_path / "probe.ps1"
    script.write_text(
        "$probe = 'p=$(printf %s \"$1\" | base64 -d); "
        "w=$(wslpath -a \"$p\"); test -f \"$w\"'\n"
        f"& wsl.exe -d Ubuntu-22.04 -- bash -lc $probe probe '{encoded}'\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8-sig",
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows/WSL Unicode contract")
def test_full_run_ps1_bridge_accepts_russian_paths_without_transcribing(
    tmp_path: Path,
) -> None:
    runtime = subprocess.run(
        [
            "wsl.exe", "-d", "Ubuntu-22.04", "--", "test", "-x",
            "/opt/meeting-documents/venv/bin/python",
        ],
        check=False,
        timeout=20,
    )
    if runtime.returncode != 0:
        pytest.skip("Meeting Documents WSL runtime is not installed")
    recording = tmp_path / "russian-recording.mp4"
    recording.write_bytes(b"bridge probe")
    output = tmp_path / "russian-output"
    completed = subprocess.run(
        [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(RUNNER), str(recording), "-OutputDirectory", str(output),
            "-Language", "ru", "-NoDiarization", "-NoSummary", "-BridgeProbe",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr.decode(
        "utf-8", errors="replace"
    )
    assert not (output / "transcript.json").exists()


def test_desktop_forces_utf8_and_syncs_runtime_before_launch() -> None:
    source = RUST.read_text(encoding="utf-8")
    assert '.env("PYTHONIOENCODING", "utf-8")' in source
    assert '.env("PYTHONUTF8", "1")' in source
    assert source.count("sync_runtime_source(&paths)?;") >= 2
    sync_start = source.index("fn sync_runtime_source")
    sync_end = source.index("fn workstation_paths", sync_start)
    assert "vendor/MOSS-Transcribe-Diarize" not in source[sync_start:sync_end]
    assert "def _configure_protocol_streams" in SIDECAR.read_text(encoding="utf-8")
