/**
 * Статус программы и этап пайплайна для жюри/методиста.
 */

import { Link } from "@tanstack/react-router";

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

const STEP_DETAILS: Record<ProgramStatus, string> = {
  draft: "Запрос введён, ожидается переход к уточнениям требований.",
  clarifying: "Методист отвечает на ключевые вопросы перед формированием структуры.",
  framework_generating: "Агент формирует модули, темы, результаты обучения и баланс часов.",
  framework_review: "Каркас сформирован. Проверьте распределение часов и утвердите структуру.",
  framework_approved: "Каркас успешно утверждён методистом (Human Gate пройден).",
  kit_generating: "Агент формирует комплекты УМК: рабочие программы, слайды, оценочные средства и тесты.",
  kit_review: "Комплект готов к методической проверке и выгрузке артефактов.",
  kit_updating: "Выполняется точечная пересборка выбранных материалов комплекта.",
  archived: "Программа переведена в архив.",
  failed: "Сборка программы остановлена из-за ошибки в данных или ограничениях.",
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
  const failed = status === "failed";
  const totalSteps = T.steps.labels.length;
  const currentStepNum = Math.min(step + 1, totalSteps);
  const remainingSteps = Math.max(0, totalSteps - currentStepNum);
  const stepTitle = T.steps.labels[step] ?? T.steps.labels[0];

  return (
    <div className={cx("flex flex-col gap-sm rounded-card border border-line bg-surface-alt p-md", className)}>
      <div className="flex flex-wrap items-center justify-between gap-sm">
        <div className="flex items-center gap-xs">
          <span className="text-caption font-semibold text-ink">
            Шаг {currentStepNum} из {totalSteps}: {stepTitle}
          </span>
          <span className="text-caption text-ink-muted">
            {remainingSteps > 0 ? `(осталось шагов: ${remainingSteps})` : "(финальный этап)"}
          </span>
        </div>
        {status ? (
          <Badge variant={failed ? "error" : busy ? "warning" : "neutral"}>{formatStatus(status)}</Badge>
        ) : null}
      </div>

      <Stepper current={step} maxReached={step} />

      {status && (
        <p className="text-caption text-ink-muted">
          {STEP_DETAILS[status] ?? T.progress.agentWorking}
        </p>
      )}

      {failed && (
        <div className="mt-xs flex flex-col gap-xs rounded-btn border border-error/40 bg-error-bg p-sm text-caption text-error">
          <strong className="font-semibold text-error">Что делать дальше:</strong>
          <p>
            Проверьте введённые параметры программы (объём часов, форма обучения, доля практики). Если параметры верны,
            вернитесь на шаг «Уточнения» или выполните откат к предыдущей версии каркаса.
          </p>
          <div className="mt-xs flex flex-wrap items-center gap-md">
            <Link
              to="/programs/$programId/clarify"
              params={{ programId }}
              className="font-medium text-primary underline underline-offset-2 hover:text-primary-dark"
            >
              Перейти к уточнениям →
            </Link>
            <Link
              to="/programs/$programId/versions"
              params={{ programId }}
              className="font-medium text-primary underline underline-offset-2 hover:text-primary-dark"
            >
              История версий и откат →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
