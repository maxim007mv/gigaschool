/**
 * ReportPanel — итог самопроверки комплекта (Д3 §4.5, US-8).
 *
 * Сводка по группам (часы, покрытие, источники, разделы, заимствования),
 * замечания с фильтром по серьёзности, допущения, разрывы и замечания
 * к образцу; выгрузка отчёта в .docx.
 */

import type { Report, ReportIssue } from "../../entities/kit";
import { formatCount, formatMillis, ISSUE_FORMS, pluralRu } from "../../entities/formatters";
import { T } from "../../shared/i18n/ru";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { cx } from "../../shared/ui/cx";
import { IssueItem } from "./IssueItem";

export interface ReportPanelProps {
  report: Report | null;
  onExportReport?: () => void;
  onFixIssue?: (issue: ReportIssue) => void;
  className?: string;
}

const SEVERITY_ORDER: Record<ReportIssue["severity"], number> = { error: 0, warning: 1, info: 2 };

export function ReportPanel({ report, onExportReport, onFixIssue, className }: ReportPanelProps) {
  if (!report) {
    return (
      <aside aria-label={T.report.title} className={cx("rounded-card border border-line bg-surface p-lg", className)}>
        <h2 className="text-subtitle font-semibold text-ink">{T.report.title}</h2>
        <p className="mt-sm text-base text-ink-muted">{T.report.notReady}</p>
      </aside>
    );
  }

  const sortedIssues = [...report.issues].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity],
  );
  const errorCount = report.issues.filter((i) => i.severity === "error").length;
  const warningCount = report.issues.filter((i) => i.severity === "warning").length;

  return (
    <aside aria-label={T.report.title} className={cx("flex flex-col gap-md rounded-card border border-line bg-surface p-lg", className)}>
      <header className="flex flex-wrap items-center justify-between gap-sm">
        <h2 className="text-subtitle font-semibold text-ink">{T.report.title}</h2>
        <Badge variant={report.passed ? "ok" : "error"}>
          {report.passed ? T.report.passed : T.report.failed}
        </Badge>
      </header>

      <p className="text-caption text-ink-muted">
        {T.report.duration}: {formatMillis(report.duration_ms)}
        {report.version !== null ? ` · ${T.framework.version} ${report.version}` : ""}
      </p>

      {/* Сводка по группам проверок */}
      <dl className="grid grid-cols-2 gap-sm text-caption">
        <SummaryItem
          label={T.report.summaryItems.hours}
          ok={report.summary.hours?.ok}
          value={report.summary.hours ? `проверок: ${report.summary.hours.checked}` : undefined}
        />
        <SummaryItem
          label={T.report.summaryItems.coverage}
          ok={report.summary.coverage?.ok}
          value={
            report.summary.coverage
              ? `${report.summary.coverage.outcomes} результатов · ≥ ${report.summary.coverage.min_assessments} средств`
              : undefined
          }
        />
        <SummaryItem
          label={T.report.summaryItems.sources}
          ok={report.summary.sources ? report.summary.sources.unverified === 0 && report.summary.sources.not_found === 0 : undefined}
          value={
            report.summary.sources
              ? `подтверждено: ${report.summary.sources.verified}, не подтверждено: ${report.summary.sources.unverified}`
              : undefined
          }
        />
        <SummaryItem
          label={T.report.summaryItems.template}
          ok={report.summary.template ? report.summary.template.filled >= report.summary.template.sections_total : undefined}
          value={
            report.summary.template
              ? `${report.summary.template.filled} из ${report.summary.template.sections_total}`
              : undefined
          }
        />
        <SummaryItem
          label={T.report.summaryItems.acr}
          ok={
            report.summary.acr_export && typeof report.summary.acr_export === "object"
              ? Boolean((report.summary.acr_export as { ok?: boolean }).ok)
              : undefined
          }
          value={
            report.summary.acr_export && typeof report.summary.acr_export === "object"
              ? `разделов эталона: ${(report.summary.acr_export as { expected_sections?: number }).expected_sections ?? "—"}`
              : undefined
          }
        />
      </dl>

      {/* Замечания */}
      <section aria-label={T.report.issues}>
        <h3 className="mb-sm text-base font-semibold text-ink">
          {T.report.issues}
          {errorCount + warningCount > 0 ? (
            <span className="ml-sm text-caption font-normal text-ink-muted">
              {errorCount > 0 ? formatCount(errorCount, ISSUE_FORMS) : ""}
              {errorCount > 0 && warningCount > 0 ? " · " : ""}
              {warningCount > 0
                ? `${warningCount} ${pluralRu(warningCount, ["предупреждение", "предупреждения", "предупреждений"])}`
                : ""}
            </span>
          ) : null}
        </h3>
        {sortedIssues.length === 0 ? (
          <Badge variant="ok">{T.report.issuesNone}</Badge>
        ) : (
          <ul className="flex flex-col gap-sm">
            {sortedIssues.map((issue, index) => (
              <IssueItem key={`${issue.rule_code}-${issue.entity_ref ?? index}`} issue={issue} onFix={onFixIssue} />
            ))}
          </ul>
        )}
      </section>

      {report.assumptions.length > 0 ? (
        <section aria-label={T.report.assumptions}>
          <h3 className="mb-sm text-base font-semibold text-ink">{T.report.assumptions}</h3>
          <ul className="list-disc pl-lg text-caption text-ink">
            {report.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {report.gaps.length > 0 ? (
        <section aria-label={T.report.gaps}>
          <h3 className="mb-sm text-base font-semibold text-ink">{T.report.gaps}</h3>
          <ul className="list-disc pl-lg text-caption text-ink">
            {report.gaps.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {report.sample_findings.length > 0 ? (
        <section aria-label={T.report.sampleFindings}>
          <h3 className="mb-sm text-base font-semibold text-ink">{T.report.sampleFindings}</h3>
          <ul className="list-disc pl-lg text-caption text-ink">
            {report.sample_findings.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {onExportReport ? (
        <div>
          <Button variant="secondary" size="sm" onClick={onExportReport}>
            {T.report.export}
          </Button>
        </div>
      ) : null}
    </aside>
  );
}

function SummaryItem({ label, ok, value }: { label: string; ok: boolean | undefined; value: string | undefined }) {
  const badge: "ok" | "error" | "neutral" = ok === true ? "ok" : ok === false ? "error" : "neutral";
  return (
    <div className="flex flex-col gap-xs rounded-btn bg-canvas px-md py-sm">
      <dt className="font-medium text-ink">{label}</dt>
      <dd>
        <Badge variant={badge}>{ok === true ? "ок" : ok === false ? "есть замечания" : "—"}</Badge>
        {value ? <span className="mt-xs block text-caption text-ink-muted">{value}</span> : null}
      </dd>
    </div>
  );
}
