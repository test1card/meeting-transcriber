import {
  cp,
  mkdir,
  readdir,
  rm,
  stat,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const desktopRoot = path.resolve(here, "..");
const projectRoot = path.resolve(desktopRoot, "..", "..");
const targetRoot = path.join(
  desktopRoot,
  "src-tauri",
  "resources",
  "workstation",
);

if (
  !targetRoot.endsWith(
    path.join("src-tauri", "resources", "workstation"),
  )
) {
  throw new Error(`Unsafe resource target: ${targetRoot}`);
}

const allowedRuntimeExtensions = new Set([
  ".py",
  ".ps1",
  ".psm1",
  ".sh",
  ".json",
  ".toml",
  ".md",
  ".txt",
  ".html",
  ".css",
  ".js",
  ".svg",
  ".png",
  ".ico",
]);

async function copyTree(source, destination, allowedExtensions) {
  await mkdir(destination, { recursive: true });
  for (const entry of await readdir(source, { withFileTypes: true })) {
    if (
      entry.name === ".git" ||
      entry.name === "__pycache__" ||
      entry.name.endsWith(".egg-info")
    ) {
      continue;
    }
    const sourcePath = path.join(source, entry.name);
    const targetPath = path.join(destination, entry.name);
    if (entry.isDirectory()) {
      await copyTree(sourcePath, targetPath, allowedExtensions);
      continue;
    }
    if (
      !allowedExtensions ||
      allowedExtensions.has(path.extname(entry.name).toLowerCase())
    ) {
      await cp(sourcePath, targetPath);
    }
  }
}

await rm(targetRoot, { recursive: true, force: true });
await mkdir(targetRoot, { recursive: true });

await copyTree(
  path.join(projectRoot, "installer"),
  path.join(targetRoot, "installer"),
  new Set([".ps1", ".psm1", ".json"]),
);

const runtimeRoot = path.join(targetRoot, "runtime-source");
await copyTree(
  path.join(projectRoot, "meeting_transcriber"),
  path.join(runtimeRoot, "meeting_transcriber"),
  new Set([".py"]),
);
for (const filename of [
  "Start-Ollama.ps1",
  "clean_transcript_deepseek.py",
  "cluster_moss_speakers.py",
  "condense_transcript_deepseek.py",
  "monitor_process.ps1",
  "run_wsl.sh",
  "transcribe_moss_chunked.py",
  "transcribe_qwen_checkpointed.py",
]) {
  await cp(
    path.join(projectRoot, "scripts", filename),
    path.join(runtimeRoot, "scripts", filename),
  );
}

const mossSource = path.join(
  projectRoot,
  "vendor",
  "MOSS-Transcribe-Diarize",
);
const mossTarget = path.join(
  runtimeRoot,
  "vendor",
  "MOSS-Transcribe-Diarize",
);
await copyTree(
  path.join(mossSource, "moss_transcribe_diarize"),
  path.join(mossTarget, "moss_transcribe_diarize"),
  allowedRuntimeExtensions,
);
for (const filename of ["pyproject.toml", "LICENSE", "README.md"]) {
  await cp(path.join(mossSource, filename), path.join(mossTarget, filename));
}

for (const filename of [
  "run.ps1",
  "run-moss-checkpointed.ps1",
  "run-qwen-checkpointed.ps1",
  "run-speaker-clustering.ps1",
]) {
  await cp(path.join(projectRoot, filename), path.join(runtimeRoot, filename));
}

async function directorySize(root) {
  let total = 0;
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const item = path.join(root, entry.name);
    total += entry.isDirectory() ? await directorySize(item) : (await stat(item)).size;
  }
  return total;
}

const bytes = await directorySize(targetRoot);
console.log(
  `Prepared clean workstation resources: ${(bytes / 1024 / 1024).toFixed(2)} MiB`,
);
