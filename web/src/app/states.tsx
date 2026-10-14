/**
 * Скелеты страниц без данных: используются во всех маршрутах.
 */

import type { ReactNode } from "react";

import { Skeleton, TableSkeleton } from "../shared/ui/Skeleton";

export function PageSkeleton() {
  return (
    <div className="flex flex-col gap-lg" role="status" aria-label="Загрузка страницы">
      <Skeleton className="h-7 w-64" />
      <Skeleton className="h-4 w-96" />
      <TableSkeleton rows={5} cols={6} />
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-md rounded-card border border-danger/30 bg-danger-bg p-lg">
      <p className="text-base text-danger">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-btn border border-danger px-md py-sm text-base text-danger hover:bg-danger hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger"
        >
          Повторить
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-md rounded-card border border-dashed border-line bg-surface p-xl">
      <span aria-hidden="true" className="text-3xl">
        📄
      </span>
      <h2 className="text-subtitle font-semibold text-ink">{title}</h2>
      <p className="max-w-[560px] text-base text-ink-muted">{hint}</p>
      {action}
    </div>
  );
}
