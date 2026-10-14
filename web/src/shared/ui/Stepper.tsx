/**
 * Индикатор шагов (Д3 §4.1, §7): Запрос → Уточнения → Каркас → Утверждение → Комплект.
 * Шаги впереди недоступного не кликабельны: через Human Gate не перескочить.
 */

import { cx } from "./cx";
import { T } from "../i18n/ru";

export interface StepperProps {
  /** Метка текущего шага, начиная с 0. */
  current: number;
  /** Подписи шагов; по умолчанию — пять этапов программы (Д3 §4.1). */
  labels?: readonly string[];
  /** Наибольший доступный шаг (по умолчанию — current). */
  maxReached?: number;
  onSelect?: (step: number) => void;
  className?: string;
}

export function Stepper({ current, labels = T.steps.labels, maxReached, onSelect, className }: StepperProps) {
  const reachable = maxReached ?? current;

  return (
    <nav aria-label="Этапы программы" className={cx("flex flex-wrap items-center gap-sm", className)}>
      <ol className="flex flex-wrap items-center gap-sm">
        {labels.map((label, index) => {
          const isCurrent = index === current;
          const isDone = index < current;
          const isReachable = index <= reachable;
          const classes = cx(
            "inline-flex items-center gap-sm rounded-full border px-md py-xs text-caption",
            isCurrent && "border-primary bg-primary-bg text-primary font-semibold",
            isDone && !isCurrent && "border-success/40 bg-success-bg text-success",
            !isCurrent && !isDone && "border-line bg-surface text-ink-muted",
            !isReachable && "opacity-60",
          );
          return (
            <li key={label} className="flex items-center gap-sm">
              {onSelect ? (
                <button
                  type="button"
                  className={cx(classes, "cursor-pointer disabled:cursor-not-allowed")}
                  disabled={!isReachable}
                  title={!isReachable ? T.steps.blocked : undefined}
                  aria-current={isCurrent ? "step" : undefined}
                  onClick={() => onSelect(index)}
                >
                  <StepMark index={index} current={current} />
                  {label}
                </button>
              ) : (
                <span className={classes} aria-current={isCurrent ? "step" : undefined}>
                  <StepMark index={index} current={current} />
                  {label}
                </span>
              )}
              {index < labels.length - 1 ? (
                <span aria-hidden="true" className="text-line">
                  →
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function StepMark({ index, current }: { index: number; current: number }) {
  const isDone = index < current;
  return (
    <span
      aria-hidden="true"
      className={cx(
        "flex h-5 w-5 items-center justify-center rounded-full text-caption font-bold",
        isDone ? "bg-success text-white" : index === current ? "bg-primary text-white" : "bg-line text-ink-muted",
      )}
    >
      {isDone ? "✓" : index + 1}
    </span>
  );
}
