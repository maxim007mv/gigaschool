/**
 * IssueItem — замечание автопроверки (Д3 §4.5, §5).
 *
 * Серьёзность передаётся значком и текстом, не только цветом.
 * Для ошибок с подсказкой доступна кнопка «Исправить».
 */

import type { ReportIssue } from "../../entities/kit";
import { T } from "../../shared/i18n/ru";
import { Badge, type BadgeVariant } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { cx } from "../../shared/ui/cx";

export interface IssueItemProps {
  issue: ReportIssue;
  onFix?: (issue: ReportIssue) => void;
  className?: string;
}

const SEVERITY_VARIANT: Record<ReportIssue["severity"], BadgeVariant> = {
  error: "error",
  warning: "warning",
  info: "info",
};

export function IssueItem({ issue, onFix, className }: IssueItemProps) {
  return (
    <li
      data-severity={issue.severity}
      className={cx(
        "flex flex-col gap-xs rounded-btn border px-md py-sm",
        issue.severity === "error" && "border-danger/30 bg-danger-bg/60",
        issue.severity === "warning" && "border-warning/30 bg-warning-bg/60",
        issue.severity === "info" && "border-line bg-canvas",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-sm">
        <Badge variant={SEVERITY_VARIANT[issue.severity]}>{T.severity[issue.severity]}</Badge>
        <span className="tnum text-caption text-ink-muted">{issue.rule_code}</span>
        {issue.entity_ref ? <span className="tnum text-caption text-ink-muted">· {issue.entity_ref}</span> : null}
      </div>
      <p className="text-base text-ink">{issue.message}</p>
      {onFix && issue.severity !== "info" ? (
        <div>
          <Button variant="ghost" size="sm" onClick={() => onFix(issue)}>
            Исправить
          </Button>
        </div>
      ) : null}
    </li>
  );
}
