# AGENTS.md

## Project purpose

This repository turns meeting recordings into Russian-language, speaker-labelled
transcripts and colleague-ready Word documents. The primary language is Russian,
with occasional English names and technical terms that must remain in Latin
spelling when supported by the source.

Read `GUI_PLAN.md` before beginning any GUI or orchestration work.

## Current environment

- Host: Windows, PowerShell.
- Local transcription runtime: Ubuntu under WSL2.
- Hardware target: Ryzen 9 9900X, 64 GB DDR5, NVIDIA RTX 5070 Ti 16 GB.
- Local model services may include Ollama and vLLM.
- DeepSeek V4 Flash is the current external text-processing tier.
- DeepSeek receives transcript text, not meeting audio.
- Never print, copy into artifacts, or commit API keys or authorization headers.

## Product requirements

- Speaker identification is mandatory for a final meeting transcript.
- The intended clerk workflow is: select or drop a recording, choose a privacy
  mode, start one job, monitor real progress, and open four DOCX files.
- Default per-meeting deliverables:
  1. meeting minutes;
  2. full speaker-labelled transcript;
  3. readable editorial transcript;
  4. shortened semantic transcript.
- JSON, prompts, checkpoints, diagnostics, and logs belong in an `_audit`
  directory and should not clutter the default clerk view.
- Preserve complete/auditable source outputs when creating edited derivatives.
  Never replace the full transcript with a cleaned or shortened version.
- Clearly mark every non-verbatim derivative.

## Cost and hardware reporting

- Local models have marginal/API cost USD 0.
- Do not calculate or estimate electricity cost.
- Report local hardware and measured VRAM requirements separately.
- Report actual API token usage and actual provider cost when available.

## Current pipeline roles

- MOSS provides the required local speaker/timestamp backbone.
- ECAPA maps chunk-local speaker labels into recording-global anonymous clusters.
- WhisperX and Qwen provide independent STT readings.
- DeepSeek V4 Flash can adjudicate competing STT text, create minutes, clean a
  transcript, and produce a shortened semantic derivative.
- DeepSeek cannot repair speaker assignments or timing inherited from the anchor,
  and it cannot discover an error shared by all STT candidates.
- The local 26B model is postponed on this hardware unless the user explicitly
  re-enables it.

## Data and privacy rules

- A cloud-enabled run must display that transcript text will be sent externally
  while audio remains local.
- A private/local mode must not call external APIs.
- Prompt archives may contain meeting text. Treat them as confidential meeting
  artifacts even though they contain no API secret.
- Store prompt messages exactly as sent for every future DeepSeek request.
- Store provider, model, prompt version, batch number, and checkpoint fingerprint.
- Never store the API key with prompts.

## Engineering constraints

- Do not hardcode new work to
  `outputs/russian-meeting-benchmark`; that folder is evidence from one meeting.
- New processing must operate on a job directory supplied at runtime.
- Keep model-specific logic behind provider/stage interfaces.
- Reuse the working transcription, consensus, cleanup, condensation, and DOCX
  code initially; refactor incrementally instead of rewriting model inference.
- Long-running stages must be checkpointed and safely resumable.
- Cancellation must preserve completed checkpoints.
- Only one GPU-heavy job should execute at once on the target workstation.
- Progress must come from real stage/chunk/batch counts, never a cosmetic timer.
- Support Unicode and Cyrillic Windows paths.
- Keep timestamps internally as numeric seconds and render them to users as
  `[HH:MM:SS]`; never expose raw floating-point ranges.

## Job contract

Each recording should receive an isolated directory containing at least:

```text
job.json
status.json
events.jsonl
checkpoints/
documents/
_audit/
logs/
```

`job.json` is immutable input/configuration provenance. `status.json` is the
latest materialized job state. `events.jsonl` is the append-only progress and
error history.

## GUI direction

- Preferred final UI: a Tauri 2 Windows desktop application with a React and
  TypeScript front end.
- Use Tailwind CSS, shadcn/ui primitives, and restrained motion to deliver a
  polished office-grade interface. Do not imitate a developer dashboard.
- Keep the existing Python pipeline as a packaged sidecar/job worker.
- The GUI is an orchestration surface, not a second implementation of the
  pipeline.
- Invoke long-running stages through subprocesses and structured events so the UI
  remains responsive.
- Default UI should expose only:
  - recording;
  - processing/privacy mode;
  - speaker range or automatic detection;
  - output folder;
  - Start.
- Put model names, logs, metrics, and diagnostics behind an Advanced/Details view.
- Use office-language errors with Retry/Resume actions; keep tracebacks in logs.

## Verification

Run the existing automated suite after Python changes:

```powershell
python -m pytest -q
```

For pipeline changes, also test:

- a short synthetic audio fixture;
- a Unicode/Cyrillic file path;
- resume from a partially completed job;
- cancellation between checkpoints;
- local mode with network disabled;
- cloud mode with the API key missing;
- DOCX output names, warnings, timestamps, and speaker labels.

Do not claim correctness from cross-model agreement. WER/CER, cpWER, DER/JER,
and summary precision/recall require human reference data.
