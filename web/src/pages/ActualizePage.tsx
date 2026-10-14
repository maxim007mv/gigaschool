/**
 * «Актуализация» (Д3 §4.6, US-10): загрузка старой программы, поиск устаревших
 * тем и инструментов, таблица «было → предлагается».
 *
 * Контракт: файл → POST /files → POST /programs/{id}:actualize {file_ids};
 * результат S22 сохраняется воркером в program.profile.actualize_result и
 * подтягивается опросом карточки программы. Применение изменений идёт обычным
 * путём «каркас → Human Gate» (отдельного эндпоинта применения нет).
 */

import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";

import type { ActualizeResult } from "../entities/kit";
import { useActualize, useProgram, useUploadFile } from "../shared/api/queries";
import { T } from "../shared/i18n/ru";
import { Badge } from "../shared/ui/Badge";
import { Button } from "../shared/ui/Button";
import { useToast } from "../shared/ui/Toast";
import { ErrorState, PageSkeleton } from "../app/states";

function readActualizeResult(profile: Record<string, unknown>): ActualizeResult | null {
  const raw = profile.actualize_result;
  if (typeof raw !== "object" || raw === null) return null;
  const record = raw as Record<string, unknown>;
  return {
    outdated: Array.isArray(record.outdated)
      ? record.outdated.flatMap((item) => {
          if (typeof item !== "object" || item === null) return [];
          const row = item as Record<string, unknown>;
          return [
            {
              element: String(row.element ?? ""),
              current: String(row.current ?? ""),
              reason: String(row.reason ?? ""),
            },
          ];
        })
      : [],
    proposals: Array.isArray(record.proposals)
      ? record.proposals.flatMap((item) => {
          if (typeof item !== "object" || item === null) return [];
          const row = item as Record<string, unknown>;
          return [
            {
              was: String(row.was ?? ""),
              proposed: String(row.proposed ?? ""),
              rationale: String(row.rationale ?? ""),
            },
          ];
        })
      : [],
    snapshot_date: String(record.snapshot_date ?? ""),
    notes: String(record.notes ?? ""),
  };
}

export function ActualizePage() {
  const { programId } = useParams({ strict: false });
  const id = programId ?? "";
  const toast = useToast();
  const actualize = useActualize(id);
  const uploadFile = useUploadFile();
  const program = useProgram(id || null);

  const [file, setFile] = useState<File | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [waiting, setWaiting] = useState(false);

  const result = program.data ? readActualizeResult(program.data.profile) : null;

  const findOutdated = async () => {
    if (!file) return;
    try {
      const uploaded = await uploadFile.mutateAsync(file);
      await actualize.mutateAsync({ fileIds: [uploaded.file_id] });
      setWaiting(true);
      setSelected(new Set());
      toast.show("success", T.actualize.finding);
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  if (program.isPending) return <PageSkeleton />;
  if (program.isError) {
    return <ErrorState message={T.app.error} onRetry={() => void program.refetch()} />;
  }

  const busy = actualize.isPending || uploadFile.isPending;
  const proposals = result?.proposals ?? [];
  const outdated = result?.outdated ?? [];

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-col gap-xs">
        <h1 className="text-title font-bold text-ink">{T.actualize.title}</h1>
        <p className="text-base text-ink-muted">{T.actualize.subtitle}</p>
      </header>

      <section className="flex flex-wrap items-end gap-md rounded-card border border-line bg-surface p-lg">
        <label className="flex flex-col gap-xs text-caption text-ink-muted">
          {T.actualize.upload}
          <input
            type="file"
            accept=".docx,.pdf,.txt,.md"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="rounded-btn border border-dashed border-line bg-canvas px-md py-sm text-base file:mr-md file:rounded-btn file:border-0 file:bg-primary-bg file:px-md file:py-sm file:text-primary"
          />
        </label>
        <Button
          variant="primary"
          disabled={!file || busy}
          disabledReason={!file ? "Выберите файл старой программы" : undefined}
          busy={busy}
          onClick={() => void findOutdated()}
        >
          {busy ? T.actualize.finding : T.actualize.find}
        </Button>
        {waiting && !result ? (
          <p role="status" className="w-full text-caption text-ink-muted">
            {T.actualize.finding}
            <button
              type="button"
              className="ml-sm text-primary underline underline-offset-2"
              onClick={() => {
                setWaiting(false);
                void program.refetch();
              }}
            >
              Обновить
            </button>
          </p>
        ) : null}
      </section>

      {result ? (
        <section aria-label={T.actualize.result} className="flex flex-col gap-md">
          <h2 className="text-subtitle font-semibold text-ink">{T.actualize.result}</h2>
          {result.snapshot_date ? (
            <p className="text-caption text-ink-muted">Снимок каталогов: {result.snapshot_date}</p>
          ) : null}

          {outdated.length > 0 ? (
            <div className="flex flex-col gap-sm">
              <h3 className="text-base font-semibold text-ink">Устаревшие элементы</h3>
              <ul className="flex flex-col gap-xs">
                {outdated.map((item) => (
                  <li
                    key={`${item.element}-${item.reason}`}
                    className="flex flex-wrap items-center gap-sm rounded-btn bg-warning-bg/60 px-md py-sm"
                  >
                    <Badge variant="warning">{item.element}</Badge>
                    <span className="text-base">{item.current}</span>
                    <span className="text-caption text-ink-muted">{item.reason}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {proposals.length === 0 && outdated.length === 0 ? (
            <p className="rounded-card border border-success/30 bg-success-bg p-lg text-base text-success">
              {T.actualize.empty}
            </p>
          ) : proposals.length > 0 ? (
            <>
              <div className="overflow-x-auto rounded-card border border-line bg-surface">
                <table className="w-full border-collapse text-base">
                  <thead>
                    <tr>
                      <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted">
                        {T.actualize.columns.apply}
                      </th>
                      <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted">
                        {T.actualize.columns.was}
                      </th>
                      <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted">
                        {T.actualize.columns.proposed}
                      </th>
                      <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted">
                        {T.actualize.columns.reason}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {proposals.map((item, index) => {
                      const checked = selected.has(index);
                      return (
                        <tr key={`${item.was}-${index}`}>
                          <td className="border-b border-line/60 px-md py-sm">
                            <label className="flex items-center gap-sm">
                              <input
                                type="checkbox"
                                className="h-4 w-4 accent-primary"
                                checked={checked}
                                aria-label={`${T.actualize.columns.apply}: ${item.was}`}
                                onChange={() =>
                                  setSelected((prev) => {
                                    const next = new Set(prev);
                                    if (next.has(index)) next.delete(index);
                                    else next.add(index);
                                    return next;
                                  })
                                }
                              />
                            </label>
                          </td>
                          <td className="border-b border-line/60 px-md py-sm">{item.was}</td>
                          <td className="border-b border-line/60 px-md py-sm">
                            <Badge variant="info">→</Badge> <span className="ml-xs">{item.proposed}</span>
                          </td>
                          <td className="border-b border-line/60 px-md py-sm text-caption text-ink-muted">
                            {item.rationale}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="flex flex-wrap items-center gap-md">
                <Link
                  to="/programs/$programId/framework"
                  params={{ programId: id }}
                  className="inline-flex min-h-[36px] items-center justify-center rounded-btn bg-primary px-lg py-sm font-medium text-white hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                >
                  {T.actualize.applySelected}
                </Link>
                <span className="text-caption text-ink-muted">{T.actualize.applied}</span>
              </div>
            </>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
