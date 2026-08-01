export type ProcessingMode = "local" | "deepseek";

export interface SystemStatus {
  project_root: string;
  ffmpeg: boolean;
  wsl: boolean;
  nvidia: boolean;
  ollama: boolean;
  ollama_installed: boolean;
  ollama_models: string[];
  deepseek_configured: boolean;
  windows_python: boolean;
  docs_python: boolean;
  moss_python: boolean;

  qwen_python: boolean;
}
export interface HardwareStatus {
  os: {
    version: string;
    build: number;
    supported: boolean;
  };
  cpu: {
    name: string;
    physical_cores: number;
    logical_cores: number;
  };
  ram_gb: number;
  disk: {
    root: string;
    free_gb: number;
  };
    largest_single_gpu_vram_gb: number;
    total_vram_gb: number;
    gpu_count: number;
    power_limit_w: number;
    total_power_limit_w: number;
    gpus: Array<{ index: number; name: string; vram_gb: number; driver: string; power_limit_w: number }>;
  nvidia: {
    available: boolean;
    name: string;
    vram_gb: number;
    driver: string;
    cuda_visible: boolean;
  };
  wsl: {
    available: boolean;
    distro_ready: boolean;
    distros: string[];
  };
  form_factor: {
    id: "portable" | "desktop" | "workstation" | "server";
    portable: boolean;
    has_battery: boolean;
    chassis_types: number[];
  };
}

export interface WorkstationComponent {
  id: string;
  label: string;
  required: boolean;
  ready: boolean;
  detail: string;
}

export interface ModelFit {
  status: "recommended" | "fits" | "slow_offload" | "unavailable" | "api";
  label: string;
  reason: string;
}

export interface WorkstationModel {
  id: string;
  display_name: string;
  role: string;
  provider: string;
  locator: string;
  download_gb: number;
  quality_tier: string;
  efficiency_tier: string;
  production_status: string;
  selectable: boolean;
  rationale: string;
  installed: boolean;
  fit: ModelFit;
}

export interface WorkstationPack {
  id: string;
  label: string;
  description: string;
  required_model_ids: string[];
  optional_model_ids: string[];
  api_model_ids: string[];
  estimated_download_gb: number;
  estimated_installed_gb: number;
  recommended: boolean;
}

export interface WorkstationModelInstallResult {
  id: string;
  label: string;
  required: boolean;
  status: "pending" | "installing" | "ready" | "skipped" | "failed";
  detail: string;
}

export interface WorkstationSetupState {
  status: "IDLE" | "RUNNING" | "PAUSED_REBOOT" | "COMPLETE" | "PARTIAL" | "FAILED";
  stage: string;
  progress: number;
  message: string;
  reboot_required: boolean;
  error: string | {
    message?: string;
    type?: string;
    failures?: Array<{ id: string; label: string; message: string }>;
  } | null;
  model_results: WorkstationModelInstallResult[];
  pack_id?: string;
  selected_model_ids?: string[];
}

export interface WorkstationStatus {
  schema_version: number;
  catalog: {
    id: string;
    as_of: string;
    review_window: string;
    disclaimer: string;
  };
  runtime_root: string;
  state_path: string;
  ready: boolean;
  hardware: HardwareStatus;
  hardware_class: {
    id: string;
    label: string;
    min_vram_gb: number;
    max_vram_gb: number;
    min_ram_gb: number;
    recommendation: string;
    recommended_ram_gb: number;
    min_free_disk_gb: number;
    recommended_free_disk_gb: number;
    local_text_ceiling: string;
  };
  ollama: {
    installed: boolean;
    running: boolean;
    models: string[];
  };
  components: WorkstationComponent[];
  packs: WorkstationPack[];
  models: WorkstationModel[];
  setup: WorkstationSetupState;
  resource_assessment: {
    tier_id: string;
    deployment_class: string;
    largest_single_gpu_vram_gb: number;
    total_vram_gb: number;
    gpu_count: number;
    meets_min_ram: boolean;
    meets_recommended_ram: boolean;
    meets_min_disk: boolean;
    meets_recommended_disk: boolean;
    multi_gpu_vram_summed_for_models: boolean;
    current_parallel_gpu_jobs: number;
  };
}

export interface WorkstationSetupLaunch {
  started: boolean;
  process_id: number;
  state_path: string;
  pack_id: string;
}

export interface JobDocument {
  key: "minutes" | "full" | "edited" | "condensed";
  filename: string;
  title: string;
  description: string;
  path: string;
  size_bytes: number;
}

export interface JobError {
  message: string;
  detail?: string;
  log_path?: string;
}

export interface JobStatus {
  schema_version: number;
  job_id: string;
  state: string;
  stage: string | null;
  stage_label: string;
  overall_progress: number;
  stage_progress: number | null;
  input_filename?: string;
  message: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number;
  eta_seconds: number | null;
  recording_duration_seconds?: number;
  current_unit: number | null;
  total_units: number | null;
  provider: string;
  model: string;
  cloud_used: boolean;
  documents: JobDocument[];
  error: JobError | null;
}

export interface LaunchResult {
  job_dir: string;
  worker_pid: number;
}

export const STAGES = [
  ["VALIDATING", "Проверка записи"],
  ["TRANSCRIBING_WHISPERX", "WhisperX"],
  ["TRANSCRIBING_MOSS", "MOSS и разметка речи"],
  ["CLUSTERING_SPEAKERS", "Говорящие"],
  ["TRANSCRIBING_QWEN", "Qwen"],
  ["ADJUDICATING", "Сверка текста"],
  ["CREATING_MINUTES", "Протокол"],
  ["CLEANING_TRANSCRIPT", "Редакционная версия"],
  ["CONDENSING_TRANSCRIPT", "Сокращённая версия"],
  ["BUILDING_DOCX", "Документы Word"],
] as const;

export const SUPPORTED_EXTENSIONS = [
  "mp4", "m4a", "mp3", "wav", "mov", "mkv", "aac", "flac", "ogg", "webm",
];
