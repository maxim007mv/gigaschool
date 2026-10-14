/**
 * Бейдж состояния (Д3 §7): цвет + значок + текст — не только цвет
 * (требование доступности WCAG 1.4.1).
 */

import type { ReactNode } from "react";
import { cx } from "./cx";

export type BadgeVariant = "ok" | "error" | "warning" | "info" | "neutral";

export interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
  /** Дополнительное пояснение для скринридера. */
  srText?: string;
  className?: string;
}

const ICONS: Record<BadgeVariant, string> = {
  ok: "✓",
  error: "✕",
  warning: "!",
  info: "i",
  neutral: "•",
};

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  ok: "bg-success-bg text-success",
  error: "bg-danger-bg text-danger",
  warning: "bg-warning-bg text-warning",
  info: "bg-primary-bg text-primary",
  neutral: "bg-canvas text-ink-muted",
};

export function Badge({ variant = "neutral", children, srText, className }: BadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-xs rounded-full px-md py-xs text-caption font-medium",
        VARIANT_CLASSES[variant],
        className,
      )}
    >
      <span aria-hidden="true" className="font-bold">
        {ICONS[variant]}
      </span>
      <span>{children}</span>
      {srText ? <span className="sr-only">, {srText}</span> : null}
    </span>
  );
}
