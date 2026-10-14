/**
 * «Версии» (Д3 §4.6): лента снимков и правок, сравнение двух версий,
 * восстановление как новой версии. История не теряется.
 */

import { useState } from "react";
import { Link, useParams } from "@tanstack/react-router";

import { formatDateTimeRu } from "../entities/formatters";
import { useRestoreVersion, useVersionDiff, useVersions } from "../shared/api/queries";
import { T } from "../shared/i18n/ru";
import { Badge } from "../shared/ui/Badge";
import { Button } from "../shared/ui/Button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "../shared/ui/Dialog";
import { useToast } from "../shared/ui/Toast";
import { ErrorState, PageSkeleton } from "../app/states";
import { DiffView } from "../features/edits/DiffView";

export function VersionsPage() {
  const { programId } = useParams({ strict: false });
  const id = programId ?? "";
  const toast = useToast();

  const versionsQuery = useVersions(id || null);
  const restoreVersion = useRestoreVersion(id);

  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<number | null>(null);

  const diff = useVersionDiff(id || null, from, to);

  if (versionsQuery.isPending) return <PageSkeleton />;
  if (versionsQuery.isError) {
    return <ErrorState message={T.app.error} onRetry={() => void versionsQuery.refetch()} />;
  }

  const items = versionsQuery.data;

  const restore = async () => {
    if (restoreTarget === null) return;
    try {
      await restoreVersion.mutateAsync(restoreTarget);
      toast.show("success", T.versions.restored);
      setRestoreTarget(null);
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-col gap-xs">
        <h1 className="text-title font-bold text-ink">{T.versions.title}</h1>
        <p className="text-base text-ink-muted">{T.versions.subtitle}</p>
        <p>
          <Link
            to="/programs/$programId/kit"
            params={{ programId: id }}
            className="text-base text-primary underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            {T.kit.title}
          </Link>
        </p>
      </header>

      {items.length === 0 ? (
        <p className="text-base text-ink-muted">{T.versions.empty}</p>
      ) : (
        <>
          {/* Сравнение двух версий */}
          <section
            aria-label={T.app.compare}
            className="flex flex-wrap items-end gap-md rounded-card border border-line bg-surface p-lg"
          >
            <label className="flex flex-col gap-xs text-caption text-ink-muted">
              {T.versions.from}
              <select
                value={from ?? ""}
                onChange={(event) => setFrom(event.target.value ? Number(event.target.value) : null)}
                className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base text-ink"
              >
                <option value="">—</option>
                {items.map((item) => (
                  <option key={item.version} value={item.version}>
                    {T.versions.version} {item.version}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-xs text-caption text-ink-muted">
              {T.versions.to}
              <select
                value={to ?? ""}
                onChange={(event) => setTo(event.target.value ? Number(event.target.value) : null)}
                className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base text-ink"
              >
                <option value="">—</option>
                {items.map((item) => (
                  <option key={item.version} value={item.version}>
                    {T.versions.version} {item.version}
                  </option>
                ))}
              </select>
            </label>
            {diff.data ? (
              <DiffView
                changedRefs={diff.data.changed}
                addedRefs={diff.data.added}
                removedRefs={diff.data.removed}
                fromVersion={from}
                toVersion={to}
              />
            ) : diff.isFetching ? (
              <span className="text-caption text-ink-muted">Сравниваем…</span>
            ) : (
              <span className="text-caption text-ink-muted">Выберите две разные версии</span>
            )}
          </section>

          {/* Лента версий */}
          <ol className="flex flex-col gap-md">
            {items.map((item) => (
              <li key={item.version} className="flex flex-col gap-sm rounded-card border border-line bg-surface p-lg">
                <div className="flex flex-wrap items-center justify-between gap-sm">
                  <div className="flex flex-wrap items-center gap-sm">
                    <Badge variant="info" className="tnum">
                      {T.versions.version} {item.version}
                    </Badge>
                    <span className="text-base font-medium text-ink">{item.reason}</span>
                  </div>
                  <Button variant="secondary" size="sm" onClick={() => setRestoreTarget(item.version)}>
                    {T.versions.restore}
                  </Button>
                </div>
                <p className="text-caption text-ink-muted">
                  {T.versions.author}: {item.created_by ?? "—"} · {T.versions.createdAt}:{" "}
                  <span className="tnum">{formatDateTimeRu(item.created_at)}</span>
                </p>
              </li>
            ))}
          </ol>
        </>
      )}

      {/* Подтверждение восстановления */}
      <Dialog open={restoreTarget !== null} onOpenChange={(open) => (!open ? setRestoreTarget(null) : undefined)}>
        <DialogContent>
          <DialogTitle className="text-subtitle font-semibold text-ink">{T.versions.restore}</DialogTitle>
          <DialogDescription className="mt-sm text-base text-ink-muted">
            {T.versions.restoreConfirm}
            {restoreTarget !== null ? ` (${T.versions.version} ${restoreTarget})` : ""}
          </DialogDescription>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost">{T.app.cancel}</Button>
            </DialogClose>
            <Button variant="primary" onClick={() => void restore()} busy={restoreVersion.isPending}>
              {T.versions.restore}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
