/**
 * DiffView — сравнение версий и результат правки (Д3 §4.5).
 *
 * Показывает, какие элементы изменились между версиями; полные тексты
 * diff-а — ленивый чанк (Д3 §10), здесь — сводка и список ref.
 */

import { T } from "../../shared/i18n/ru";
import { Badge } from "../../shared/ui/Badge";
import { cx } from "../../shared/ui/cx";

export interface DiffViewProps {
  changedRefs: string[];
  addedRefs?: string[];
  removedRefs?: string[];
  fromVersion?: number | null;
  toVersion?: number | null;
  summary?: string | null;
  className?: string;
}

export function DiffView({
  changedRefs,
  addedRefs = [],
  removedRefs = [],
  fromVersion,
  toVersion,
  summary,
  className,
}: DiffViewProps) {
  const hasVersions = typeof fromVersion === "number" && typeof toVersion === "number";
  const hasAny = changedRefs.length > 0 || addedRefs.length > 0 || removedRefs.length > 0;

  return (
    <section aria-label={T.kit.changedRefs} className={cx("flex flex-col gap-sm", className)}>
      <h3 className="text-base font-semibold text-ink">{T.kit.changedRefs}</h3>

      {hasVersions ? (
        <p className="tnum text-caption text-ink-muted">
          {T.framework.version} {fromVersion} → {toVersion}
        </p>
      ) : null}

      {summary ? <p className="text-base text-ink">{summary}</p> : null}

      {!hasAny ? (
        <p className="text-base text-ink-muted">Изменённых элементов нет.</p>
      ) : (
        <div className="flex flex-col gap-sm">
          {changedRefs.length > 0 ? (
            <ul className="flex flex-wrap gap-xs">
              {changedRefs.map((ref) => (
                <li key={`changed-${ref}`}>
                  <Badge variant="warning" className="tnum">
                    {ref}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : null}
          {addedRefs.length > 0 ? (
            <p className="flex flex-wrap items-center gap-xs text-caption">
              <span className="text-ink-muted">Добавлено:</span>
              {addedRefs.map((ref) => (
                <Badge key={`added-${ref}`} variant="ok" className="tnum">
                  {ref}
                </Badge>
              ))}
            </p>
          ) : null}
          {removedRefs.length > 0 ? (
            <p className="flex flex-wrap items-center gap-xs text-caption">
              <span className="text-ink-muted">Удалено:</span>
              {removedRefs.map((ref) => (
                <Badge key={`removed-${ref}`} variant="error" className="tnum">
                  {ref}
                </Badge>
              ))}
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}
