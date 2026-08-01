# Multi-STT consensus for Russian meetings

The consensus stage accepts two or more `transcript.json` files and produces one
canonical transcript plus a complete audit trail.

## Safety model

One transcript is selected as the **anchor**. Its timestamps and speaker labels
are immutable. For every anchor turn, the pipeline collects text from all other
STT segments that overlap it in time.

Exact agreements bypass the LLM. Disagreements are sent in small batches to the
selected judge. The judge may reconstruct only the spoken text. It is explicitly
forbidden to summarize, translate, invent context, change speakers, or change
timestamps.

The Russian adjudication prompt preserves occasional English technical terms,
names, identifiers, filenames, commands, numbers, and negation.

## Run

Copy `glossary.example.txt` to `glossary.txt`, then add company-specific names and
technical vocabulary.

```powershell
cd C:\path\to\meeting-transcriber

.\consensus.ps1 `
  -Transcripts @(
    ".\runs\moss\transcript.json",
    ".\runs\qwen\transcript.json",
    ".\runs\whisperx\transcript.json"
  ) `
  -Labels "moss,qwen,whisperx" `
  -Anchor "moss" `
  -Glossary ".\glossary.txt" `
  -JudgeModel "gemma4:26b" `
  -NoDeepSeek
```

Use the STT result with the best speaker diarization as the anchor. MOSS is the
natural first choice; use WhisperX instead if it assigns speakers more accurately
on the recording.

Remove `-NoDeepSeek` to run the existing local and DeepSeek summary comparison
after adjudication. Only transcript text and glossary terms—not audio—are sent to
DeepSeek.

## Inputs

Each JSON file may use either shape:

```json
{
  "transcript": {
    "language": "ru",
    "segments": [
      {
        "start": 1.2,
        "end": 4.8,
        "speaker": "S01",
        "text": "Запускаем Docker в пятницу."
      }
    ]
  },
  "metadata": {}
}
```

or a top-level object containing `segments`.

Only the anchor must have reliable `speaker` values. Every input must have useful
segment timestamps.

## Outputs

- `transcript.json`: canonical machine-readable transcript
- `transcript.md`: readable Russian transcript
- `transcript.srt`: subtitles
- `consensus-audit.json`: every candidate reading and final decision
- `minutes-*.md`: optional independent summaries
- `comparison.md` and `compare.html`: optional summary comparison

Each canonical segment includes:

```json
{
  "consensus": {
    "confidence": "high",
    "support": ["moss", "qwen"]
  }
}
```

Review every `low` confidence segment in `consensus-audit.json` against the audio.
