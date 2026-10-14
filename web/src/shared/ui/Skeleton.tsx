/**
 * Скелетоны загрузки (Д3 §5): вместо спиннеров, без смещения макета.
 */

import { cx } from "./cx";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("animate-pulse rounded-btn bg-line/60", className)} />;
}

export function TableSkeleton({ rows = 4, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div role="status" aria-label="Загрузка данных" className="flex flex-col gap-sm">
      {Array.from({ length: rows }, (_, rowIndex) => (
        <div key={rowIndex} className="grid gap-sm" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
          {Array.from({ length: cols }, (_, colIndex) => (
            <Skeleton key={colIndex} className={cx("h-6", colIndex === 0 && "w-3/4")} />
          ))}
        </div>
      ))}
    </div>
  );
}
