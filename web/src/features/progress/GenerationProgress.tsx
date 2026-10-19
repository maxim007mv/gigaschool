/**
 * Ожидание фоновой сборки: текущий шаг, прогресс и понятный план действий
 * при ошибке (Задача 6 ТЗ: «UX ожидания и откатов»).
 */

import type { ReactNode } from "react";

import type { ProgressEventData } from "../../shared/api/sse";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { cx } from "../../shared/ui/cx";

export interface GenerationFailure {
  /** Технический код задачи; показывается мелким текстом для поддержки. */
  code: string | null;
  detail: string;
  willRetry?: boolean;
}

export interface GenerationProgressProps {
  title: string;
  description: string;
  /** Сколько обычно длится сборка и что делать, пока она идёт. */
  estimate: string;
  progress?: ProgressEventData | null;
  failure?: GenerationFailure | null;
  /** Что именно проверить и сделать при ошибке. */
  failureHint?: string;
  onRetry?: () => void;
  retryBusy?: boolean;
  retryLabel?: string;
  /** Дополнительные действия (например, ссылка на уточнения). */
  actions?: ReactNode;
  className?: string;
}

export function GenerationProgress({
  title,
  description,
  estimate,
  progress,
  failure,
  failureHint,
  onRetry,
  retryBusy = false,
  retryLabel = "Повторить сборку",
  actions,
  className,
}: GenerationProgressProps) {
  const failed = Boolean(failure);
  const percent =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.done / progress.total) * 100))
      : null;

  return (
    <section
      role={failed ? "alert" : "status"}
      aria-live="polite"
      className={cx(
        "flex flex-col gap-md rounded-card border p-lg",
        failed ? "border-danger/30 bg-danger-bg" : "border-warning/30 bg-warning-bg",
        className,
      )}
    >
      <header className="flex flex-wrap items-center justify-between gap-sm">
        <h2 className="text-subtitle font-semibold text-ink">
          {failed ? "Сборка остановилась" : title}
        </h2>
        <Badge variant={failed ? "error" : "warning"}>
          {failed ? "Нужно ваше действие" : "Идёт сборка"}
        </Badge>
      </header>

      {failed ? (
        <>
          <p className="text-base text-danger">{failure?.detail}</p>
          <div className="flex flex-col gap-xs rounded-btn border border-danger/20 bg-surface/70 p-md text-base text-ink">
            <strong className="font-semibold">Что делать дальше</strong>
            <p>
              {failureHint ??
                "Проверьте параметры программы и повторите сборку. Если ошибка не исчезает, измените исходные данные."}
            </p>
            {failure?.code ? (
              <p className="text-caption text-ink-muted">Код ошибки для поддержки: {failure.code}</p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-md">
            {onRetry ? (
              <Button variant="primary" onClick={onRetry} busy={retryBusy}>
                {retryLabel}
              </Button>
            ) : null}
            {actions}
          </div>
        </>
      ) : (
        <>
          <p className="text-base text-ink">{description}</p>

          {progress && progress.total > 0 ? (
            <div className="flex flex-col gap-xs">
              <div className="flex flex-wrap items-center justify-between gap-sm text-base text-ink">
                <span>{progress.label}</span>
                <span className="flex items-center gap-sm">
                  <span className="tnum text-caption text-ink-muted">
                    {progress.done} из {progress.total}
                  </span>
                  <span className="text-caption text-ink-muted">
                    осталось шагов: {Math.max(0, progress.total - progress.done)}
                  </span>
                </span>
              </div>
              <div
                role="progressbar"
                aria-label={progress.label}
                aria-valuemin={0}
                aria-valuemax={progress.total}
                aria-valuenow={progress.done}
                className="h-2 overflow-hidden rounded-full bg-line"
              >
                <div className="h-full bg-primary transition-all" style={{ width: `${percent}%` }} />
              </div>
            </div>
          ) : null}

          <p className="text-caption text-ink-muted">{estimate}</p>
          {actions ? <div className="flex flex-wrap items-center gap-md">{actions}</div> : null}
        </>
      )}
    </section>
  );
}
