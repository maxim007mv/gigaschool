/**
 * Диалог и выдвижная панель на Radix Dialog (Д3 §7):
 * фокус-ловушка, Escape закрывает, фокус возвращается на кнопку-триггер.
 */

import * as DialogPrimitive from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { cx } from "./cx";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

export interface DialogContentProps {
  children: ReactNode;
  /** "center" — обычное окно; "right" — панель справа (правка элемента). */
  side?: "center" | "right";
  className?: string;
}

export function DialogContent({ children, side = "center", className }: DialogContentProps) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-ink/40" />
      <DialogPrimitive.Content
        className={cx(
          "fixed z-50 bg-surface shadow-card focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
          side === "center" &&
            "left-1/2 top-1/2 w-[min(640px,92vw)] max-h-[85vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-card p-xl",
          side === "right" &&
            "right-0 top-0 h-full w-[min(560px,94vw)] overflow-y-auto rounded-l-card p-xl shadow-drawer",
          className,
        )}
      >
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogFooter({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("mt-lg flex flex-wrap items-center justify-end gap-md", className)}>{children}</div>;
}
