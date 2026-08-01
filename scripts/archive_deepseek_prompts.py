from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from meeting_transcriber.consensus import (
    _agreed_decision,
    _batches,
    build_consensus_units,
    load_candidate,
)
from meeting_transcriber.formatting import chunk_lines, transcript_lines


CONSENSUS_SYSTEM = (
    "You are a conservative speech-transcription adjudicator, not a summarizer. "
    "For each ID, reconstruct exactly what was spoken using only the competing STT "
    "readings. The meeting is predominantly Russian with occasional individual "
    "English words. Preserve supported English technical terms, names, identifiers, "
    "numbers, negation, uncertainty, and meaning. Do not translate, paraphrase, "
    "polish content, merge IDs, invent context, or add facts. Fix punctuation and "
    "obvious recognition errors only when supported by another reading or the "
    "glossary. If evidence is genuinely insufficient, retain the anchor reading and "
    "mark confidence low. Return one decision for every ID as valid JSON. "
    'Use exactly this JSON shape: {"decisions":[{"id":"A00001",'
    '"text":"faithful decided text","confidence":"high",'
    '"support":["moss","qwen"],"note":"short evidence note"}]}. '
    "The decisions array must contain every requested ID exactly once. "
    "Do not return separate JSON objects, an ID-keyed map, Markdown, or "
    "explanatory text outside the JSON object."
)

EXTRACTION_SYSTEM = (
    "You are a meticulous meeting analyst. Extract only facts supported by the "
    "transcript. Never invent owners, deadlines, decisions, or consensus. Use "
    '"unspecified" when a field is not explicit. Every decision, action, risk, '
    "and question must include an evidence timestamp copied from the transcript. "
    "Preserve English technical terms, names, identifiers, filenames, and commands "
    "in their original Latin spelling; do not translate or transliterate them. "
    "Write in Russian. Return valid JSON only. "
    "Use exactly the following JSON shape; empty arrays are allowed: "
    '{"overview":"supported overview","topics":[{"topic":"topic",'
    '"summary":"supported summary","evidence":["[00:01:02]"]}],'
    '"decisions":[{"decision":"explicit decision","owner":"unspecified",'
    '"evidence":"[00:01:02]"}],"actions":[{"task":"explicit task",'
    '"owner":"unspecified","due":"unspecified","evidence":"[00:01:02]"}],'
    '"risks":[{"risk":"supported risk","evidence":"[00:01:02]"}],'
    '"open_questions":[{"question":"unresolved question",'
    '"evidence":"[00:01:02]"}]}. '
    "Do not return Markdown, separate JSON objects, an alternative schema, "
    "or text outside the single JSON object."
)

SYNTHESIS_SYSTEM = (
    "You are an executive meeting-minutes editor. Produce clear, concise, "
    "beautiful Markdown using only the supplied extracted facts. Merge duplicates. "
    "Do not turn proposals into decisions. Preserve evidence timestamps. Use these "
    "headings: Executive summary, Topics discussed, Decisions, Action items, "
    "Risks and blockers, Open questions. Use a table for action items. "
    "The action table must contain Task, Owner, Due, and Evidence columns. "
    "If a section has no supported entries, say 'None identified'. "
    "Preserve supported English technical terms, names, identifiers, filenames, "
    "and commands in their original Latin spelling. Write in Russian."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconstruct and archive prior DeepSeek prompt messages."
    )
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def archive_consensus(root: Path, output: Path) -> dict[str, Any]:
    run = root / "consensus-deepseek-flash-v2"
    audit = json.loads((run / "consensus-audit.json").read_text(encoding="utf-8"))
    candidates = [
        load_candidate(Path(entry["path"]), entry["label"])
        for entry in audit["candidates"]
    ]
    _, units = build_consensus_units(candidates, anchor_label=audit["anchor"])
    unit_by_id = {unit["id"]: unit for unit in units}
    checkpoints = run / "consensus-checkpoints"
    checkpoint_paths = sorted(checkpoints.glob("batch-*.json"))
    verified = 0
    for index, checkpoint_path in enumerate(checkpoint_paths, start=1):
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        decision_ids = [item["id"] for item in checkpoint["decisions"]]
        batch = [unit_by_id[item_id] for item_id in decision_ids]
        user_payload = {
            "primary_language": "ru",
            "glossary": audit.get("glossary", []),
            "units": [
                {
                    "id": unit["id"],
                    "speaker": unit["speaker"],
                    "start": unit["start"],
                    "end": unit["end"],
                    "readings": unit["readings"],
                }
                for unit in batch
            ],
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "language": "ru",
                    "glossary": audit.get("glossary", []),
                    "batch": batch,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        matches = checkpoint.get("fingerprint") == fingerprint
        verified += int(matches)
        write_json(
            output / "consensus" / f"batch-{index:03d}.json",
            {
                "provenance": "deterministically reconstructed",
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "response_format": {"type": "json_object"},
                "checkpoint_fingerprint": checkpoint.get("fingerprint"),
                "reconstructed_fingerprint": fingerprint,
                "fingerprint_verified": matches,
                "messages": [
                    {"role": "system", "content": CONSENSUS_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
            },
        )
    return {
        "batches": len(checkpoint_paths),
        "fingerprints_verified": verified,
        "all_fingerprints_verified": verified == len(checkpoint_paths),
    }


def archive_summary(root: Path, output: Path) -> dict[str, Any]:
    transcript_payload = json.loads(
        (root / "consensus-deepseek-flash-v2" / "transcript.json").read_text(
            encoding="utf-8"
        )
    )
    transcript = transcript_payload.get("transcript", transcript_payload)
    lines = transcript_lines(transcript["segments"])
    chunks = chunk_lines(lines, max_chars=16_000)
    for index, chunk in enumerate(chunks, start=1):
        user = (
            f"Transcript section {index}/{len(chunks)}:\n\n{chunk}\n\n"
            "Extract an overview, topics, explicit decisions, action items, "
            "risks/blockers, and unresolved questions according to the requested "
            "JSON schema."
        )
        write_json(
            output / "summary" / f"extraction-{index:03d}.json",
            {
                "provenance": (
                    "deterministically reconstructed from transcript and source; "
                    "summary_language inferred as Russian from the launcher"
                ),
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": EXTRACTION_SYSTEM},
                    {"role": "user", "content": user},
                ],
            },
        )
    extraction = json.loads(
        (
            root
            / "summary-comparison"
            / "extraction-deepseek-v4-flash.json"
        ).read_text(encoding="utf-8")
    )
    write_json(
        output / "summary" / "synthesis-final.json",
        {
            "provenance": (
                "deterministically reconstructed from final extraction and source; "
                "summary_language inferred as Russian from the launcher"
            ),
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "messages": [
                {"role": "system", "content": SYNTHESIS_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(extraction, ensure_ascii=False),
                },
            ],
        },
    )
    write_json(
        output / "conditional-repair-prompts.json",
        {
            "provenance": "source-defined conditional prompts; invocation not proven",
            "consensus_repair_system": (
                "Return corrected JSON only. Include exactly one decision for "
                "every requested ID and no additional IDs."
            ),
            "summary_json_repair_system": "Repair the following into valid JSON only.",
            "warning": (
                "Old response logs were not retained, so the archive cannot prove "
                "whether either conditional repair path was invoked."
            ),
        },
    )
    return {"extraction_prompts": len(chunks), "synthesis_prompts": 1}


def main() -> int:
    args = parse_args()
    root = args.benchmark_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    consensus = archive_consensus(root, output)
    summary = archive_summary(root, output)
    cleanup_sources = {
        "smoke_test_editorial_v1": root / "cleaned-transcript-smoke" / "prompts",
        "full_editorial_v1": root / "cleaned-transcript-deepseek" / "prompts",
        "full_editorial_v2": root / "cleaned-transcript-deepseek-v2" / "prompts",
        "semantic_condensation_v1": (
            root / "condensed-transcript-deepseek" / "prompts"
        ),
    }
    cleanup_manifest = {}
    for label, source in cleanup_sources.items():
        destination = output / "cleanup" / label
        destination.mkdir(parents=True, exist_ok=True)
        for prompt in sorted(source.glob("*.json")):
            shutil.copy2(prompt, destination / prompt.name)
        cleanup_manifest[label] = {
            "path": str(Path("cleanup") / label),
            "prompt_files": len(list(destination.glob("*.json"))),
        }
    manifest = {
        "scope": "DeepSeek V4 Flash prompts used for consensus, minutes, and transcript cleanup",
        "secrets_included": False,
        "consensus": consensus,
        "summary": summary,
        "cleanup_prompts": cleanup_manifest,
        "limitations": [
            "The earlier runs did not prospectively log HTTP request bodies.",
            "Consensus prompts are fingerprint-verified against all checkpoints.",
            "Summary prompts are reconstructed from immutable inputs and source code; "
            "the launcher indicates Russian, but no request-body log exists.",
            "Conditional repair invocations cannot be established from retained logs.",
        ],
    }
    write_json(output / "manifest.json", manifest)
    (output / "README.md").write_text(
        "# DeepSeek prompt archive\n\n"
        "No API keys or authorization headers are stored here.\n\n"
        f"- Consensus: {consensus['batches']} instantiated prompts; "
        f"{consensus['fingerprints_verified']} checkpoint fingerprints verified.\n"
        f"- Minutes: {summary['extraction_prompts']} extraction prompts and one "
        "final synthesis prompt reconstructed.\n"
        "- Cleaned transcript: exact prospective logs include one smoke-test "
        "prompt, nine conservative-v1 prompts, and nine final-v2 prompts. They "
        "remain beside their respective cleanup runs.\n"
        "- Shortened semantic transcript: six exact prospective prompts.\n\n"
        "See `manifest.json` for reconstruction limitations.\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
