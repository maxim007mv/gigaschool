/**
 * ConstraintBar — панель ограничений часов и замечаний проверки (Д3 §4.3).
 *
 * Показывает, что именно требует заказчик (объём, аттестация, кратность,
 * доля практики, ДОТ/стажировка), какие расхождения найдены и кнопку
 * «Пересчитать часы» (framework:rebalance с закреплёнными ячейками).
 */

import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { cx } from "../../shared/ui/cx";
import { T } from "../../shared/i18n/ru";
import { RULES } from "./rules";
import type { LiveConstraints, LiveHoursResult } from "./useLiveHours";

export interface ConstraintBarProps {
  constraints: LiveConstraints;
  result: LiveHoursResult;
  onRebalance?: () => void;
  busy?: boolean;
  className?: string;
}

export function ConstraintBar({ constraints, result, onRebalance, busy, className }: ConstraintBarProps) {
  const errorCount = result.issues.length;

  return (
    <aside aria-label={T.constraints.title} className={cx("flex flex-col gap-md rounded-card border border-line bg-surface p-lg", className)}>
      <h2 className="text-subtitle font-semibold text-ink">{T.constraints.title}</h2>

      <ul className="flex flex-col gap-sm text-base text-ink">
        <li className="flex items-baseline justify-between gap-sm">
          <span>{T.constraints.total}</span>
          <span className="tnum font-semibold">{constraints.total} ч</span>
        </li>
        <li className="flex items-baseline justify-between gap-sm">
          <span>{T.constraints.finalAtt}</span>
          <span className="tnum font-semibold">{constraints.finalAttHours} ч</span>
        </li>
        <li className="flex items-baseline justify-between gap-sm">
          <span>{T.constraints.unit}</span>
          <span className="tnum font-semibold">{constraints.unitHours ?? 1} ч</span>
        </li>
        <li className="flex items-baseline justify-between gap-sm">
          <span>{T.constraints.minPractice}</span>
          <span className="tnum font-semibold">≥ {constraints.minPracticeSharePct ?? 0} %</span>
        </li>
        {constraints.selfStudyOnly ? (
          <li>
            <Badge variant="info">{T.constraints.selfStudyOnly}</Badge>
          </li>
        ) : null}
        {constraints.distanceMode ? (
          <li>
            <Badge variant="info">{T.constraints.distance}</Badge>
          </li>
        ) : null}
      </ul>

      <div className="border-t border-line pt-md">
        <h3 className="mb-sm text-base font-semibold text-ink">{T.constraints.issues}</h3>
        <p aria-live="polite" className="mb-sm text-caption text-ink-muted">
          {errorCount === 0 ? T.hours.checksPassed : `${errorCount} — сумма не сходится`}
        </p>
        {errorCount > 0 ? (
          <ul className="flex flex-col gap-sm">
            {result.issues.map((issue, index) => (
              <li key={`${issue.rule}-${issue.ref ?? "program"}-${index}`} className="rounded-btn bg-danger-bg px-md py-sm text-caption text-danger">
                <span className="font-semibold">
                  {issue.ref ? `${RULES[issue.rule].title} · ${issue.ref}` : RULES[issue.rule].title}
                </span>
                <span className="mt-[2px] block">{issue.message}</span>
              </li>
            ))}
          </ul>
        ) : (
          <Badge variant="ok">{T.hours.checksPassed}</Badge>
        )}
      </div>

      {onRebalance ? (
        <div className="flex flex-col gap-xs">
          <Button variant="secondary" size="sm" onClick={onRebalance} busy={busy}>
            {T.hours.rebalance}
          </Button>
          <span className="text-caption text-ink-muted">{T.hours.rebalanceHint}</span>
        </div>
      ) : null}
    </aside>
  );
}
