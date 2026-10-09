"""Download pinned official checkpoints without executing model code."""
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "asr": "microsoft/VibeVoice-ASR-Streaming-7B",
    "diarization": "nvidia/Nemotron-3-Diarization",
    "llm": "Qwen/Qwen3-8B-FP8",
}

if __name__ == "__main__":
    api = HfApi()
    manifest_path = ROOT / "local-runtime.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for role, repo in MODELS.items():
        entry = manifest.get(role, {})
        revision = entry.get("revision") or api.model_info(repo).sha
        target = ROOT / "models" / role
        manifest[role] = {"repo": repo, "revision": revision, "path": str(target), "downloaded": False}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"Downloading {role}: {repo}@{revision}", flush=True)
        snapshot_download(repo, revision=revision, local_dir=target, max_workers=3,
                          allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken", "README.md"])
        manifest[role]["downloaded"] = True
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        print(f"Ready: {role}", flush=True)
