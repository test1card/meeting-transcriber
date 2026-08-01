import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import type {
  JobStatus,
  LaunchResult,
  WorkstationSetupLaunch,
  WorkstationStatus,
  ProcessingMode,
  SystemStatus,
} from "../types";

export async function chooseRecording(): Promise<string | null> {
  const selected = await open({
    multiple: false,
    directory: false,
    title: "Выберите запись совещания",
    filters: [
      {
        name: "Аудио и видео",
        extensions: [
          "mp4",
          "m4a",
          "mp3",
          "wav",
          "mov",
          "mkv",
          "aac",
          "flac",
          "ogg",
          "webm",
        ],
      },
    ],
  });
  return typeof selected === "string" ? selected : null;
}

export async function chooseOutputFolder(): Promise<string | null> {
  const selected = await open({
    multiple: false,
    directory: true,
    title: "Куда сохранить документы",
  });
  return typeof selected === "string" ? selected : null;
}

export function getSystemStatus(startOllama = false): Promise<SystemStatus> {
  return invoke<SystemStatus>("system_status", { startOllama });
}

export function getDefaultOutputRoot(): Promise<string> {
  return invoke<string>("default_output_root");
}

export function startJob(options: {
  inputPath: string;
  outputRoot: string;
  mode: ProcessingMode;
  model: string;
  speakerCount: number | null;
  cloudConsent: boolean;
}): Promise<LaunchResult> {
  return invoke<LaunchResult>("start_job", options);
}

export function getJobStatus(jobDir: string): Promise<JobStatus> {
  return invoke<JobStatus>("get_job_status", { jobDir });
}

export function cancelJob(jobDir: string): Promise<void> {
  return invoke<void>("cancel_job", { jobDir });
}

export function resumeJob(jobDir: string): Promise<LaunchResult> {
  return invoke<LaunchResult>("resume_job", { jobDir });
}

export function openDocument(
  jobDir: string,
  documentPath: string,
): Promise<void> {
  return invoke<void>("open_document", { jobDir, documentPath });
}

export function getWorkstationStatus(): Promise<WorkstationStatus> {
  return invoke<WorkstationStatus>("workstation_status");
}

export function startWorkstationSetup(
  packId: string,
  modelIds: string[],
): Promise<WorkstationSetupLaunch> {
  return invoke<WorkstationSetupLaunch>("start_workstation_setup", {
    packId,
    modelIds,
  });
}

export function openWorkstationSetupLog(): Promise<void> {
  return invoke<void>("open_workstation_setup_log");
}

export function openJobFolder(jobDir: string): Promise<void> {
  return invoke<void>("open_job_folder", { jobDir });
}

export function openLogsFolder(jobDir: string): Promise<void> {
  return invoke<void>("open_logs_folder", { jobDir });
}
