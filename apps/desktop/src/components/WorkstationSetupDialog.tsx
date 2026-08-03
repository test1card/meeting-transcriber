import * as Dialog from "@radix-ui/react-dialog";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronRight,
  Cloud,
  Cpu,
  Download,
  Gauge,
  HardDrive,
  LoaderCircle,
  MemoryStick,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  openWorkstationSetupLog,
  startWorkstationSetup,
} from "../lib/backend";
import type {
  WorkstationModel,
  WorkstationPack,
  WorkstationStatus,
} from "../types";
import { Button, StatusDot, cn } from "./ui";

const PACK_ORDER = [
  "deepseek-production",
  "local-efficient",
  "local-proven",
  "local-maximum",
];

const STATUS_LABELS: Record<string, string> = {
  validated_pipeline: "Проверено в конвейере",
  draft_only: "Только черновик",
  compatible_unbenchmarked: "Совместимо, нужен замер",
  postponed_on_16gb: "Медленнее на 16 ГБ",
  adapter_required: "Исследовательская модель",
};

const FIT_LABELS: Record<string, string> = {
  recommended: "Отлично подходит",
  fits: "Подходит",
  slow_offload: "Часть расчётов в оперативной памяти",
  unavailable: "Не подходит",
  api: "Работает через внешний API",
};

const SETUP_STAGES: Record<string, string> = {
  not_started: "Ожидание выбора",
  prerequisites: "Системные компоненты",
  wsl: "Настройка WSL",
  runtime: "Файлы приложения",
  python: "Среды Python",
  models: "Загрузка моделей",
  verification: "Итоговая проверка",
  complete: "Компьютер готов к работе",
};

function packBadge(pack: WorkstationPack) {
  if (pack.id === "deepseek-production") return "Лучшее качество через API";
  if (pack.id === "local-efficient") return "Рекомендуемый локальный вариант";
  if (pack.id === "local-proven") return "Только черновик";
  return "Максимальная локальная";
}

function packIcon(pack: WorkstationPack) {
  if (pack.id === "deepseek-production") return <Cloud size={20} />;
  if (pack.id === "local-efficient") return <Zap size={20} />;
  if (pack.id === "local-proven") return <ShieldCheck size={20} />;
  return <Sparkles size={20} />;
}

function shortCpu(name: string) {
  return name.replace(/\s+/g, " ").replace(/\s+Processor\s*$/i, "").trim();
}

function formatGb(value: number) {
  return new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 1,
  }).format(value);
}

function ModelRow({
  model,
  selected,
  locked,
  multiple = false,
  onToggle,
}: {
  model: WorkstationModel;
  selected: boolean;
  locked: boolean;
  multiple?: boolean;
  onToggle: () => void;
}) {
  const warning = model.fit.status === "slow_offload";
  return (
    <label
      className={cn(
        "model-row",
        selected && "model-row-selected",
        warning && "model-row-warning",
        locked && "model-row-locked",
      )}
    >
      <input
        type={locked || multiple ? "checkbox" : "radio"}
        checked={selected}
        disabled={locked}
        onChange={onToggle}
      />
      <span className="model-check">
        {selected && <Check size={13} strokeWidth={3} />}
      </span>
      <span className="model-copy">
        <span className="model-title-line">
          <strong>{model.display_name}</strong>
          {model.installed && <em className="installed-badge">Установлено</em>}
        </span>
        <small>{model.rationale}</small>
        <span className="model-badges">
          <em className={`fit-${model.fit.status}`}>
            {FIT_LABELS[model.fit.status] ?? model.fit.label}
          </em>
          <em>{STATUS_LABELS[model.production_status] ?? model.production_status}</em>
          {model.download_gb > 0 && <em>{formatGb(model.download_gb)} ГБ</em>}
        </span>
      </span>
    </label>
  );
}

export function WorkstationSetupDialog({
  open,
  onOpenChange,
  status,
  error,
  refreshing,
  onRefresh,
  onInstalled,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  status: WorkstationStatus | null;
  error: string;
  refreshing: boolean;
  onRefresh: () => void;
  onInstalled: () => void;
}) {
  const [packId, setPackId] = useState("local-efficient");
  const [choiceByPack, setChoiceByPack] = useState<Record<string, string>>({
    "deepseek-production": "deepseek-v4-flash",
    "local-efficient": "gemma4-12b",
  });
  const [optional, setOptional] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [launchError, setLaunchError] = useState("");
  const [editingSelection, setEditingSelection] = useState(false);

  const packs = useMemo(
    () =>
      [...(status?.packs ?? [])].sort(
        (a, b) => PACK_ORDER.indexOf(a.id) - PACK_ORDER.indexOf(b.id),
      ),
    [status?.packs],
  );
  const pack = packs.find((item) => item.id === packId) ?? packs[0];
  const modelMap = useMemo(
    () => new Map((status?.models ?? []).map((model) => [model.id, model])),
    [status?.models],
  );
  const requiredModels = (pack?.required_model_ids ?? [])
    .map((id) => modelMap.get(id))
    .filter((item): item is WorkstationModel => Boolean(item));
  const optionalModels = (pack?.optional_model_ids ?? [])
    .map((id) => modelMap.get(id))
    .filter((item): item is WorkstationModel => Boolean(item));
  const apiModels = (pack?.api_model_ids ?? [])
    .map((id) => modelMap.get(id))
    .filter((item): item is WorkstationModel => Boolean(item));
  const selectableLocal = requiredModels.filter(
    (model) => model.selectable && model.role === "local_documents",
  );
  const selectableModels = apiModels.length ? apiModels : selectableLocal;
  const selectedChoice =
    choiceByPack[pack?.id] ??
    (apiModels.find((model) => model.id === "deepseek-v4-flash") ??
      selectableModels[0])?.id;
  const completionNotified = useRef(false);
  const setupActive = ["RUNNING"].includes(
    status?.setup.status ?? "",
  );

  useEffect(() => {
    if (!open || !setupActive) return;
    const timer = window.setInterval(onRefresh, 2000);
    return () => window.clearInterval(timer);
  }, [open, onRefresh, setupActive]);

  useEffect(() => {
    if (status?.setup.status !== "COMPLETE") {
      completionNotified.current = false;
      return;
    }
    if (completionNotified.current) return;
    completionNotified.current = true;
    onInstalled();
  }, [onInstalled, status?.setup.status]);

  async function beginSetup() {
    if (!pack) return;
    setStarting(true);
    setLaunchError("");
    const retryPrevious = !editingSelection && ["PARTIAL", "FAILED", "PAUSED_REBOOT"].includes(
      status?.setup.status ?? "",
    );
    const targetPackId = retryPrevious && status?.setup.pack_id
      ? status.setup.pack_id
      : pack.id;
    const modelIds = retryPrevious && status?.setup.selected_model_ids?.length
      ? status.setup.selected_model_ids
      : [
          ...(selectedChoice ? [selectedChoice] : []),
          ...optional,
        ];
    try {
      await startWorkstationSetup(targetPackId, modelIds);
      setEditingSelection(false);
      onRefresh();
    } catch (caught) {
      setLaunchError(String(caught).replace(/^Error:\s*/, ""));
    } finally {
      setStarting(false);
    }
  }

  function choosePack(next: WorkstationPack) {
    setPackId(next.id);
    setOptional([]);
    if (!choiceByPack[next.id]) {
      const candidates = next.api_model_ids.length
        ? next.api_model_ids
        : next.required_model_ids.filter(
            (id) => modelMap.get(id)?.role === "local_documents",
          );
      const preferred =
        candidates.find((id) => id === "deepseek-v4-flash") ?? candidates[0];
      if (preferred) {
        setChoiceByPack((current) => ({ ...current, [next.id]: preferred }));
      }
    }
  }

  const hardware = status?.hardware;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild>
              <motion.div
                className="dialog-overlay setup-overlay"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              />
            </Dialog.Overlay>
            <Dialog.Content asChild>
              <motion.div
                className="workstation-dialog"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <header className="workstation-header">
                  <div className="dialog-icon"><Gauge size={24} /></div>
                  <div>
                    <Dialog.Title>Подготовка компьютера</Dialog.Title>
                    <Dialog.Description>
                      Программа определила характеристики компьютера и подобрала подходящие
                      модели для русскоязычных совещаний.
                    </Dialog.Description>
                  </div>
                  <span className="catalog-date">
                    Каталог {status?.catalog.as_of?.split("-").reverse().join(".") ?? "загружается"}
                  </span>
                  <Dialog.Close className="icon-button dialog-close" aria-label="Закрыть">
                    <X size={18} />
                  </Dialog.Close>
                </header>

                <div className="workstation-scroll">
                  {(error || launchError) && (
                    <div className="setup-error" role="alert">
                      <AlertTriangle size={18} />
                      <span>{launchError || error}</span>
                    </div>
                  )}

                  {!status ? (
                    <div className="setup-loading">
                      <LoaderCircle className="spin" size={28} />
                      <strong>Проверяем компьютер…</strong>
                      <span>Видеокарта, память, WSL и доступное место</span>
                    </div>
                  ) : (
                    <>
                      <section className="hardware-panel">
                        <div className="hardware-heading">
                          <div>
                            <span className="eyebrow">Этот компьютер</span>
                            <h2>{status.hardware_class.label}</h2>
                            <p>{status.hardware_class.recommendation}</p>
                          </div>
                          <span className={cn("readiness-badge", status.ready && "ready")}>
                            <StatusDot tone={status.ready ? "good" : "warn"} />
                            {status.ready ? "Базовая система готова" : "Требуется установка"}
                          </span>
                        </div>
                        <div className="hardware-grid">
                          <div><Cpu /><span><small>Процессор</small><strong>{shortCpu(hardware!.cpu.name)}</strong></span></div>
                          <div><MemoryStick /><span><small>Оперативная память</small><strong>{formatGb(hardware!.ram_gb)} ГБ</strong></span></div>
                          <div><Gauge /><span><small>Видеокарта</small><strong>{hardware!.nvidia.name || "Не найдена"}</strong><em>{formatGb(hardware!.nvidia.vram_gb)} ГБ VRAM</em></span></div>
                          <div><HardDrive /><span><small>Свободное место</small><strong>{formatGb(hardware!.disk.free_gb)} ГБ</strong></span></div>
                        </div>
                      </section>

                      {!editingSelection && (setupActive || ["FAILED", "PARTIAL", "PAUSED_REBOOT", "COMPLETE"].includes(status.setup.status)) ? (
                        <section className="setup-progress-card">
                          <div className={cn("setup-progress-icon", status.setup.status.toLowerCase())}>
                            {status.setup.status === "COMPLETE" ? (
                              <CheckCircle2 size={27} />
                            ) : ["FAILED", "PARTIAL"].includes(status.setup.status) ? (
                              <AlertTriangle size={27} />
                            ) : status.setup.reboot_required ? (
                              <RotateCw size={27} />
                            ) : (
                              <Download size={27} />
                            )}
                          </div>
                          <div className="setup-progress-copy">
                            <span className="eyebrow">
                              {SETUP_STAGES[status.setup.stage] ?? status.setup.stage}
                            </span>
                            <h2>
                              {status.setup.reboot_required && !status.hardware.wsl.distro_ready
                                ? "Нужно перезагрузить Windows"
                                : status.setup.status === "PAUSED_REBOOT"
                                  ? "Можно продолжить настройку"
                                  : status.setup.status === "COMPLETE"
                                  ? "Компьютер готов к работе"
                                  : status.setup.status === "PARTIAL"
                                    ? "\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043a\u0430 \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0430 \u0447\u0430\u0441\u0442\u0438\u0447\u043d\u043e"
                                  : status.setup.status === "FAILED"
                                    ? "Установка остановилась"
                                    : "Устанавливаем и проверяем компоненты"}
                            </h2>
                            <p>
                              {["FAILED", "PARTIAL"].includes(status.setup.status) && status.setup.error
                                ? typeof status.setup.error === "string"
                                  ? status.setup.error
                                  : status.setup.error.message ??
                                    status.setup.message
                                : status.setup.message}
                            </p>
                            <div className="setup-progress-track">
                              <motion.span
                                animate={{ width: `${Math.max(2, status.setup.progress * 100)}%` }}
                              />
                            </div>
                            <small>{Math.round(status.setup.progress * 100)}%</small>
                            {status.setup.model_results?.length > 0 && (
                              <div className="setup-result-list" aria-label="Model installation results">
                                {status.setup.model_results.map((result) => (
                                  <div
                                    className={cn("setup-result-row", `result-${result.status}`)}
                                    key={result.id}
                                  >
                                    <span className="setup-result-icon">
                                      {["ready", "skipped"].includes(result.status) ? (
                                        <CheckCircle2 size={16} />
                                      ) : result.status === "failed" ? (
                                        <AlertTriangle size={16} />
                                      ) : result.status === "installing" ? (
                                        <LoaderCircle className="spin" size={16} />
                                      ) : (
                                        <Download size={16} />
                                      )}
                                    </span>
                                    <span className="setup-result-copy">
                                      <strong>{result.label}</strong>
                                      <small>{result.detail}</small>
                                    </span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </section>
                      ) : (
                        <>
                          <section className="setup-section">
                            <div className="setup-section-heading">
                              <div>
                                <span className="eyebrow">Шаг 1</span>
                                <h2>Выберите качество обработки</h2>
                              </div>
                              <p>Распознавание речи и определение говорящих выполняются на компьютере.</p>
                            </div>
                            <div className="pack-grid">
                              {packs.map((item) => (
                                <button
                                  type="button"
                                  className={cn("pack-card", item.id === pack?.id && "pack-card-selected")}
                                  onClick={() => choosePack(item)}
                                  key={item.id}
                                >
                                  <span className="pack-icon">{packIcon(item)}</span>
                                  <span className="pack-badge">{packBadge(item)}</span>
                                  <strong>{item.label}</strong>
                                  <p>{item.description}</p>
                                  <span className="pack-meta">
                                    <Download size={13} /> {formatGb(item.estimated_download_gb)} ГБ
                                    <i />
                                    {item.estimated_installed_gb} ГБ после установки
                                  </span>
                                  {item.recommended && (
                                    <span className="recommended-mark"><Check size={13} /> Подходит этому компьютеру</span>
                                  )}
                                  <ChevronRight className="pack-chevron" size={17} />
                                </button>
                              ))}
                            </div>
                          </section>

                          <section className="setup-section model-section">
                            <div className="setup-section-heading">
                              <div>
                                <span className="eyebrow">Шаг 2</span>
                                <h2>Состав набора</h2>
                              </div>
                              <p>Обязательные модели защищены от случайного отключения.</p>
                            </div>
                            <div className="model-list">
                              {requiredModels
                                .filter((model) => !model.selectable)
                                .map((model) => (
                                  <ModelRow
                                    model={model}
                                    selected
                                    locked
                                    onToggle={() => undefined}
                                    key={model.id}
                                  />
                                ))}
                              {selectableModels.map((model) => (
                                <ModelRow
                                  model={model}
                                  selected={selectedChoice === model.id}
                                  locked={false}
                                  onToggle={() =>
                                    setChoiceByPack((current) => ({
                                      ...current,
                                      [pack!.id]: model.id,
                                    }))
                                  }
                                  key={model.id}
                                />
                              ))}
                              {optionalModels.map((model) => (
                                <ModelRow
                                  model={model}
                                  selected={optional.includes(model.id)}
                                  locked={false}
                                  multiple
                                  onToggle={() =>
                                    setOptional((current) =>
                                      current.includes(model.id)
                                        ? current.filter((id) => id !== model.id)
                                        : [...current, model.id],
                                    )
                                  }
                                  key={model.id}
                                />
                              ))}
                            </div>
                          </section>
                        </>
                      )}

                      <div className="model-truth-note">
                        <ShieldCheck size={18} />
                        <p>
                          <strong>Что означает «лучше».</strong> Рекомендация учитывает
                          VRAM, размер весов, поддержку русского и состояние интеграции.
                          Фактическая точность подтверждается только сравнением с
                          проверенной человеком стенограммой: WER/CER/cpWER и DER/JER.
                        </p>
                      </div>
                    </>
                  )}
                </div>

                <footer className="workstation-actions">
                  <Button variant="ghost" onClick={() => void openWorkstationSetupLog()}>
                    Открыть журнал
                  </Button>
                  <Button variant="secondary" busy={refreshing} onClick={onRefresh}>
                    <RefreshCw size={16} /> Проверить снова
                  </Button>
                  {["FAILED", "PARTIAL"].includes(status?.setup.status ?? "") && !editingSelection && (
                    <Button variant="secondary" onClick={() => setEditingSelection(true)}>
                      <RefreshCw size={16} />
                      {"\u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c \u043d\u0430\u0431\u043e\u0440"}
                    </Button>
                  )}

                  {status?.setup.status === "COMPLETE" ? (
                    <Dialog.Close asChild><Button>Готово</Button></Dialog.Close>
                  ) : status?.setup.reboot_required && !status?.hardware.wsl.distro_ready ? (
                    <Button disabled><RotateCw size={16} /> Перезагрузите компьютер</Button>
                  ) : (
                    <Button
                      busy={starting || setupActive}
                      disabled={!status || !pack || setupActive}
                      onClick={() => void beginSetup()}
                    >
                      <Download size={16} />
                      {status?.setup.status === "PAUSED_REBOOT" ? "Продолжить настройку" : status?.ready ? "Установить выбранные модели" : "Установить и настроить"}
                    </Button>
                  )}
                </footer>
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}
