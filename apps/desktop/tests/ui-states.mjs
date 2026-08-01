import { spawn, spawnSync } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const here = path.dirname(fileURLToPath(import.meta.url));
const appRoot = path.resolve(here, "..");
const resultRoot = path.join(appRoot, "test-results");
const url = "http://127.0.0.1:4174";
const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
await mkdir(resultRoot, { recursive: true });

const system = {
  project_root: "C:\\Meeting Transcriber",
  ffmpeg: true,
  wsl: true,
  nvidia: true,
  ollama: true,
  ollama_installed: true,
  ollama_models: ["gemma4:e4b", "gemma4:26b"],
  deepseek_configured: true,
  windows_python: true,
  docs_python: true,
  moss_python: true,
  qwen_python: true,
};

const catalog = JSON.parse(
  await readFile(
    path.resolve(appRoot, "..", "..", "installer", "model-catalog.json"),
    "utf8",
  ),
);
const resourceTier = catalog.resource_tiers.find(
  (tier) => tier.id === "resource-16",
);
const workstation = {
  schema_version: 2,
  catalog: {
    id: catalog.catalog_id,
    as_of: catalog.as_of,
    review_window: catalog.review_window,
    disclaimer: catalog.disclaimer,
  },
  runtime_root: "C:\\Meeting Documents",
  state_path: "C:\\Meeting Documents\\setup-state.json",
  ready: true,
  hardware: {
    os: { version: "10.0.26200.0", build: 26200, supported: true },
    cpu: { name: "12-core workstation processor", physical_cores: 12, logical_cores: 24 },
    ram_gb: 64,
    disk: { root: "C:\\", free_gb: 180 },
    nvidia: {
      available: true, name: "NVIDIA GPU", vram_gb: 16,
      largest_single_gpu_vram_gb: 16, total_vram_gb: 16, gpu_count: 1,
      power_limit_w: 300, total_power_limit_w: 300, driver: "610.62",
      cuda_visible: true, gpus: [],
    },
    wsl: { available: true, distro_ready: true, distros: ["Ubuntu-22.04"] },
    form_factor: { id: "desktop", portable: false, has_battery: false, chassis_types: [3] },
  },
  hardware_class: resourceTier,
  resource_assessment: {
    tier_id: "resource-16", deployment_class: "desktop",
    largest_single_gpu_vram_gb: 16, total_vram_gb: 16, gpu_count: 1,
    meets_min_ram: true, meets_recommended_ram: true,
    meets_min_disk: true, meets_recommended_disk: true,
    multi_gpu_vram_summed_for_models: false, current_parallel_gpu_jobs: 1,
  },
  ollama: { installed: true, running: true, models: ["gemma4:e4b"] },
  components: [],
  packs: catalog.packs.map((pack) => ({
    ...pack,
    recommended: resourceTier.recommended_pack_ids.includes(pack.id),
  })),
  models: catalog.models.map((model) => ({
    ...model,
    installed: model.id === "gemma4-e4b",
    fit: {
      status: model.provider.endsWith("-api") ? "api" : model.id === "gemma4-26b" ? "slow_offload" : "recommended",
      label: "Подходит", reason: "Test fixture",
    },
  })),
  setup: { status: "IDLE", stage: "not_started", progress: 0, message: "Setup has not started", reboot_required: false, error: null },
};

const baseStatus = {
  schema_version: 1,
  job_id: "20260730T090000Z-recording",
  stage_progress: null,
  input_filename: "Стратегическая сессия — июль 2026.mp4",
  created_at: "2026-07-30T09:00:00+03:00",
  updated_at: "2026-07-30T10:24:00+03:00",
  started_at: "2026-07-30T09:00:02+03:00",
  finished_at: null,
  elapsed_seconds: 5040,
  eta_seconds: 3900,
  recording_duration_seconds: 10320,
  current_unit: null,
  total_units: null,
  provider: "deepseek",
  model: "deepseek-v4-flash",
  cloud_used: true,
  documents: [],
  error: null,
};

const documents = [
  {
    key: "minutes",
    filename: "01_Протокол.docx",
    title: "Протокол совещания",
    description: "Решения, поручения, сроки и ответственные.",
    path: "C:\\Results\\01_Протокол.docx",
    size_bytes: 38214,
  },
  {
    key: "full",
    filename: "02_Полная_стенограмма.docx",
    title: "Полная стенограмма",
    description: "Полный текст с говорящими и отметками времени.",
    path: "C:\\Results\\02_Полная_стенограмма.docx",
    size_bytes: 110982,
  },
  {
    key: "edited",
    filename: "03_Редакционная_версия.docx",
    title: "Редакционная версия",
    description: "Речь без технических реплик и словесного мусора.",
    path: "C:\\Results\\03_Редакционная_версия.docx",
    size_bytes: 79420,
  },
  {
    key: "condensed",
    filename: "04_Сокращённая_версия.docx",
    title: "Сокращённая версия",
    description: "Смысл совещания без повторов.",
    path: "C:\\Results\\04_Сокращённая_версия.docx",
    size_bytes: 42118,
  },
];

const scenarios = {
  ready: null,
  processing: {
    ...baseStatus,
    state: "RUNNING",
    stage: "TRANSCRIBING_MOSS",
    stage_label: "MOSS и разметка речи",
    overall_progress: 0.31,
    stage_progress: 0.46,
    message: "Распознаём речь и определяем говорящих",
    current_unit: 8,
    total_units: 17,
  },
  failed: {
    ...baseStatus,
    state: "FAILED",
    stage: "TRANSCRIBING_QWEN",
    stage_label: "Qwen",
    overall_progress: 0.48,
    message: "Обработка остановлена",
    error: {
      message: "Недостаточно видеопамяти для модели Qwen. Закройте другие задачи GPU и продолжите с контрольной точки.",
      log_path: "C:\\Results\\logs\\worker.log",
    },
  },
  complete: {
    ...baseStatus,
    state: "COMPLETE",
    stage: "BUILDING_DOCX",
    stage_label: "Документы Word",
    overall_progress: 1,
    message: "Четыре документа готовы",
    finished_at: "2026-07-30T11:02:00+03:00",
    elapsed_seconds: 7320,
    eta_seconds: 0,
    documents,
  },
};

function startVite() {
  const executable = process.platform === "win32"
    ? (process.env.ComSpec || "C:\\Windows\\System32\\cmd.exe")
    : "npm";
  const args = process.platform === "win32"
    ? ["/d", "/s", "/c", "npm run dev -- --host 127.0.0.1 --port 4174"]
    : ["run", "dev", "--", "--host", "127.0.0.1", "--port", "4174"];
  return spawn(executable, args, {
    cwd: appRoot,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

async function waitForServer(processHandle) {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    if (processHandle.exitCode !== null) {
      throw new Error(`Vite exited early with code ${processHandle.exitCode}`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Vite is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("Timed out waiting for Vite");
}

function installTauriMock(payload) {
  const { scenario, systemStatus, workstationStatus } = payload;
  const callbacks = new Map();
  window.__TAURI_CALLS__ = [];
  let nextCallback = 1;
  window.__TAURI_INTERNALS__ = {
    metadata: {
      currentWindow: { label: "main" },
      currentWebview: { label: "main" },
    },
    transformCallback(callback, once = false) {
      const id = nextCallback++;
      callbacks.set(id, { callback, once });
      return id;
    },
    unregisterCallback(id) {
      callbacks.delete(id);
    },
    runCallback(id, data) {
      const entry = callbacks.get(id);
      if (!entry) return;
      entry.callback?.(data);
      if (entry.once) callbacks.delete(id);
    },
    async invoke(command, args = {}) {
      if (command === "plugin:event|listen") return args.handler;
      window.__TAURI_CALLS__.push({ command, args });
      if (command === "plugin:event|unlisten") return null;
      if (command === "system_status") return systemStatus;
      if (command === "workstation_status") return workstationStatus;
      if (command === "default_output_root") return "C:\\Документы\\Встречи";
      if (command === "get_job_status") return scenario;
      if (command.startsWith("plugin:dialog|")) return null;
      return null;
    },
  };
  window.__TAURI_EVENT_PLUGIN_INTERNALS__ = {
    unregisterListener() {},
  };
  if (scenario) {
    localStorage.setItem("meeting-documents.current-job", "C:\\Results\\20260730T090000Z-recording");
  } else {
    localStorage.removeItem("meeting-documents.current-job");
  }
}

const expected = {
  ready: "Из записи — в готовые документы",
  processing: "Готовим документы встречи",
  failed: "Не удалось завершить один из этапов",
  complete: "Документы встречи подготовлены",
};

const server = startVite();
let browser;
const failures = [];
try {
  await waitForServer(server);
  browser = await chromium.launch({ executablePath: chrome, headless: true });
  for (const [name, status] of Object.entries(scenarios)) {
    const page = await browser.newPage({ viewport: { width: 1180, height: 840 }, deviceScaleFactor: 1, reducedMotion: "reduce" });
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.addInitScript(installTauriMock, { scenario: status, systemStatus: system, workstationStatus: workstation });
    await page.goto(url, { waitUntil: "networkidle" });
    await page.waitForTimeout(450);
    await page.getByText(expected[name], { exact: false }).first().waitFor();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    if (overflow) failures.push(`${name}: horizontal overflow`);
    if (errors.length) failures.push(`${name}: ${errors.join(" | ")}`);
    await page.screenshot({ path: path.join(resultRoot, `${name}.png`), fullPage: true });

    if (name === "ready") {
      await page.getByRole("radio", { name: /На этом компьютере/ }).click();
      const localSelected = await page.getByRole("radio", { name: /На этом компьютере/ }).getAttribute("aria-checked");
      if (localSelected !== "true") failures.push("ready: local mode did not become selected");
      const startedOllama = await page.evaluate(() =>
        window.__TAURI_CALLS__.some(
          (call) => call.command === "system_status" && call.args?.startOllama === true,
        ),
      );
      if (!startedOllama) failures.push("ready: local mode did not request Ollama startup");
      await page.getByRole("radio", { name: /DeepSeek API/ }).click();

      await page.getByRole("button", { name: "Справка" }).click();
      await page.waitForTimeout(450);
      await page.getByRole("heading", { name: "Как подготовить документы" }).waitFor();
      await page.screenshot({ path: path.join(resultRoot, "help.png"), fullPage: true });
      await page.getByRole("button", { name: "Закрыть" }).first().click();
      await page.getByRole("button", { name: /Система готова|Нужна настройка/ }).click();
      await page.waitForTimeout(450);
      await page.getByRole("heading", { name: "Диагностика рабочей станции" }).waitFor();
      await page.screenshot({ path: path.join(resultRoot, "diagnostics.png"), fullPage: true });
      const diagnosticRows = await page.locator(".diagnostic-row").count();
      if (diagnosticRows !== 5) failures.push(`diagnostics: expected 5 checks, got ${diagnosticRows}`);
      const healthyRows = await page.locator(".diagnostic-row .status-dot-good").count();
      if (healthyRows !== 5) failures.push(`diagnostics: expected 5 healthy checks, got ${healthyRows}`);
      if (await page.locator(".diagnostic-error").count()) failures.push("diagnostics: unexpected system error");
      await page.getByRole("button", { name: /Модели и установка/ }).click();
      await page.waitForTimeout(450);
      await page.getByRole("heading", { name: "Настройка рабочей станции" }).waitFor();
      await page.getByText("13–19 ГБ VRAM", { exact: true }).waitFor();
      const packCards = await page.locator(".pack-card").count();
      if (packCards !== 4) failures.push(`setup: expected 4 pack cards, got ${packCards}`);
      await page.screenshot({ path: path.join(resultRoot, "workstation-setup.png"), fullPage: true });
      await page.getByRole("button", { name: "Закрыть" }).first().click();
    }
    await page.close();
  }
} finally {
  await browser?.close();
  if (process.platform === "win32" && server.pid) {
    spawnSync("taskkill", ["/pid", String(server.pid), "/t", "/f"], { windowsHide: true, stdio: "ignore" });
  } else {
    server.kill("SIGTERM");
  }
}

if (failures.length) {
  throw new Error(`UI state checks failed:\n${failures.join("\n")}`);
}
console.log(`UI states verified. Screenshots: ${resultRoot}`);
