/**
 * «Мои программы»: короткий список + одна кнопка действия на карточке.
 * Фильтры спрятаны — для демо/Zoom не мешают.
 */

import { useState } from "react";
import { Link } from "@tanstack/react-router";

import type { ProgramStatus, ProgramSummary } from "../entities/kit";
import { formatStatus } from "../entities/formatters";
import { usePrograms } from "../shared/api/queries";
import { T } from "../shared/i18n/ru";
import { Badge, type BadgeVariant } from "../shared/ui/Badge";
import { EmptyState, ErrorState, PageSkeleton } from "../app/states";

const STATUS_VARIANT: Record<ProgramStatus, BadgeVariant> = {
  draft: "neutral",
  clarifying: "warning",
  framework_generating: "info",
  framework_review: "info",
  framework_approved: "ok",
  kit_generating: "info",
  kit_review: "info",
  kit_updating: "info",
  archived: "neutral",
  failed: "error",
};

type NextStep = {
  label: string;
  to: "/programs/$programId/clarify" | "/programs/$programId/framework" | "/programs/$programId/kit";
};

function nextStep(status: ProgramStatus): NextStep {
  switch (status) {
    case "clarifying":
      return { label: "Ответить на вопросы", to: "/programs/$programId/clarify" };
    case "framework_review":
      return { label: "Проверить часы", to: "/programs/$programId/framework" };
    case "framework_approved":
    case "kit_generating":
      return { label: "Собрать комплект", to: "/programs/$programId/kit" };
    case "kit_review":
    case "kit_updating":
      return { label: "Открыть материалы", to: "/programs/$programId/kit" };
    case "failed":
      return { label: "Открыть программу", to: "/programs/$programId/framework" };
    default:
      return { label: "Открыть каркас", to: "/programs/$programId/framework" };
  }
}

export function ProgramsPage() {
  const [showFilters, setShowFilters] = useState(false);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<string>("all");
  const [kind, setKind] = useState<string>("all");

  const programs = usePrograms({ q, status, kind });

  if (programs.isPending) return <PageSkeleton />;
  if (programs.isError) {
    return <ErrorState message={T.app.error} onRetry={() => void programs.refetch()} />;
  }

  // Архив не показываем в обычном списке — меньше шума.
  const items = programs.data.items.filter((p) => p.status !== "archived");

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-wrap items-end justify-between gap-md">
        <div className="flex flex-col gap-xs">
          <h1 className="text-title font-bold text-ink">{T.programs.title}</h1>
          <p className="max-w-[36rem] text-base text-ink-muted">
            Нажмите зелёную кнопку на карточке — откроется следующий шаг.
          </p>
        </div>
        <Link
          to="/programs/new"
          className="inline-flex min-h-[40px] items-center justify-center rounded-btn bg-primary px-lg py-sm font-medium text-white hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          {T.programs.newProgram}
        </Link>
      </header>

      <ol className="grid gap-sm rounded-card border border-line bg-surface px-lg py-md text-base text-ink sm:grid-cols-3">
        <li>
          <span className="font-semibold text-primary">1.</span> Выберите программу
        </li>
        <li>
          <span className="font-semibold text-primary">2.</span> Проверьте часы в каркасе
        </li>
        <li>
          <span className="font-semibold text-primary">3.</span> Смотрите материалы в комплекте
        </li>
      </ol>

      <div className="flex items-center justify-between gap-md">
        <p className="text-caption text-ink-muted">
          {items.length === 0 ? "Программ пока нет" : `Программ: ${items.length}`}
        </p>
        <button
          type="button"
          className="text-caption text-primary underline underline-offset-2"
          onClick={() => setShowFilters((v) => !v)}
        >
          {showFilters ? "Скрыть фильтры" : "Фильтры"}
        </button>
      </div>

      {showFilters ? (
        <form
          className="flex flex-wrap items-end gap-md rounded-card border border-line bg-surface p-lg"
          onSubmit={(event) => event.preventDefault()}
          aria-label="Фильтры программ"
        >
          <label className="flex min-w-[220px] flex-col gap-xs text-caption text-ink-muted">
            {T.programs.search}
            <input
              type="search"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder={T.programs.search}
              className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base text-ink focus-visible:border-primary"
            />
          </label>
          <label className="flex flex-col gap-xs text-caption text-ink-muted">
            {T.programs.filterStatus}
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base text-ink focus-visible:border-primary"
            >
              <option value="all">{T.programs.filterAll}</option>
              {(Object.keys(T.statuses) as ProgramStatus[]).map((value) => (
                <option key={value} value={value}>
                  {T.statuses[value]}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-xs text-caption text-ink-muted">
            {T.programs.filterKind}
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value)}
              className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base text-ink focus-visible:border-primary"
            >
              <option value="all">{T.programs.filterAll}</option>
              <option value="dpp_pk">{T.kinds.dpp_pk}</option>
              <option value="dop">{T.kinds.dop}</option>
            </select>
          </label>
        </form>
      ) : null}

      {items.length === 0 ? (
        <EmptyState
          title={T.programs.empty}
          hint="Создайте новую программу кнопкой справа вверху"
          action={
            <Link
              to="/programs/new"
              className="inline-flex min-h-[36px] items-center justify-center rounded-btn bg-primary px-lg py-sm font-medium text-white hover:bg-primary-dark"
            >
              {T.programs.newProgram}
            </Link>
          }
        />
      ) : (
        <ul className="flex flex-col gap-md">
          {items.map((program) => (
            <li key={program.id}>
              <ProgramCard program={program} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ProgramCard({ program }: { program: ProgramSummary }) {
  const step = nextStep(program.status);
  return (
    <article className="flex flex-col gap-md rounded-card border border-line bg-surface p-lg shadow-card sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-sm">
        <Badge variant={STATUS_VARIANT[program.status]}>{formatStatus(program.status)}</Badge>
        <h2 className="text-subtitle font-semibold text-ink">{program.title}</h2>
        <p className="text-caption text-ink-muted">
          {program.total_hours ? `${program.total_hours} ч` : "объём не задан"}
        </p>
      </div>
      <Link
        to={step.to}
        params={{ programId: program.id }}
        className="inline-flex min-h-[44px] shrink-0 items-center justify-center rounded-btn bg-primary px-xl py-sm text-base font-semibold text-white hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      >
        {step.label}
      </Link>
    </article>
  );
}
