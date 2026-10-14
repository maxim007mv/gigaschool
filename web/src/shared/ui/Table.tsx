/**
 * Табличные примитивы. Семантика: thead/tbody/th/td; для интерактивных
 * таблиц (план часов, матрица покрытия) вызывающий код добавляет role="grid"
 * и реализует грид-паттерн клавиатуры; по умолчанию — обычная таблица.
 * Числовые ячейки — класс tnum (tabular-nums, Д3 §7).
 */

import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";
import { cx } from "./cx";

export function Table({ children, className, label }: { children: ReactNode; className?: string; label: string }) {
  return (
    <table role="table" aria-label={label} className={cx("w-full border-collapse text-base", className)}>
      {children}
    </table>
  );
}

export function TableHeaderCell({
  children,
  className,
  scope = "col",
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & { children: ReactNode; scope?: "col" | "row" | "rowgroup" }) {
  return (
    <th
      scope={scope}
      className={cx(
        "border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function TableCell({
  children,
  className,
  numeric,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement> & { children?: ReactNode; numeric?: boolean }) {
  return (
    <td className={cx("border-b border-line/60 px-md py-sm align-top", numeric && "tnum text-right", className)} {...rest}>
      {children}
    </td>
  );
}
