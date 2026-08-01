import {
  ArrowRight,
  Check,
  ExternalLink,
  FileCheck2,
  FileClock,
  FileText,
  FolderOpen,
  ListChecks,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { motion } from "motion/react";
import type { JobDocument, JobStatus } from "../types";
import { Button } from "./ui";

const icons = {
  minutes: ListChecks,
  full: FileText,
  edited: Sparkles,
  condensed: FileClock,
};

function formatElapsed(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.max(1, Math.round((seconds % 3600) / 60));
  return hours ? `${hours} ч ${minutes} мин` : `${minutes} мин`;
}

export function ResultsView({
  status,
  inputName,
  onOpenDocument,
  onOpenFolder,
  onNewJob,
}: {
  status: JobStatus;
  inputName: string;
  onOpenDocument: (document: JobDocument) => void;
  onOpenFolder: () => void;
  onNewJob: () => void;
}) {
  return (
    <motion.div
      className="workspace results-workspace"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className="success-hero">
        <motion.div
          className="success-mark"
          initial={{ scale: 0.6, rotate: -10 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ type: "spring", stiffness: 380, damping: 24 }}
        >
          <Check size={29} strokeWidth={2.5} />
        </motion.div>
        <span className="eyebrow">Готово</span>
        <h1>Материалы по встрече готовы</h1>
        <p>{inputName}</p>
        <div className="result-meta">
          <span>{status.cloud_used ? "DeepSeek API" : "Локальная обработка"}</span>
          <i />
          <span>{status.model}</span>
          <i />
          <span>{formatElapsed(status.elapsed_seconds)}</span>
        </div>
      </div>

      <div className="document-grid">
        {status.documents.map((document, index) => {
          const Icon = icons[document.key] ?? FileCheck2;
          return (
            <motion.article
              className="document-card"
              key={document.key}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.06 * index }}
            >
              <div className={`document-icon document-icon-${document.key}`}>
                <Icon size={23} />
              </div>
              <div className="document-number">0{index + 1}</div>
              <h2>{document.title}</h2>
              <p>{document.description}</p>
              {document.key !== "full" && (
                <span className="edited-badge">
                  {document.key === "minutes" ? "Структурировано" : "Не дословно"}
                </span>
              )}
              <button
                type="button"
                className="document-open"
                onClick={() => onOpenDocument(document)}
              >
                Открыть в Word
                <ExternalLink size={15} />
              </button>
            </motion.article>
          );
        })}
      </div>

      <div className="result-actions">
        <Button onClick={onOpenFolder}>
          <FolderOpen size={18} />
          Открыть папку
        </Button>
        <Button variant="secondary" onClick={onNewJob}>
          <RotateCcw size={17} />
          Обработать другую запись
        </Button>
      </div>

      <div className="verification-note">
        <FileCheck2 size={18} />
        <p>
          Для важных решений, фамилий, чисел и сроков сверяйтесь с полной
          стенограммой и исходной записью.
        </p>
        <ArrowRight size={17} />
      </div>
    </motion.div>
  );
}
