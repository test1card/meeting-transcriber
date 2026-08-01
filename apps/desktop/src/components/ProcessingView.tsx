import {
  Check,
  ChevronDown,
  Circle,
  Clock3,
  FolderClock,
  LoaderCircle,
  Square,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { JobStatus } from "../types";
import { STAGES } from "../types";
import { Button, Card, cn } from "./ui";

function duration(value: number | null | undefined): string {
  if (value == null) return "считаем…";
  if (value < 60) return "меньше минуты";
  const hours = Math.floor(value / 3600);
  const minutes = Math.ceil((value % 3600) / 60);
  return hours ? `${hours} ч ${minutes} мин` : `${minutes} мин`;
}

export function ProcessingView({
  status,
  inputName,
  modeLabel,
  onCancel,
  cancelling,
  onOpenLogs,
}: {
  status: JobStatus;
  inputName: string;
  modeLabel: string;
  onCancel: () => void;
  cancelling: boolean;
  onOpenLogs: () => void;
}) {
  const [details, setDetails] = useState(false);
  const activeIndex = STAGES.findIndex(([key]) => key === status.stage);
  const progress = Math.round(status.overall_progress * 100);

  return (
    <motion.div
      className="workspace processing-workspace"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
    >
      <div className="processing-top">
        <div>
          <span className="eyebrow">Обработка идёт</span>
          <h1>Готовим документы встречи</h1>
          <p title={inputName}>{inputName}</p>
        </div>
        <div className="time-card">
          <Clock3 size={18} />
          <span>Осталось примерно</span>
          <strong>{duration(status.eta_seconds)}</strong>
        </div>
      </div>

      <Card className="progress-card">
        <div className="progress-summary">
          <div className="progress-ring" style={{ "--progress": `${progress * 3.6}deg` } as React.CSSProperties}>
            <div>
              <strong>{progress}%</strong>
              <span>готово</span>
            </div>
          </div>
          <div className="progress-copy">
            <span className="progress-kicker">{status.stage_label}</span>
            <h2>{status.message}</h2>
            <p>
              {status.current_unit && status.total_units
                ? `Часть ${status.current_unit} из ${status.total_units}`
                : "Текущий этап может занять некоторое время"}
            </p>
            {status.stage_progress != null ? (
              <div className="linear-progress" aria-label={`Этап выполнен на ${Math.round(status.stage_progress * 100)}%`}>
                <motion.span
                  initial={false}
                  animate={{ width: `${status.stage_progress * 100}%` }}
                />
              </div>
            ) : (
              <div className="linear-progress indeterminate" aria-label="Этап выполняется">
                <span />
              </div>
            )}
          </div>
        </div>

        <div className="stage-list">
          {STAGES.map(([key, label], index) => {
            const completed = activeIndex === -1
              ? status.overall_progress >= 1
              : index < activeIndex;
            const active = index === activeIndex;
            return (
              <div className={cn("stage-row", active && "stage-row-active")} key={key}>
                <span className={cn("stage-marker", completed && "stage-complete", active && "stage-active")}>
                  {completed ? (
                    <Check size={14} />
                  ) : active ? (
                    <LoaderCircle size={15} className="spin" />
                  ) : (
                    <Circle size={10} />
                  )}
                </span>
                <span>{label}</span>
                {active && status.current_unit && status.total_units && (
                  <em>{status.current_unit} / {status.total_units}</em>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      <div className="processing-actions">
        <Button
          variant="secondary"
          onClick={onCancel}
          busy={cancelling}
          disabled={status.state === "CANCELLING"}
        >
          <Square size={15} fill="currentColor" />
          Остановить безопасно
        </Button>
        <button
          type="button"
          className="details-toggle"
          onClick={() => setDetails((value) => !value)}
          aria-expanded={details}
        >
          Подробности
          <ChevronDown size={16} className={cn(details && "rotate")} />
        </button>
      </div>

      <AnimatePresence>
        {details && (
          <motion.div
            className="details-panel"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
          >
            <dl>
              <div><dt>Режим</dt><dd>{modeLabel}</dd></div>
              <div><dt>Модель</dt><dd>{status.model}</dd></div>
              <div><dt>Прошло</dt><dd>{duration(status.elapsed_seconds)}</dd></div>
              <div><dt>Говорящие</dt><dd>Обязательное определение</dd></div>
            </dl>
            <Button variant="ghost" size="small" onClick={onOpenLogs}>
              <FolderClock size={16} />
              Открыть технический журнал
            </Button>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
