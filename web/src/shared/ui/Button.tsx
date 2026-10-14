/**
 * Кнопка (Д3 §7): primary, secondary, ghost, danger.
 *
 * Правила: одна primary-кнопка на экран; глагол в названии; disabled —
 * с понятной причиной рядом или в подсказке.
 */

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cx } from "./cx";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "md" | "sm";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Причина недоступности: показывается в подсказке (title). */
  disabledReason?: string;
  /** Идёт операция — кнопка блокируется и помечается aria-busy. */
  busy?: boolean;
  children: ReactNode;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-primary text-white hover:bg-primary-dark disabled:bg-primary/50",
  secondary: "bg-white text-ink border border-line hover:border-primary hover:text-primary disabled:text-ink-muted",
  ghost: "bg-transparent text-primary hover:bg-primary-bg disabled:text-ink-muted",
  danger: "bg-danger text-white hover:bg-danger/90 disabled:bg-danger/50",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  md: "min-h-[36px] px-lg py-sm text-base",
  sm: "min-h-[28px] px-md py-xs text-caption",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", disabledReason, busy = false, disabled, className, children, ...rest },
  ref,
) {
  const isDisabled = Boolean(disabled || busy);
  const button = (
    <button
      ref={ref}
      type={rest.type ?? "button"}
      disabled={isDisabled}
      aria-busy={busy || undefined}
      title={isDisabled && disabledReason ? disabledReason : rest.title}
      className={cx(
        "inline-flex items-center justify-center gap-xs rounded-btn font-medium",
        "transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
        "disabled:cursor-not-allowed",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      )}
      {...rest}
    >
      {busy ? <span aria-hidden="true" className="animate-pulse">…</span> : null}
      {children}
    </button>
  );

  // Причина недоступности рядом: доступна и скринридеру, и мышью (title).
  if (isDisabled && disabledReason) {
    return (
      <span className="inline-flex flex-col items-start gap-xs" title={disabledReason}>
        {button}
        <span className="text-caption text-ink-muted">{disabledReason}</span>
      </span>
    );
  }
  return button;
});
