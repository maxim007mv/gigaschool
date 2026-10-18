/**
 * Всплывающие уведомления (Д3 §7): успех и ошибка.
 *
 * Не заменяют ошибки на месте: критичные проблемы (часы, Human Gate)
 * показываются прямо в интерфейсе, а тосты — только про фон.
 */

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "./cx";

export type ToastKind = "success" | "error";

interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  show: (kind: ToastKind, message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 6000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const show = useCallback((kind: ToastKind, message: string) => {
    const id = nextId.current;
    nextId.current += 1;
    setItems((prev) => [...prev, { id, kind, message }]);
    setTimeout(() => {
      setItems((prev) => prev.filter((item) => item.id !== id));
    }, AUTO_DISMISS_MS);
  }, []);

  const value = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-label="Уведомления"
        className="pointer-events-none fixed bottom-lg right-lg z-[100] flex w-[min(360px,92vw)] flex-col gap-sm"
      >
        {items.map((item) => (
          <div
            key={item.id}
            role="status"
            className={cx(
              "pointer-events-auto rounded-card border px-lg py-md text-base shadow-card",
              item.kind === "success" && "border-success/30 bg-success-bg text-success",
              item.kind === "error" && "border-danger/30 bg-danger-bg text-danger",
            )}
          >
            <span aria-hidden="true" className="mr-xs font-bold">
              {item.kind === "success" ? "✓" : "✕"}
            </span>
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast можно вызывать только внутри ToastProvider");
  }
  return ctx;
}
