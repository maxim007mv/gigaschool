/**
 * «Мои программы» (Д3 §4.6): список программ с фильтрами по статусу, виду
 * и объёму, статус-бейджи, кнопка «Новый запрос», пустое состояние.
 */

import { useState } from "react";
import { Link } from "@tanstack/react-router";

import type { ProgramStatus, ProgramSummary } from "../entities/kit";
import { formatDateRu, formatProgramForm, formatProgramKind, formatStatus } from "../entities/formatters";
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

export function ProgramsPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<string>("all");
  const [kind, setKind] = useState<string>("all");

  const programs = usePrograms({ q, status, kind });

  if (programs.isPending) return <PageSkeleton />;
  if (programs.isError) {
    return <ErrorState message={T.app.error} onRetry={() => void programs.refetch()} />;
  }

  const items = programs.data.items;

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-wrap items-end justify-between gap-md">
        <h1 className="text-title font-bold text-ink">{T.programs.title}</h1>
        <Link
          to="/programs/new"
          className="inline-flex min-h-[36px] items-center justify-center rounded-btn bg-primary px-lg py-sm font-medium text-white hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          {T.programs.newProgram}
        </Link>
      </header>

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

      {items.length === 0 ? (
        <EmptyState
          title={T.programs.empty}
          hint={T.programs.emptyHint}
          action={
            <Link
              to="/programs/new"
              className="inline-flex min-h-[36px] items-center justify-center rounded-btn bg-primary px-lg py-sm font-medium text-white hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              {T.programs.newProgram}
            </Link>
          }
        />
      ) : (
        <ul className="grid grid-cols-1 gap-md lg:grid-cols-2">
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
  return (
    <article className="flex h-full flex-col gap-md rounded-card border border-line bg-surface p-lg shadow-card">
      <div className="flex flex-wrap items-center gap-sm">
        <Badge variant={STATUS_VARIANT[program.status]}>{formatStatus(program.status)}</Badge>
        {program.kind ? <Badge variant="neutral">{formatProgramKind(program.kind)}</Badge> : null}
        {program.form ? <Badge variant="neutral">{formatProgramForm(program.form)}</Badge> : null}
        {program.needs_input ? <Badge variant="warning">{T.programs.needsInput}</Badge> : null}
      </div>

      <h2 className="text-subtitle font-semibold">
        <ProgramLink program={program} />
      </h2>

      <dl className="flex flex-wrap gap-lg text-caption text-ink-muted">
        <div className="flex gap-xs">
          <dt>{T.programs.hours}:</dt>
          <dd className="tnum font-medium text-ink">{program.total_hours} ч</dd>
        </div>
        <div className="flex gap-xs">
          <dt>{T.programs.updated}:</dt>
          <dd className="tnum">{formatDateRu(program.updated_at)}</dd>
        </div>
        {program.audience ? (
          <div className="flex gap-xs">
            <dt>Слушатели:</dt>
            <dd>{program.audience}</dd>
          </div>
        ) : null}
      </dl>
    </article>
  );
}

/** Куда ведёт карточка: следующий неоконченный шаг программы. */
function ProgramLink({ program }: { program: ProgramSummary }) {
  const className =
    "text-ink hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary";

  switch (program.status) {
    case "clarifying":
      return (
        <Link to="/programs/$programId/clarify" params={{ programId: program.id }} className={className}>
          {program.title}
        </Link>
      );
    case "kit_generating":
    case "kit_review":
    case "kit_updating":
      return (
        <Link to="/programs/$programId/kit" params={{ programId: program.id }} className={className}>
          {program.title}
        </Link>
      );
    default:
      return (
        <Link to="/programs/$programId/framework" params={{ programId: program.id }} className={className}>
          {program.title}
        </Link>
      );
  }
}
