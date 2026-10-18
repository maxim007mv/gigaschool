/**
 * SumCell — ячейка вычисленной суммы.
 *
 * Красная подсветка ошибки — не только цветом: добавляется значок «!»
 * и текст для скринридера (WCAG 1.4.1).
 */

import { cx } from "../../shared/ui/cx";

export type SumCellState = "normal" | "muted" | "error" | "ok";

export interface SumCellProps {
  value: number;
  /** Единица измерения рядом: обычно «ч». */
  unit?: string;
  state?: SumCellState;
  /** Полужирный итог (модуль, программа). */
  strong?: boolean;
  /** Живой регион для скринридера (суммы пересчитываются на лету). */
  live?: boolean;
  title?: string;
  className?: string;
}

export function SumCell({ value, unit = "ч", state = "normal", strong, live, title, className }: SumCellProps) {
  return (
    <span
      data-state={state}
      aria-live={live ? "polite" : undefined}
      title={title}
      className={cx(
        "tnum inline-flex items-center justify-end gap-xs text-right",
        strong && "font-semibold",
        state === "muted" && "text-ink-muted",
        state === "error" && "font-semibold text-danger",
        state === "ok" && "text-success",
        className,
      )}
    >
      {state === "error" ? (
        <span aria-hidden="true" className="font-bold">
          !
        </span>
      ) : null}
      <span>
        {value}
        {unit ? <span className="ml-[2px] text-caption text-ink-muted"> {unit}</span> : null}
      </span>
      {state === "error" ? <span className="sr-only">Ошибка: сумма не сходится</span> : null}
    </span>
  );
}
