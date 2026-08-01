import { AlertTriangle, FolderClock, RefreshCw, RotateCcw } from "lucide-react";
import { motion } from "motion/react";
import type { JobStatus } from "../types";
import { Button, Card } from "./ui";

export function ErrorView({
  status,
  onRetry,
  onOpenLogs,
  onNewJob,
  retrying,
}: {
  status: JobStatus;
  onRetry: () => void;
  onOpenLogs: () => void;
  onNewJob: () => void;
  retrying: boolean;
}) {
  const cancelled = status.state === "CANCELLED";
  return (
    <motion.div
      className="workspace attention-workspace"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <Card className="attention-card">
        <div className={`attention-icon ${cancelled ? "attention-muted" : ""}`}>
          <AlertTriangle size={28} />
        </div>
        <span className="eyebrow">{cancelled ? "Остановлено" : "Нужно внимание"}</span>
        <h1>
          {cancelled
            ? "Обработка безопасно остановлена"
            : "Не удалось завершить один из этапов"}
        </h1>
        <p>{status.error?.message ?? status.message}</p>
        <div className="saved-note">
          Уже готовые части сохранены. Повторный запуск продолжит работу с
          контрольной точки.
        </div>
        <div className="attention-actions">
          <Button onClick={onRetry} busy={retrying}>
            <RefreshCw size={17} />
            Продолжить
          </Button>
          <Button variant="secondary" onClick={onOpenLogs}>
            <FolderClock size={17} />
            Технический журнал
          </Button>
          <Button variant="ghost" onClick={onNewJob}>
            <RotateCcw size={17} />
            Новая запись
          </Button>
        </div>
      </Card>
    </motion.div>
  );
}
