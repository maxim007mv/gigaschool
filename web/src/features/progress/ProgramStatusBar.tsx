/**
 * Статус программы и этап пайплайна для жюри/методиста.
 */

import { formatStatus } from "../../entities/formatters";
import type { ProgramStatus } from "../../entities/kit";
import { useProgram } from "../../shared/api/queries";
import { T } from "../../shared/i18n/ru";
import { Badge } from "../../shared/ui/Badge";
import { Stepper } from "../../shared/ui/Stepper";
import { cx } from "../../shared/ui/cx";

const STATUS_STEP: Record<ProgramStatus, number> = {
  draft: 0,
  clarifying: 1,
  framework_generating: 2,
  framework_review: 2,
  framework_approved: 3,
  kit_generating: 4,
  kit_review: 4,
  kit_updating: 4,
  archived: 4,
  failed: 0,
};

export interface ProgramStatusBarProps {
  programId: string;
  /** Текущий шаг stepper (0–4). Если не задан — выводится из status программы. */
  currentStep?: number;
  className?: string;
}

export function ProgramStatusBar({ programId, currentStep, className }: ProgramStatusBarProps) {
  const programQuery = useProgram(programId || null);
  const status = programQuery.data?.status;
  const step = currentStep ?? (status ? STATUS_STEP[status] : 0);
  const busy = status === "framework_generating" || status === "kit_generating" || status === "kit_updating";

  return (
    <div className={cx("flex flex-col gap-sm rounded-card border border-line bg-surface-alt p-md", className)}>
      <div className="flex flex-wrap items-center justify-between gap-sm">
        <span className="text-caption font-medium text-ink-muted">{T.progress.pipeline}</span>
        {status ? (
          <Badge variant={busy ? "warning" : "neutral"}>{formatStatus(status)}</Badge>
        ) : null}
      </div>
      <Stepper current={step} maxReached={step} />
      {busy ? <p className="text-caption text-ink-muted">{T.progress.agentWorking}</p> : null}
    </div>
  );
}
