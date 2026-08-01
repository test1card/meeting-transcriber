from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .events import fail_with_message, read_json
from .jobs import JobValidationError, create_job
from .pipeline import PROJECT_ROOT, run_job


def _configure_protocol_streams() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")


def _worker_command(job_dir: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "run", "--job-dir", str(job_dir)]
    return [
        sys.executable,
        "-m",
        "meeting_transcriber.sidecar",
        "run",
        "--job-dir",
        str(job_dir),
    ]


def _background_creation_flags() -> int:
    if os.name != "nt":
        return 0
    return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def _spawn_worker(job_dir: Path) -> int:
    log = (job_dir / "logs" / "sidecar.log").open(
        "a", encoding="utf-8", errors="replace"
    )
    process = subprocess.Popen(
        _worker_command(job_dir),
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=_background_creation_flags(),
        close_fds=True,
    )
    return process.pid


def _command_exists(name: str, arguments: list[str]) -> bool:
    executable = shutil.which(name)
    if not executable:
        return False
    try:
        completed = subprocess.run(
            [executable, *arguments],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
            creationflags=_background_creation_flags(),
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _deepseek_configured() -> bool:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return True
    env_file = PROJECT_ROOT / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if stripped.startswith("DEEPSEEK_API_KEY=") and stripped.split("=", 1)[1]:
                return True
    except OSError:
        pass
    return False


def _ollama_models() -> tuple[bool, list[str]]:
    try:
        request = urllib.request.Request("http://127.0.0.1:11434/api/tags")
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.load(response)
        models = [
            str(item.get("name"))
            for item in payload.get("models", [])
            if item.get("name")
        ]
        return True, models
    except (OSError, ValueError, urllib.error.URLError):
        return False, []


def _start_ollama() -> None:
    powershell = (
        shutil.which("powershell.exe")
        or shutil.which("powershell")
        or "powershell.exe"
    )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "Start-Ollama.ps1"),
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
        creationflags=_background_creation_flags(),
    )


def system_status(*, start_ollama: bool = False) -> dict[str, Any]:
    ollama_running, models = _ollama_models()
    if start_ollama and not ollama_running:
        _start_ollama()
        ollama_running, models = _ollama_models()
    return {
        "project_root": str(PROJECT_ROOT),
        "ffmpeg": _command_exists("ffprobe", ["-version"]),
        "wsl": _command_exists("wsl.exe", ["-d", "Ubuntu-22.04", "--", "true"]),
        "nvidia": _command_exists("nvidia-smi.exe", ["-L"])
        or _command_exists("nvidia-smi", ["-L"]),
        "ollama": ollama_running,
        "ollama_installed": shutil.which("ollama.exe") is not None
        or shutil.which("ollama") is not None,
        "ollama_models": models,
        "deepseek_configured": _deepseek_configured(),
        "windows_python": (PROJECT_ROOT / ".venv-win" / "Scripts" / "python.exe").is_file(),
        "docs_python": (PROJECT_ROOT / ".venv-docs" / "Scripts" / "python.exe").is_file(),
        "moss_python": (PROJECT_ROOT / ".venv-moss" / "Scripts" / "python.exe").is_file(),
        "qwen_python": (PROJECT_ROOT / ".venv-qwen" / "Scripts" / "python.exe").is_file(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Служебный процесс приложения «Материалы встреч»")
    commands = parser.add_subparsers(dest="command", required=True)

    launch = commands.add_parser("launch")
    launch.add_argument("--input", required=True)
    launch.add_argument("--output-root", required=True)
    launch.add_argument("--mode", choices=["local", "deepseek"], required=True)
    launch.add_argument("--model", required=True)
    launch.add_argument("--speaker-count", type=int)
    launch.add_argument("--cloud-consent", action="store_true")

    run = commands.add_parser("run")
    run.add_argument("--job-dir", type=Path, required=True)

    resume = commands.add_parser("resume")
    resume.add_argument("--job-dir", type=Path, required=True)

    status = commands.add_parser("status")
    status.add_argument("--job-dir", type=Path, required=True)

    cancel = commands.add_parser("cancel")
    cancel.add_argument("--job-dir", type=Path, required=True)

    system = commands.add_parser("system-status")
    system.add_argument("--start-ollama", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_protocol_streams()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "launch":
            job_dir = create_job(
                input_path=args.input,
                output_root=args.output_root,
                mode=args.mode,
                model=args.model,
                speaker_count=args.speaker_count,
                cloud_consent=args.cloud_consent,
            )
            pid = _spawn_worker(job_dir)
            print(
                json.dumps(
                    {"job_dir": str(job_dir), "worker_pid": pid},
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "run":
            return run_job(args.job_dir)
        if args.command == "resume":
            job_dir = args.job_dir.expanduser().resolve()
            if not (job_dir / "job.json").is_file():
                raise JobValidationError("Задание не найдено.")
            (job_dir / "cancel.request").unlink(missing_ok=True)
            pid = _spawn_worker(job_dir)
            print(json.dumps({"job_dir": str(job_dir), "worker_pid": pid}))
            return 0
        if args.command == "status":
            status = read_json(args.job_dir / "status.json")
            if not isinstance(status, dict):
                raise JobValidationError("Статус задания не найден.")
            print(json.dumps(status, ensure_ascii=False))
            return 0
        if args.command == "cancel":
            job_dir = args.job_dir.expanduser().resolve()
            if not (job_dir / "job.json").is_file():
                raise JobValidationError("Задание не найдено.")
            (job_dir / "cancel.request").write_text(
                "cancel\n", encoding="ascii"
            )
            print(json.dumps({"cancel_requested": True}))
            return 0
        if args.command == "system-status":
            print(json.dumps(system_status(start_ollama=args.start_ollama), ensure_ascii=False))
            return 0
    except JobValidationError as error:
        return fail_with_message(str(error), 2)
    except Exception as error:
        return fail_with_message(str(error), 1)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
