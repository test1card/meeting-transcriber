import * as Dialog from "@radix-ui/react-dialog";
import {
  BookOpen,
  Check,
  CircleAlert,
  Cloud,
  FileText,
  Laptop,
  RefreshCw,
  Settings2,
  Users,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import type { ProcessingMode, SystemStatus } from "../types";
import { Button, StatusDot } from "./ui";

function Shell({
  open,
  onOpenChange,
  icon,
  title,
  description,
  wide = false,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  icon: ReactNode;
  title: string;
  description: string;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild>
              <motion.div
                className="dialog-overlay"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              />
            </Dialog.Overlay>
            <Dialog.Content asChild>
              <motion.div
                className={`dialog-content support-dialog${wide ? " support-dialog-wide" : ""}`}
                initial={{ opacity: 0, y: 12, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.98 }}
              >
                <Dialog.Close className="icon-button dialog-close" aria-label="Закрыть">
                  <X size={18} />
                </Dialog.Close>
                <div className="dialog-icon">{icon}</div>
                <Dialog.Title className="dialog-title">{title}</Dialog.Title>
                <Dialog.Description className="dialog-description">
                  {description}
                </Dialog.Description>
                {children}
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}

export function HelpDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const steps = [
    ["1", "Добавьте запись", "Перетащите аудио или видео длительностью до 5 часов."],
    ["2", "Выберите обработку", "DeepSeek быстрее; локальный режим не отправляет текст наружу."],
    ["3", "Получите Word", "Готовые документы сохранятся в выбранную папку."],
  ];
  const documents = [
    ["Протокол", "решения, поручения, сроки и ответственные"],
    ["Полная стенограмма", "максимально полная речь с говорящими и временем"],
    ["Редакционная версия", "без технических реплик и речевого мусора"],
    ["Сокращённая версия", "только смысл, без повторов"],
  ];
  return (
    <Shell
      open={open}
      onOpenChange={onOpenChange}
      icon={<BookOpen size={24} />}
      title="Как подготовить документы"
      description="Программа распознаёт русскую речь, учитывает отдельные английские слова и обязательно разделяет участников."
      wide
    >
      <div className="help-steps">
        {steps.map(([number, title, text]) => (
          <div className="help-step" key={number}>
            <span>{number}</span>
            <div><strong>{title}</strong><p>{text}</p></div>
          </div>
        ))}
      </div>
      <div className="support-section-title"><FileText size={16} /> Что будет создано</div>
      <div className="help-documents">
        {documents.map(([title, text]) => (
          <div key={title}><Check size={15} /><span><strong>{title}</strong>{text}</span></div>
        ))}
      </div>
      <div className="support-note">
        <Users size={17} />
        <span>Имена людей программа не угадывает: в документах используются метки «Говорящий 1», «Говорящий 2» и далее.</span>
      </div>
      <div className="dialog-actions">
        <Dialog.Close asChild><Button>Понятно</Button></Dialog.Close>
      </div>
    </Shell>
  );
}

function CheckRow({
  ok,
  label,
  detail,
}: {
  ok: boolean;
  label: string;
  detail: string;
}) {
  return (
    <div className="diagnostic-row">
      <StatusDot tone={ok ? "good" : "warn"} />
      <span><strong>{label}</strong><small>{detail}</small></span>
      <em>{ok ? "Готово" : "Нужно настроить"}</em>
    </div>
  );
}

export function DiagnosticsDialog({
  open,
  onOpenSetup,
  onOpenChange,
  system,
  error,
  mode,
  checking,
  consentRemembered,
  onRefresh,
  onForgetConsent,
}: {
  open: boolean;
  onOpenSetup: () => void;
  onOpenChange: (open: boolean) => void;
  system: SystemStatus | null;
  error: string;
  mode: ProcessingMode;
  checking: boolean;
  consentRemembered: boolean;
  onRefresh: (startOllama: boolean) => void;
  onForgetConsent: () => void;
}) {
  const pythonReady = Boolean(
    system?.windows_python && system.docs_python && system.moss_python && system.qwen_python,
  );
  const ollamaReady = Boolean(system?.ollama && system.ollama_models.some((name) => !/embed/i.test(name)));
  return (
    <Shell
      open={open}
      onOpenChange={onOpenChange}
      icon={<Settings2 size={24} />}
      title="Диагностика рабочей станции"
      description="Здесь видно, что готово к обработке и что потребуется настроить."
      wide
    >
      {error && <div className="diagnostic-error"><CircleAlert size={17} />{error}</div>}
      <div className="diagnostic-list" aria-live="polite">
        <CheckRow ok={Boolean(system?.ffmpeg)} label="Медиафайлы" detail="FFmpeg читает аудио и видео" />
        <CheckRow ok={Boolean(system?.wsl && system?.nvidia)} label="Видеокарта" detail="WSL и NVIDIA доступны для распознавания" />
        <CheckRow ok={pythonReady} label="Модели речи" detail="WhisperX, MOSS, Qwen и экспорт Word" />
        <CheckRow
          ok={ollamaReady}
          label="Локальная обработка"
          detail={ollamaReady
            ? `${system?.ollama_models.filter((name) => !/embed/i.test(name)).length} текстовых моделей`
            : system?.ollama_installed ? "Ollama установлена, но ещё не запущена" : "Ollama не найдена"}
        />
        <CheckRow
          ok={Boolean(system?.deepseek_configured)}
          label="DeepSeek API"
          detail={system?.deepseek_configured ? "Ключ API найден" : "Переменная DEEPSEEK_API_KEY не найдена"}
        />
      </div>
      <div className="diagnostic-mode">
        {mode === "local" ? <Laptop size={18} /> : <Cloud size={18} />}
        <span>
          <strong>Сейчас выбран: {mode === "local" ? "локальный режим" : "DeepSeek API"}</strong>
          {mode === "local"
            ? "При обновлении программа попробует сама запустить Ollama."
            : "Во внешний API уходит только распознанный текст, не запись."}
        </span>
      </div>
      <div className="dialog-actions diagnostic-actions">
        {consentRemembered && (
          <Button variant="ghost" onClick={onForgetConsent}>Забыть согласие API</Button>
        )}
        <Button variant="secondary" onClick={onOpenSetup}>
          <Settings2 size={16} /> Модели и установка
        </Button>
        <Button
          variant="secondary"
          busy={checking}
          onClick={() => onRefresh(mode === "local")}
        >
          <RefreshCw size={16} /> Проверить снова
        </Button>
        <Dialog.Close asChild><Button>Закрыть</Button></Dialog.Close>
      </div>
    </Shell>
  );
}
