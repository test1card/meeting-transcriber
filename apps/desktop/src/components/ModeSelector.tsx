import { Check, Cloud, Cpu, ShieldCheck, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import type { ProcessingMode, SystemStatus } from "../types";
import { cn, StatusDot } from "./ui";

export function ModeSelector({
  mode,
  onModeChange,
  model,
  onModelChange,
  system,
}: {
  mode: ProcessingMode;
  onModeChange: (mode: ProcessingMode) => void;
  model: string;
  onModelChange: (model: string) => void;
  system: SystemStatus | null;
}) {
  const localModels = (system?.ollama_models ?? [])
    .filter((name) => !/embed/i.test(name))
    .sort((a, b) => {
      const priority = ["gemma4:12b", "gemma4:26b", "gemma4:e4b"];
      const left = priority.indexOf(a);
      const right = priority.indexOf(b);
      if (left >= 0 || right >= 0) {
        return (left >= 0 ? left : priority.length) - (right >= 0 ? right : priority.length);
      }
      return a.localeCompare(b);
    });
  if (localModels.length === 0) localModels.push("gemma4:12b");
  const apiModels = ["deepseek-v4-flash", "deepseek-v4-pro"];
  const models = mode === "local" ? localModels : apiModels;
  const selected = models.includes(model) ? model : models[0];

  return (
    <section className="section-block" aria-labelledby="mode-heading">
      <div className="section-heading">
        <div>
          <span className="step-number">02</span>
          <h2 id="mode-heading">Как обработать запись</h2>
        </div>
        <span className="section-hint">Запись не покидает компьютер</span>
      </div>

      <div className="mode-grid" role="radiogroup" aria-label="Режим обработки">
        <ModeCard
          active={mode === "local"}
          onClick={() => {
            onModeChange("local");
            if (!localModels.includes(model)) onModelChange(localModels[0]);
          }}
          icon={<Cpu size={22} />}
          title="Локально"
          badge="Данные остаются здесь"
          description="Запись и текст не отправляются в интернет — подходит для закрытых совещаний."
          status={
            <>
              <StatusDot tone={system?.ollama ? "good" : "warn"} />
              {system?.ollama ? "Локальная обработка готова" : "Локальная обработка недоступна"}
            </>
          }
        />
        <ModeCard
          active={mode === "deepseek"}
          disabled={!system?.deepseek_configured}
          onClick={() => {
            onModeChange("deepseek");
            if (!apiModels.includes(model)) onModelChange(apiModels[0]);
          }}
          icon={<Cloud size={22} />}
          title="DeepSeek API"
          badge={system?.deepseek_configured ? "Лучшее качество" : "Нужен свой ключ"}
          description="Лучше вычитывает стенограмму и оформляет протокол."
          status={
            <>
              <StatusDot tone={system?.deepseek_configured ? "good" : "warn"} />
              {system?.deepseek_configured ? "Ключ найден" : "Ключ не найден"}
            </>
          }
        />
      </div>

      <div className="model-row">
        <div>
          <label htmlFor="model-select">Модель</label>
          <p>
            {mode === "local"
              ? "Работает установленная локальная модель"
              : "В DeepSeek отправляется только текст стенограммы"}
          </p>
        </div>
        <div className="select-wrap">
          <Sparkles size={16} aria-hidden />
          <select
            id="model-select"
            value={selected}
            onChange={(event) => onModelChange(event.target.value)}
          >
            {models.map((name) => (
              <option key={name} value={name}>
                {name}
                {name === "gemma4:12b" ? " — основной локальный вариант" : ""}
                {name === "gemma4:26b" ? " — заметно медленнее" : ""}
                {name === "gemma4:e4b" ? " — только черновик" : ""}
                {name === "deepseek-v4-flash" ? " — быстро" : ""}
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  );
}

function ModeCard({
  active,
  disabled = false,
  onClick,
  icon,
  title,
  badge,
  description,
  status,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  badge: string;
  description: string;
  status: React.ReactNode;
}) {
  return (
    <motion.button
      type="button"
      role="radio"
      aria-checked={active}
      aria-disabled={disabled}
      disabled={disabled}
      className={cn("mode-card", active && "mode-card-active")}
      onClick={onClick}
      whileTap={{ scale: 0.992 }}
    >
      <span className="mode-icon">{icon}</span>
      <span className="mode-copy">
        <span className="mode-title-row">
          <strong>{title}</strong>
          <span className="mode-badge">{badge}</span>
        </span>
        <span className="mode-description">{description}</span>
        <span className="mode-status">{status}</span>
      </span>
      <span className="radio-check">{active && <Check size={15} />}</span>
      {active && (
        <motion.span
          layoutId="active-mode"
          className="mode-highlight"
          transition={{ type: "spring", stiffness: 420, damping: 36 }}
        />
      )}
    </motion.button>
  );
}
