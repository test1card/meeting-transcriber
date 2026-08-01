# Local meeting transcriber

This pipeline transcribes a recording with WhisperX, optionally adds speaker
labels with pyannote, can adjudicate multiple STT transcripts into one audited
canonical transcript, and independently summarizes the chosen transcript with
`gemma4:e4b` and `gemma4:26b` through Ollama plus `deepseek-v4-flash` and
`deepseek-v4-pro` through the DeepSeek API.

## Installed layout

- Source: `C:\path\to\meeting-transcriber`
- Runtime: Ubuntu-22.04 under WSL2
- Python environment: `/home/fall/.venvs/meeting-transcriber`
- Windows summary environment: `.venv-win`
- Whisper model cache: `/home/fall/.cache/meeting-transcriber`
- Local LLMs: `gemma4:e4b,gemma4:26b`
- External comparison: `deepseek-v4-flash,deepseek-v4-pro`

The DeepSeek model names and endpoint follow the current official V4 API:
<https://api-docs.deepseek.com/guides/reasoning_model>.

The vLLM environment at `/home/fall/vllm-env` is not modified.
Transcription runs in WSL; summarization runs with Windows Python so it can reach
## Desktop application for clerks

The workstation now includes a Tauri 2 desktop application in `apps/desktop`.
It accepts a recording up to five hours, keeps speech processing local, requires
speaker identification, and produces four Word documents:

1. `01_Протокол_совещания.docx`
2. `02_Полная_стенограмма.docx`
3. `03_Редакционная_стенограмма.docx`
4. `04_Сокращенная_смысловая_стенограмма.docx`

The main screen makes the text-processing choice explicit:

- **На этом компьютере** uses a selected installed Ollama model and makes no
  external request.
- **DeepSeek API** keeps audio/video local and sends only transcript text after
  explicit consent.
The Help panel explains the clerk workflow and all four deliverables.
Diagnostics shows actionable workstation checks, and selecting local processing
automatically attempts to start Ollama before refreshing its model list.


Run the compiled application on this configured workstation:

```powershell
.\\apps\\desktop\\src-tauri\\target\\release\\meeting-documents.exe
```

The Windows installer is created at:

```text
apps\desktop\src-tauri\target\release\bundle\nsis\
```

The installer packages the desktop shell, setup engine, versioned model catalog,
and clean pipeline source. Office users do not need the repository or
`setup.ps1`. The graphical first-run wizard can install/check WSL2, Ubuntu
22.04, FFmpeg, uv, Ollama, isolated Python/CUDA environments, and the selected
model weights. Large weights are downloaded only after the user chooses a
profile.

Recommendations are resource based rather than GPU-name based. The catalog
evaluates the largest single-GPU VRAM, RAM, free disk, GPU count, form factor,
and reported power limit. It covers no CUDA GPU, 6–8, 10–12, 13–19, 20–31,
32–47, 48–79, and 80+ GB VRAM, plus portable, desktop, workstation, and server
deployment classes. VRAM from multiple GPUs is not summed for one model.

Build the full bootstrap installer with:

```powershell
cd apps\desktop
npm run tauri:build:full
```

For development:

```powershell
cd apps\desktop
npm install
npm run tauri dev
```

For implementation details, system checks, checkpoint behavior, and packaging
commands, see `apps/desktop/README.md`.

## One required step for speaker names

Transcription works immediately. To distinguish speakers:

1. Open <https://huggingface.co/pyannote/speaker-diarization-community-1>.
2. Sign in and accept the model conditions.
3. Create a read token at <https://huggingface.co/settings/tokens>.
4. Copy `.env.example` to `.env`.
5. Put the token after `HF_TOKEN=` in `.env`.

Do not commit or share `.env`.

## Run

From PowerShell:

```powershell
cd C:\path\to\meeting-transcriber
.\run.ps1 "C:\path\to\meeting.mp4"
```

For a known range of speakers:

```powershell
.\run.ps1 "C:\path\to\meeting.mp3" -MinSpeakers 3 -MaxSpeakers 6
```

For Russian-only recognition:

```powershell
.\run.ps1 "C:\path\to\meeting.m4a" -Language ru
```

Russian is the intended primary language. The summarizers write in Russian while
preserving occasional English technical terms, names, commands, filenames, and
identifiers in Latin spelling.

## Reconcile several STT results

Run each STT backend independently and save its result in the same
`transcript.json` shape (`transcript.segments`, each with `start`, `end`, `text`,
and optionally `speaker`). Then run:

```powershell
.\consensus.ps1 `
  -Transcripts @(
    ".\runs\moss\transcript.json",
    ".\runs\qwen\transcript.json",
    ".\runs\whisperx\transcript.json"
  ) `
  -Labels "moss,qwen,whisperx" `
  -Anchor "moss" `
  -Glossary ".\glossary.txt"
```

Use the transcript with the best diarization as `-Anchor`. Its timestamps and
speaker labels are immutable. The judge sees only time-overlapping candidate
readings and chooses the most strongly supported wording. It cannot rewrite
timestamps or speakers.

Copy `glossary.example.txt` to `glossary.txt` and add employee names, project
names, abbreviations, and English technical terms.

For confidential meetings, keep adjudication and summaries local:

```powershell
.\consensus.ps1 `
  -Transcripts @(".\moss.json", ".\qwen.json", ".\whisperx.json") `
  -Labels "moss,qwen,whisperx" `
  -Anchor "moss" `
  -JudgeModel "gemma4:26b" `
  -NoDeepSeek
```

`gemma4:26b` is the recommended local judge. The 4B model remains useful for
summary comparison but is more likely to over-correct uncertain Russian speech.

Transcribe without diarization or LLM summarization:

```powershell
.\run.ps1 "C:\path\to\meeting.wav" -NoDiarization -NoSummary
```

Re-run only the two LLMs without transcribing again:

```powershell
.\run.ps1 ".\outputs\meeting-YYYYMMDD-HHMMSS\transcript.json" -NoDiarization
```

Choose other Ollama models:

```powershell
.\run.ps1 "C:\path\to\meeting.mp4" -Models "gemma4:e4b,gemma4:31b"
```

Skip the external DeepSeek tier for a confidential meeting:

```powershell
.\run.ps1 "C:\path\to\meeting.mp4" -NoDeepSeek
```

By default the comparison sends transcript text (not the audio file) to DeepSeek.
The launcher prints a warning before this happens. The existing
`DEEPSEEK_API_KEY` Windows user environment variable is used without copying or
printing its value.

## Outputs

Each run creates a timestamped directory under `outputs`:

- `transcript.json`: canonical machine-readable result
- `transcript.md`: readable speaker-labelled transcript
- `transcript.srt`: subtitles
- `consensus-audit.json`: every STT reading, selected wording, support, and confidence
- `minutes-gemma4-e4b.md`: E4B minutes
- `minutes-gemma4-26b.md`: 26B minutes
- `minutes-deepseek-v4-flash.md`: DeepSeek V4 Flash minutes
- `minutes-deepseek-v4-pro.md`: DeepSeek V4 Pro minutes
- `extraction-*.json`: evidence-backed structured facts
- `metrics-*.json`: runtime and coverage counts
- `comparison.md`: compact comparison table
- `compare.html`: side-by-side visual comparison

The comparison counts measure coverage, not truth. Validate decisions and actions
against their timestamps in `transcript.md`.

## Use a local vLLM server

The code supports any OpenAI-compatible vLLM endpoint. Start your preferred current
model separately, then run:

```powershell
.\run.ps1 ".\outputs\meeting-...\transcript.json" `
  -Provider vllm `
  -BaseUrl "http://127.0.0.1:8000" `
  -Models "your-served-model-name"
```

## Rebuild the environment

The machine is already configured. If the environment is removed later:

```powershell
.\setup.ps1
```
