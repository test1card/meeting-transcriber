import {
  Activity,
  ChevronRight,
  FolderOpen,
  Headphones,
  HelpCircle,
  Moon,
  Settings2,
  ShieldCheck,
  Sun,
  Users,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import {
  cancelJob,
  chooseOutputFolder,
  getDefaultOutputRoot,
  getJobStatus,
  getSystemStatus,
  getWorkstationStatus,
  openDocument,
  openJobFolder,
  openLogsFolder,
  resumeJob,
  startJob,
} from "./lib/backend";
import type {
  JobDocument,
  JobStatus,
  ProcessingMode,
  SystemStatus,
  WorkstationStatus,
} from "./types";
import { SUPPORTED_EXTENSIONS } from "./types";
import { Button, Card, FieldLabel, StatusDot, cn } from "./components/ui";
import { RecordingPicker } from "./components/RecordingPicker";
import { ModeSelector } from "./components/ModeSelector";
import { ConsentDialog } from "./components/ConsentDialog";
import { ProcessingView } from "./components/ProcessingView";
import { DiagnosticsDialog, HelpDialog } from "./components/SupportDialogs";
import { WorkstationSetupDialog } from "./components/WorkstationSetupDialog";
import { ResultsView } from "./components/ResultsView";
import { ErrorView } from "./components/ErrorView";

const JOB_STORAGE = "meeting-documents.current-job";
const CONSENT_STORAGE = "meeting-documents.deepseek-consent";

export function App() {
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [systemError, setSystemError] = useState("");
  const [inputPath, setInputPath] = useState("");
  const [outputRoot, setOutputRoot] = useState("");
  const [mode, setMode] = useState<ProcessingMode>("deepseek");
  const [helpOpen, setHelpOpen] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [workstation, setWorkstation] = useState<WorkstationStatus | null>(null);
  const [workstationError, setWorkstationError] = useState("");
  const [workstationOpen, setWorkstationOpen] = useState(false);
  const [checkingWorkstation, setCheckingWorkstation] = useState(false);
  const [checkingSystem, setCheckingSystem] = useState(false);
  const [consentRemembered, setConsentRemembered] = useState(() => localStorage.getItem(CONSENT_STORAGE) === "yes");
  const [model, setModel] = useState("deepseek-v4-flash");
  const [speakerMode, setSpeakerMode] = useState<"auto" | "known">("auto");
  const [speakerCount, setSpeakerCount] = useState(4);
  const [jobDir, setJobDir] = useState(
    () => localStorage.getItem(JOB_STORAGE) ?? "",
  );
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [consentOpen, setConsentOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const stored = localStorage.getItem("meeting-documents.theme");
    if (stored === "light" || stored === "dark") return stored;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  const [formError, setFormError] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("meeting-documents.theme", theme);
  }, [theme]);

  const refreshSystem = useCallback(async (startOllama = false) => {
    setCheckingSystem(true);
    setSystemError("");
    try {
      const nextSystem = await getSystemStatus(startOllama);
      setSystem(nextSystem);
      if (!nextSystem.deepseek_configured) {
        setMode("local");
        const preferred = ["gemma4:12b", "gemma4:26b", "gemma4:e4b"]
          .find((name) => nextSystem.ollama_models.includes(name))
          ?? nextSystem.ollama_models.find((name) => !/embed/i.test(name));
        if (preferred) setModel(preferred);
      }
    } catch (error) {
      setSystemError(normalizeError(error));
    } finally {
      setCheckingSystem(false);
    }
  }, []);

  const refreshWorkstation = useCallback(async () => {
    setCheckingWorkstation(true);
    setWorkstationError("");
    try {
      const next = await getWorkstationStatus();
      setWorkstation(next);
      if (
        !next.ready ||
        ["RUNNING", "PAUSED_REBOOT"].includes(next.setup.status)
      ) {
        setWorkstationOpen(true);
      }
    } catch (error) {
      setWorkstationError(normalizeError(error));
    } finally {
      setCheckingWorkstation(false);
    }
  }, []);

  useEffect(() => {
    void refreshWorkstation();
  }, [refreshWorkstation]);

  useEffect(() => {
    void refreshSystem(false);
    getDefaultOutputRoot().then(setOutputRoot).catch((error) => setSystemError(normalizeError(error)));
  }, [refreshSystem]);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    getCurrentWebview()
      .onDragDropEvent((event) => {
        if (disposed) return;
        if (event.payload.type === "over") setDragging(true);
        if (event.payload.type === "leave") setDragging(false);
        if (event.payload.type === "drop") {
          setDragging(false);
          const path = event.payload.paths[0];
          if (path) {
            const extension = path.split(".").pop()?.toLowerCase() ?? "";
            if (SUPPORTED_EXTENSIONS.includes(extension)) {
              setInputPath(path);
              setFormError("");
            } else {
              setFormError("Выберите поддерживаемый аудио- или видеофайл.");
            }
          }
        }
      })
      .then((stop) => {
        unlisten = stop;
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  const refreshStatus = useCallback(async () => {
    if (!jobDir) return;
    try {
      const next = await getJobStatus(jobDir);
      setStatus(next);
    } catch (error) {
      if (!status) {
        localStorage.removeItem(JOB_STORAGE);
        setJobDir("");
      }
      console.error(error);
    }
  }, [jobDir, status]);

  useEffect(() => {
    if (!jobDir) return;
    void refreshStatus();
    const timer = window.setInterval(() => void refreshStatus(), 2000);
    return () => window.clearInterval(timer);
  }, [jobDir, refreshStatus]);

  const running =
    status &&
    !["COMPLETE", "FAILED", "CANCELLED"].includes(status.state);
  const inputName = useMemo(() => (
    inputPath.split(/[\\/]/).pop() || status?.input_filename || "Запись совещания"
  ), [inputPath, status?.input_filename]);
  const modeReady =
    mode === "deepseek"
      ? Boolean(system?.deepseek_configured)
      : Boolean(system?.ollama && system.ollama_models.length);
  const coreReady = Boolean(
    system?.ffmpeg &&
      system.wsl &&
      system.nvidia &&
      system.windows_python &&
      system.docs_python &&
      system.moss_python &&
      system.qwen_python,
  );

  function changeMode(next: ProcessingMode) {
    setMode(next);
    setModel(next === "deepseek" ? "deepseek-v4-flash" : "gemma4:12b");
    if (next === "local") void refreshSystem(true);
    setFormError("");
  }

  async function launch(cloudConsent = false) {
    setFormError("");
    if (!inputPath) {
      setFormError("Сначала выберите запись совещания.");
      return;
    }
    if (!outputRoot) {
      setFormError("Выберите папку для документов.");
      return;
    }
    if (!coreReady || !modeReady) {
      setFormError("Выбранный режим пока не готов. Проверьте статус системы.");
      return;
    }
    if (mode === "deepseek" && !cloudConsent) {
      if (!consentRemembered) {
        setConsentOpen(true);
        return;
      }
      cloudConsent = true;
    }
    setStarting(true);
    try {
      const result = await startJob({
        inputPath,
        outputRoot,
        mode,
        model,
        speakerCount: speakerMode === "known" ? speakerCount : null,
        cloudConsent: mode === "deepseek" ? cloudConsent : false,
      });
      setJobDir(result.job_dir);
      localStorage.setItem(JOB_STORAGE, result.job_dir);
      await new Promise((resolve) => setTimeout(resolve, 400));
      setStatus(await getJobStatus(result.job_dir));
    } catch (error) {
      setFormError(normalizeError(error));
    } finally {
      setStarting(false);
    }
  }

  async function confirmConsent(remember: boolean) {
    if (remember) {
      localStorage.setItem(CONSENT_STORAGE, "yes");
      setConsentRemembered(true);
    }
    setConsentOpen(false);
    await launch(true);
  }

  async function cancel() {
    if (!jobDir) return;
    setCancelling(true);
    try {
      await cancelJob(jobDir);
      await refreshStatus();
    } finally {
      setCancelling(false);
    }
  }

  async function retry() {
    if (!jobDir) return;
    setRetrying(true);
    try {
      await resumeJob(jobDir);
      await new Promise((resolve) => setTimeout(resolve, 500));
      await refreshStatus();
    } catch (error) {
      setFormError(normalizeError(error));
    } finally {
      setRetrying(false);
    }
  }

  function reset() {
    localStorage.removeItem(JOB_STORAGE);
    setJobDir("");
    setStatus(null);
    setInputPath("");
    setFormError("");
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <button className="brand" type="button" onClick={() => !running && reset()}>
          <span className="brand-mark" aria-hidden>
            <span /><span /><span /><span /><span />
          </span>
          <span>
            <strong>Документы встречи</strong>
            <em>расшифровка и протокол</em>
          </span>
        </button>
        <nav className="header-actions" aria-label="Приложение">
          <button className="system-pill" type="button" title={systemError || "Состояние компонентов"} onClick={() => setDiagnosticsOpen(true)}>
            <StatusDot tone={coreReady && modeReady ? "good" : "warn"} />
            {coreReady && modeReady ? "Система готова" : "Нужна настройка"}
          </button>
          <button
            className="icon-button"
            type="button"
            aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button className="icon-button" type="button" aria-label="Справка" onClick={() => setHelpOpen(true)}>
            <HelpCircle size={18} />
          </button>
        </nav>
      </header>

      <main>
        <AnimatePresence mode="wait">
          {!jobDir && (
            <motion.div
              className="workspace ready-workspace"
              key="ready"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
            >
              <div className="welcome">
                <span className="eyebrow">Новая встреча</span>
                <h1>Из записи — в готовые документы</h1>
                <p>
                  Выберите аудио или видео. Программа распознает речь, разделит
                  говорящих и подготовит четыре файла Word.
                </p>
              </div>

              <Card className="setup-card">
                <section className="section-block recording-section">
                  <div className="section-heading">
                    <div>
                      <span className="step-number">01</span>
                      <h2>Запись совещания</h2>
                    </div>
                    <span className="section-hint">Аудио и видео · до 5 часов</span>
                  </div>
                  <RecordingPicker
                    value={inputPath}
                    onChange={setInputPath}
                    dragging={dragging}
                  />
                </section>

                <ModeSelector
                  mode={mode}
                  onModeChange={changeMode}
                  model={model}
                  onModelChange={setModel}
                  system={system}
                />

                <section className="section-block options-section">
                  <div className="section-heading">
                    <div>
                      <span className="step-number">03</span>
                      <h2>Результат</h2>
                    </div>
                    <span className="section-hint">4 документа Word</span>
                  </div>

                  <div className="option-grid">
                    <div className="option-field">
                      <FieldLabel>Говорящие</FieldLabel>
                      <div className="segmented">
                        <button
                          type="button"
                          className={cn(speakerMode === "auto" && "active")}
                          onClick={() => setSpeakerMode("auto")}
                        >
                          <Users size={16} /> Автоматически
                        </button>
                        <button
                          type="button"
                          className={cn(speakerMode === "known" && "active")}
                          onClick={() => setSpeakerMode("known")}
                        >
                          Известно
                        </button>
                      </div>
                      {speakerMode === "known" && (
                        <label className="speaker-count">
                          Количество
                          <input
                            type="number"
                            min={1}
                            max={20}
                            value={speakerCount}
                            onChange={(event) =>
                              setSpeakerCount(Number(event.target.value))
                            }
                          />
                        </label>
                      )}
                    </div>

                    <div className="option-field">
                      <FieldLabel>Папка для документов</FieldLabel>
                      <button
                        type="button"
                        className="folder-field"
                        onClick={async () => {
                          const path = await chooseOutputFolder();
                          if (path) setOutputRoot(path);
                        }}
                      >
                        <FolderOpen size={18} />
                        <span title={outputRoot}>{outputRoot || "Выбрать папку"}</span>
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </div>
                </section>

                {formError && (
                  <div className="form-error" role="alert">
                    <Activity size={17} />
                    {formError}
                  </div>
                )}

                <div className="start-row">
                  <div className="privacy-summary">
                    <ShieldCheck size={19} />
                    <span>
                      <strong>Определение говорящих обязательно</strong>
                      {mode === "deepseek"
                        ? "Аудио останется на компьютере"
                        : "Вся обработка останется на компьютере"}
                    </span>
                  </div>
                  <Button
                    className="start-button"
                    onClick={() => void launch(false)}
                    busy={starting}
                  >
                    <Headphones size={19} />
                    Создать документы
                    <ChevronRight size={18} />
                  </Button>
                </div>
              </Card>
            </motion.div>
          )}

          {jobDir && running && status && (
            <ProcessingView
              key="processing"
              status={status}
              inputName={inputName}
              modeLabel={status.cloud_used ? "DeepSeek API" : "Локально"}
              onCancel={() => void cancel()}
              cancelling={cancelling}
              onOpenLogs={() => void openLogsFolder(jobDir)}
            />
          )}

          {jobDir && status?.state === "COMPLETE" && (
            <ResultsView
              key="results"
              status={status}
              inputName={inputName}
              onOpenDocument={(document: JobDocument) =>
                void openDocument(jobDir, document.path)
              }
              onOpenFolder={() => void openJobFolder(jobDir)}
              onNewJob={reset}
            />
          )}

          {jobDir &&
            status &&
            ["FAILED", "CANCELLED"].includes(status.state) && (
              <ErrorView
                key="attention"
                status={status}
                onRetry={() => void retry()}
                onOpenLogs={() => void openLogsFolder(jobDir)}
                onNewJob={reset}
                retrying={retrying}
              />
            )}
        </AnimatePresence>
      </main>

      <footer className="app-footer">
        <span>Meeting Documents · рабочая станция</span>
        <button type="button" onClick={() => setDiagnosticsOpen(true)}>
          <Settings2 size={14} /> Диагностика
        </button>
      </footer>

      <HelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
      <DiagnosticsDialog
        open={diagnosticsOpen}
        onOpenChange={setDiagnosticsOpen}
        system={system}
        error={systemError}
        mode={mode}
        checking={checkingSystem}
        consentRemembered={consentRemembered}
        onRefresh={(startOllama) => void refreshSystem(startOllama)}
        onForgetConsent={() => {
          localStorage.removeItem(CONSENT_STORAGE);
          setConsentRemembered(false);
        }}
        onOpenSetup={() => {
          setDiagnosticsOpen(false);
          setWorkstationOpen(true);
        }}
      />

      <WorkstationSetupDialog
        open={workstationOpen}
        onOpenChange={setWorkstationOpen}
        status={workstation}
        error={workstationError}
        refreshing={checkingWorkstation}
        onRefresh={() => void refreshWorkstation()}
        onInstalled={() => {
          void refreshSystem(false);
        }}
      />

      <ConsentDialog
        open={consentOpen}
        onOpenChange={setConsentOpen}
        onConfirm={(remember) => void confirmConsent(remember)}
      />
    </div>
  );
}

function normalizeError(error: unknown): string {
  const text = String(error);
  try {
    const match = text.match(/\{.*\}/s);
    if (match) {
      const parsed = JSON.parse(match[0]);
      if (parsed.error) return parsed.error;
    }
  } catch {
    // The backend may return a plain localized string.
  }
  return text.replace(/^Error:\s*/, "");
}
