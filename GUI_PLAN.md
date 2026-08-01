# Clerk GUI plan

## Status

The first workstation MVP was implemented on 30 July 2026 under
`apps/desktop`. It includes the Ready, Processing, Needs attention, and Complete
screens; native file/folder dialogs; local/API selection; durable status polling;
safe cancellation/resume; and the four-DOCX result contract. The remaining
phases cover deployment hardening and clerk validation.

## Objective

Create a polished Windows desktop application that allows an office clerk to
drop or select an audio/video recording and receive four clearly named DOCX files without
using PowerShell, WSL, model CLIs, JSON, or Markdown.

The application should behave like an office conversion utility, not a machine
learning control panel.

## Default user journey

1. Launch `Meeting Documents`.
2. Drop one supported recording or click `Choose recording`.
3. Choose a processing mode:
   - Recommended: local audio processing plus DeepSeek text processing.
   - Private: all processing local.
4. Leave speaker detection on Automatic or optionally provide a minimum/maximum.
5. Choose an output folder.
6. Click `Create documents`.
7. Watch real stage progress and estimated remaining time.
8. Open any of the four Word files or open the output folder.

Supported inputs include MP4, M4A, MP3, WAV, MOV, MKV, AAC, FLAC, OGG, and
WebM. The workstation accepts recordings up to five hours; longer recordings
must be split before processing.

## Four clerk-facing deliverables

Use stable names inside each job's `documents` directory:

1. `01_Протокол_совещания.docx`
2. `02_Полная_стенограмма.docx`
3. `03_Редакционная_стенограмма.docx`
4. `04_Сокращенная_смысловая_стенограмма.docx`

The model-comparison report is not a default per-meeting clerk deliverable. Put
technical reports, JSON, prompts, checkpoints, and logs under `_audit`.

## Processing profiles

### Recommended

- Audio remains local.
- Run the required local STT/speaker stages.
- Use MOSS/ECAPA as the speaker and timestamp anchor.
- Use independent WhisperX and Qwen readings.
- Send transcript text to DeepSeek V4 Flash for adjudication and document text.
- Generate all four DOCX files.

This is the current practical default. It is provisional until human-reference
WER/CER/cpWER/DER/JER and minutes precision/recall are available.

### Private local

- No external API calls.
- Use local STT and MOSS/ECAPA speaker processing.
- Use the configured Ollama model for minutes and editorial derivatives.
- Show a clear warning that local document quality may differ from the validated
  DeepSeek workflow.

The first GUI version may mark this profile Experimental until the same cleanup
and condensation prompts have been tested with the selected local model.

### Quick draft

- Optimize for preliminary reading rather than the required final workflow.
- It may use fewer independent STT readings.
- If speaker identification is absent, label the output Draft and do not present
  it as a final meeting transcript.

### Maximum review

- Run the full Recommended pipeline.
- Produce an additional review queue for low-confidence speech, names, numbers,
  and speaker transitions.
- Keep this profile in the Advanced view.

## Main window

The initial window should contain:

```text
┌─────────────────────────────────────────────────────────┐
│ Meeting Documents                                       │
│                                                         │
│      Drop a recording here or choose a file             │
│                                                         │
│ Mode: Recommended / Private                             │
│ Speakers: Automatic                                     │
│ Output folder: Documents                                │
│                                                         │
│                 Create documents                        │
├─────────────────────────────────────────────────────────┤
│ ✓ Audio prepared                                        │
│ ● Speaker identification                 6 / 8 chunks    │
│ ○ Transcript comparison                                 │
│ ○ Word documents                                        │
│                                                         │
│ Overall progress: 63%                                   │
│ Estimated remaining time: approximately 29 minutes      │
│                                                         │
│ Cancel safely                              Show details  │
└─────────────────────────────────────────────────────────┘
```

After completion, replace the Start area with:

- Open meeting minutes
- Open full transcript
- Open readable transcript
- Open shortened transcript
- Open output folder

## Visual and interaction direction

The application must feel like a finished modern office product, not a themed
Python utility. Visual quality is a product requirement.

Use:

- Tauri 2 for the lightweight Windows desktop shell;
- React and TypeScript for the interface;
- Tailwind CSS for design tokens and layout;
- shadcn/ui and its accessible Radix primitives for consistent controls;
- Motion for React for restrained transitions and progress feedback;
- Lucide icons with text labels, never unexplained icons alone.

The design language should be calm, spacious, and trustworthy:

- one clear primary action on each screen;
- generous spacing, rounded but not playful surfaces, and restrained shadows;
- neutral backgrounds with one deliberate accent color;
- excellent Cyrillic typography using a bundled or dependable system font;
- dark and light themes, following Windows by default;
- visible keyboard focus, full keyboard operation, and adequate contrast;
- motion used to explain state changes, with reduced-motion support;
- no fake terminal, dense model dashboard, neon AI styling, or decorative clutter.

Design the workflow as four coherent states:

1. **Ready** — a prominent drag-and-drop surface, simple mode choice, and output
   location.
2. **Processing** — a stage timeline, real progress, elapsed/remaining time, and
   a quiet expandable details panel.
3. **Needs attention** — a plain-language explanation with one recommended
   recovery action and access to details.
4. **Complete** — four document cards with descriptions, completion state,
   `Open`, and `Show in folder` actions.

The completed screen should make the differences between the four documents
obvious without exposing pipeline terminology. A compact recording summary may
show duration, detected speaker count, processing mode, elapsed time, and whether
cloud text processing was used.

Create a small visual design system before building screens:

- color, typography, spacing, radius, elevation, and motion tokens;
- reusable recording picker, stage row, status badge, document card, consent
  dialog, empty state, and error panel;
- representative mockups at 100%, 125%, and 150% Windows display scaling;
- Russian UI copy tested with long file names and long error messages.

Beauty must not conceal state. Progress, cloud use, failures, and whether an
output is verbatim or edited must remain explicit.

## Cloud consent

Before the first Recommended run, display:

> The audio recording remains on this computer. Transcript text will be sent to
> DeepSeek for comparison, cleanup, and document creation.

Allow `Remember this choice`. Do not show or request the API key in the normal
clerk workflow. System status should show only `DeepSeek configured: Yes/No`.

## Architecture

Use a Tauri 2 desktop shell with a React/TypeScript front end over the
job-oriented Python orchestration layer. The existing Python transcription and
document pipeline remains the source of truth and is packaged as a sidecar
worker; it is not rewritten in Rust or TypeScript.

```text
React + TypeScript UI
    |
    v
Tauri 2 shell
    |
    v
Python sidecar
    │
    ▼
JobController / event reader
    │
    ▼
meeting_transcriber.pipeline
    ├── validation/audio preparation
    ├── WhisperX
    ├── MOSS chunked transcription/diarization
    ├── ECAPA global speaker clustering
    ├── Qwen checkpointed transcription
    ├── consensus provider
    ├── minutes provider
    ├── editorial cleanup provider
    ├── semantic condensation provider
    └── DOCX builder
```

The React application renders state only. It must not contain pipeline business
logic or construct shell commands. Narrow Tauri commands provide file selection,
job start/cancel/resume, document opening, and system-status operations.

Tauri launches a packaged Python worker for each job. Prefer JSON Lines over
standard input/output for live commands and events, backed by the durable
`job.json`, `status.json`, and `events.jsonl` files. If loopback HTTP is later
needed, it must use a per-launch secret and bind only to localhost.

Neither the Tauri shell nor the React renderer imports GPU model runtimes.
Heavy stages remain isolated subprocesses so failures, CUDA cleanup,
cancellation, and restarts do not take down the interface. Never infer progress
by parsing human-oriented console prose.

The desktop shell must use a restrictive content security policy, load no remote
UI code, expose no generic command execution to React, and emit no telemetry by
default. API secrets stay in the existing environment/credential layer and are
never sent to the renderer.

## Proposed package layout
```text
apps/
└── desktop/
    ├── package.json
    ├── src/
    │   ├── app/
    │   ├── components/
    │   ├── features/
    │   │   ├── recording/
    │   │   ├── processing/
    │   │   ├── results/
    │   │   └── settings/
    │   ├── lib/
    │   └── styles/
    ├── src-tauri/
    │   ├── capabilities/
    │   ├── src/
    │   └── tauri.conf.json
    └── tests/
```

```text
meeting_transcriber/
├── pipeline.py
├── jobs.py
├── events.py
├── stages/
│   ├── base.py
│   ├── audio.py
│   ├── whisperx.py
│   ├── moss.py
│   ├── qwen.py
│   ├── speakers.py
│   ├── consensus.py
│   ├── documents.py
│   └── evaluation.py
├── providers/
│   ├── base.py
│   ├── deepseek.py
│   └── ollama.py
└── sidecar.py
```

Do not move all existing code at once. Add adapters around the current scripts,
then migrate shared logic only where duplication becomes harmful.

## Job directory contract

```text
outputs/
└── <safe-recording-name>-<timestamp>/
    ├── job.json
    ├── status.json
    ├── events.jsonl
    ├── checkpoints/
    │   ├── moss/
    │   ├── qwen/
    │   ├── consensus/
    │   ├── cleanup/
    │   └── condensation/
    ├── documents/
    ├── logs/
    └── _audit/
        ├── transcripts/
        ├── prompts/
        ├── metrics/
        └── reports/
```

A job ID must not depend on an English-only filename. Preserve the original input
path in `job.json`; use a sanitized name only for the directory.

## State machine

```text
QUEUED
  → VALIDATING
  → PREPARING_AUDIO
  → TRANSCRIBING_MOSS
  → CLUSTERING_SPEAKERS
  → TRANSCRIBING_WHISPERX
  → TRANSCRIBING_QWEN
  → ADJUDICATING
  → CREATING_MINUTES
  → CLEANING_TRANSCRIPT
  → CONDENSING_TRANSCRIPT
  → BUILDING_DOCX
  → COMPLETE
```

Every running state may transition to `FAILED`, `CANCELLING`, or `CANCELLED`.
On restart, a recoverable job transitions to `RESUMABLE`.

## Progress reporting

Progress must be based on work units:

- MOSS: completed chunks / total chunks.
- Qwen: completed chunks / total chunks.
- Consensus: completed batches / total batches.
- Minutes: extraction chunks plus final synthesis.
- Cleanup and condensation: completed batches / total batches.
- DOCX: completed files / four.

Use measured stage history for ETA. Initial estimates may use the benchmark run:

- WhisperX: 209.756 seconds.
- MOSS: 3119.101 seconds.
- Qwen: 425.287 seconds.
- DeepSeek consensus: 519.006 seconds.
- DeepSeek minutes: 47.68 seconds.
- Editorial cleanup v2: 111.628 seconds.
- Semantic condensation: 75.406 seconds.

Never advance progress from a timer alone.

## Error behavior

Normal UI errors should state:

- what stopped;
- whether work was saved;
- the recommended clerk action;
- a Retry or Resume button.

Example:

> Speaker identification stopped during part 6 of 8. Five completed parts were
> saved. Press Retry to continue.

Put the exception and traceback in the job log, accessible through `Show details`.

## System check

Run at startup and on demand:

- input file readable and supported;
- FFmpeg/ffprobe available;
- WSL2 distribution available;
- NVIDIA GPU and CUDA visible;
- sufficient VRAM and disk space;
- required model caches present;
- Ollama available for local mode;
- DeepSeek key configured for cloud mode;
- Python environments available;
- DOCX generator available.

A missing optional provider should disable only its profile, not the entire app.

## Implementation phases

### Phase 0 — Freeze contracts

- Define `job.json`, `status.json`, and event schemas.
- Define the four document contracts and warnings.
- Define stage inputs, outputs, exit codes, and resume behavior.

### Phase 1 — Job-scoped orchestration

- Create `pipeline.py`.
- Wrap existing scripts as explicit stages.
- Remove benchmark-directory assumptions from production paths.
- Add structured progress events.
- Prove resume/cancel without a GUI.

### Phase 2 — Generic DOCX generation

- Parameterize the current DOCX builder with a job directory.
- Generate the four stable filenames.
- Enforce `[HH:MM:SS]` timestamp formatting.
- Omit empty transcript shells.
- Preserve warnings and provenance.

### Phase 3 — Provider abstraction

- Introduce DeepSeek and Ollama provider interfaces.
- Centralize retry, JSON validation, token accounting, and prompt logging.
- Guarantee that local mode cannot accidentally call the network.

### Phase 4 — Tauri/React desktop MVP

- Establish the visual tokens and reusable components before assembling screens.
- Add narrow Tauri commands and Python sidecar event transport.
- Implement Ready, Processing, Needs attention, and Complete states.
- Implement file picker and drag-and-drop.
- Implement Recommended and Private profiles.
- Run one job through the controller.
- Show real stage progress, safe cancellation, and completion buttons.

### Phase 5 — Resume, queue, and support

- Discover unfinished jobs at startup.
- Resume from checkpoints.
- Add a serial multi-recording queue.
- Add support-bundle export without secrets.

### Phase 6 — Deployment

- Package the React assets, Tauri shell, and standalone Python sidecar as one
  Windows application.
- Produce a normal signed Windows installer; office users must not install
  Node.js, Rust, Python, or frontend dependencies.
- Detect or bootstrap the Microsoft WebView2 runtime when necessary.
- Keep the developer build toolchain out of the clerk-facing installation.
- Do not bundle model weights into the GUI executable.
- Add first-run system checks and environment repair guidance.
- Consider an installer only after the workstation deployment is stable.

### Phase 7 — Clerk pilot

- Test with users who have never used the command line.
- Record where they hesitate or misinterpret privacy/progress.
- Simplify labels and defaults before adding advanced settings.

## Acceptance criteria for the first usable release

- A clerk can process a Cyrillic-named MP4 without opening a terminal.
- Recommended mode creates all four DOCX files.
- Private mode performs no external request.
- Speaker labels are present in all transcript documents.
- Timestamps display as `[HH:MM:SS]`, with no raw floats.
- Edited documents are clearly marked non-verbatim.
- The interface remains legible and usable at 100%, 125%, and 150% Windows
  scaling.
- All primary actions are keyboard accessible and reduced-motion preferences are
  respected.
- DeepSeek consent is explicit and remembered only when requested.
- Closing and reopening the app can resume an interrupted checkpointed job.
- Cancel preserves completed checkpoints.
- No API secret appears in logs, prompts, documents, or support bundles.
- Errors are actionable for a nontechnical user.

## Non-goals for the MVP

- Multi-user server or shared web deployment.
- Editing the transcript inside the GUI.
- Automatic identification of real employee names from voiceprints.
- Parallel GPU jobs on the same RTX 5070 Ti.
- Electricity-cost calculation.
- A composite quality score without human ground truth.

## Decisions to confirm before implementation

1. Whether the clerk-facing application and DOCX headings should be Russian-only
   or support Russian/English UI localization.
2. Whether the default output folder is beside the recording or under Documents.
3. Whether Recommended mode consent is per run or remembered per Windows user.
4. Which Ollama model becomes the supported Private-mode default.
5. Whether the first release supports one recording at a time or exposes a queue.
6. Whether Word files should open automatically or only through completion buttons.
7. Which approved product name, accent color, and organization mark should seed
   the visual design system; use a neutral unbranded system until these are
   supplied.
