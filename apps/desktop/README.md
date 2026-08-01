# Meeting Documents desktop app

A Tauri 2 + React/TypeScript Windows application for nontechnical office staff.
The user selects or drops one meeting recording, chooses local or API text
processing, and receives four DOCX files.

## Clerk workflow

1. Select or drop an MP4, M4A, MP3, WAV, MOV, MKV, AAC, FLAC, OGG, or WebM.
2. Choose **На этом компьютере** or **DeepSeek API**.
3. Select the text model from the visible model list.
4. Leave speaker detection on Automatic or enter the known speaker count.
5. Choose the output folder and press **Создать документы**.
6. Follow real stage/chunk progress.
7. Open any Word document or its folder from the completion screen.

The maximum accepted recording duration is five hours. A longer file is rejected
before GPU work begins, with a plain-language request to split it.

## Privacy modes
The header **Справка** button explains the workflow and the differences between
the four documents. **Диагностика** reports media, GPU, speech-model, Ollama, and
DeepSeek readiness in office language. When local mode is selected, the app can
start Ollama before refreshing the installed-model list. The original recording
name remains visible when an interrupted job is restored after an app restart.


### Local

- WhisperX, MOSS, ECAPA, and Qwen run locally.
- Consensus, minutes, editorial cleanup, and condensation use the selected
  installed Ollama model.
- No external model request is made.

### DeepSeek API

- All audio/video and speaker processing remains local.
- Only transcript text is sent to the selected DeepSeek model.
- The first use requires explicit consent.
- The API key remains in the Windows environment or `.env`; it is never sent to
  React, written into job files, prompts, logs, or documents.

## Durable job layout

Each recording creates its own timestamped directory:

```text
<output root>/<recording>-<timestamp>/
├── job.json
├── status.json
├── events.jsonl
├── checkpoints/
├── stages/
├── documents/
├── logs/
└── _audit/
```

`job.json` is immutable provenance. `status.json` is the current materialized
state. `events.jsonl` is the append-only history. Heavy MOSS and Qwen stages keep
chunk checkpoints. Cleanup and condensation keep batch checkpoints.

Cancel requests stop the current subprocess tree and preserve completed work.
The **Продолжить** action resumes from existing checkpoints. A process lock
allows only one GPU job on the workstation at a time.

## Development

Prerequisites:

- configured repository environments from `setup.ps1`;
- Node.js;
- current Rust toolchain;
- Microsoft WebView2;
- Tauri platform prerequisites.

Commands:

```powershell
cd C:\path\to\meeting-transcriber\apps\desktop
npm install
npm run build
cargo check --manifest-path .\src-tauri\Cargo.toml
npm run tauri dev
```

The frontend production build is written to `dist`. The Rust target directory is
`src-tauri/target`.

## Release build

```powershell
cd C:\path\to\meeting-transcriber\apps\desktop
npm run tauri:build:full
```

Outputs:

```text
src-tauri\target\release\meeting-documents.exe
src-tauri\target\release\bundle\nsis\Документы встречи_<version>_x64-setup.exe
```

The current installer is an unsigned workstation build. Sign the executable and
installer with the organization's Windows code-signing certificate before broad
distribution to colleagues.

The full installer embeds the application runtime and first-run workstation
wizard, but not multi-gigabyte model weights. The wizard can install/check
FFmpeg, uv, Ollama, WSL2 with Ubuntu 22.04, isolated Python environments, CUDA
speech runtimes, and the models selected by the user. Enabling WSL can require
one Windows restart; progress is saved and setup resumes after sign-in.

## Resource-based recommendations

Recommendations do not depend on GPU product names. The displayed name is
diagnostic only. Classification uses the largest individual CUDA GPU's VRAM,
system RAM, free disk, GPU count, portable/desktop/workstation form factor, and
the reported sustained power limit when available. VRAM from several GPUs is
not added together for one model. The current scheduler runs one GPU-heavy
stage at a time.

| Resource tier | Minimum RAM | Recommended RAM | Minimum free disk | Local text ceiling |
|---|---:|---:|---:|---|
| No CUDA GPU | 16 GB | 32 GB | 20 GB | API client only |
| 6–8 GB VRAM | 32 GB | 48 GB | 40 GB | Compact/experimental |
| 10–12 GB VRAM | 32 GB | 64 GB | 45 GB | E4B class |
| 13–19 GB VRAM | 48 GB | 64 GB | 55 GB | 12B class |
| 20–31 GB VRAM | 64 GB | 96 GB | 70 GB | 26B class |
| 32–47 GB VRAM | 64 GB | 128 GB | 90 GB | 26B with large context |
| 48–79 GB VRAM | 96 GB | 192 GB | 120 GB | Future large local models |
| 80+ GB VRAM | 128 GB | 256 GB | 160 GB | Server-grade/future maximum |

Portable systems retain a portable flag and power-limit telemetry so the UI can
warn about sustained load and operation from mains power. Resource-rich and
multi-GPU systems are classified as workstations; a multi-job server scheduler
is not yet included.

The versioned source of truth is `installer/model-catalog.json`. It records the
catalog date, resource policy, deployment classes, model revisions, install
sizes, and production status. Local electricity cost is intentionally excluded.

## First-run behavior

1. Open **Diagnostics** and choose **Models and installation**.
2. Review the detected resource tier and recommended packs.
3. Choose an API or fully local text-processing profile.
4. Start setup. It is idempotent and writes progress to
   `%LOCALAPPDATA%\MeetingDocuments\setup-state.json`.
5. Restart Windows if requested, then reopen the application.

Runtime files are installed under
`%LOCALAPPDATA%\MeetingDocuments\runtime`. `MEETING_TRANSCRIBER_ROOT` and
`MEETING_TRANSCRIBER_PYTHON` remain available as development overrides.

## Verification

From the repository root:

```powershell
python -m pytest -q
$env:PYTHONPATH = (Get-Location).Path
.\.venv-docs\Scripts\python.exe .\tests\document_smoke.py
```

From `apps/desktop`:

```powershell
npm run build
cargo check --manifest-path .\src-tauri\Cargo.toml
npm run test:ui
```


`test:ui` opens the frontend in installed Chrome with mocked Tauri job states and
verifies ready, processing, failed, complete, Help, Diagnostics, and the
resource/model setup wizard, including local/API switching.

The interface is designed for 100%, 125%, and 150% Windows scaling, light/dark
themes, keyboard focus, and reduced-motion preferences.

## Security boundary

The React renderer has no generic shell or filesystem command. Narrow Rust
commands perform job launch/status/cancel/resume and validate that opened files
remain under the selected job's `documents` or `logs` directory. The Tauri
configuration loads no remote UI code, uses a restrictive CSP, and grants only
the native open-dialog permission.
