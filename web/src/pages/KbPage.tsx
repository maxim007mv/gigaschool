/**
 * «База знаний» (Д3 §4.6, US-12): документы организации для RAG —
 * загрузка с ролью и областью применения, список, удаление (администратор).
 *
 * Контракт: POST /files → POST /kb/documents {file_id, title, doc_role, applies_to};
 * список — GET /kb/documents (karkas/api/routers/kb.py).
 */

import { useState } from "react";

import type { KbAppliesTo, KbDocRole } from "../entities/kit";
import { formatDateRu } from "../entities/formatters";
import {
  useAddKbDocument,
  useDeleteKbDocument,
  useKbDocuments,
  useMe,
} from "../shared/api/queries";
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
import { EmptyState, ErrorState, PageSkeleton } from "../app/states";

const ROLE_OPTIONS = Object.keys(T.kbRoles) as KbDocRole[];
/** "all" → applies_to = null (ко всем видам программ). */
const SCOPE_OPTIONS: Array<KbAppliesTo | "all"> = ["all", "dpp_pk", "dop"];

export function KbPage() {
  const toast = useToast();
  const documents = useKbDocuments();
  const addDocument = useAddKbDocument();
  const deleteDocument = useDeleteKbDocument();
  const me = useMe();
  const isAdmin = me.data?.role === "admin";

  const [file, setFile] = useState<File | null>(null);
  const [role, setRole] = useState<KbDocRole>("template");
  const [scope, setScope] = useState<KbAppliesTo | "all">("all");
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; filename: string } | null>(null);

  if (documents.isPending) return <PageSkeleton />;
  if (documents.isError) {
    return <ErrorState message={T.app.error} onRetry={() => void documents.refetch()} />;
  }

  const add = async () => {
    if (!file) return;
    try {
      // Хук сам загружает файл (POST /files) и создаёт документ базы знаний.
      await addDocument.mutateAsync({
        file,
        role,
        appliesTo: scope === "all" ? null : [scope],
      });
      toast.show("success", T.kb.added);
      setFile(null);
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    try {
      await deleteDocument.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-col gap-xs">
        <h1 className="text-title font-bold text-ink">{T.kb.title}</h1>
        <p className="text-base text-ink-muted">{T.kb.subtitle}</p>
      </header>

      <section
        aria-label={T.kb.upload}
        className="flex flex-wrap items-end gap-md rounded-card border border-line bg-surface p-lg"
      >
        <label className="flex flex-col gap-xs text-caption text-ink-muted">
          {T.kb.file}
          <input
            type="file"
            accept=".docx,.pdf,.txt,.md"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="rounded-btn border border-dashed border-line bg-canvas px-md py-sm text-base file:mr-md file:rounded-btn file:border-0 file:bg-primary-bg file:px-md file:py-sm file:text-primary"
          />
        </label>
        <label className="flex flex-col gap-xs text-caption text-ink-muted">
          {T.kb.role}
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as KbDocRole)}
            className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base text-ink"
          >
            {ROLE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {T.kbRoles[option]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-xs text-caption text-ink-muted">
          {T.kb.scope}
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value as KbAppliesTo | "all")}
            className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base text-ink"
          >
            {SCOPE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {T.kbAppliesTo[option]}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="primary"
          onClick={() => void add()}
          disabled={!file || addDocument.isPending}
          disabledReason={!file ? "Выберите файл" : undefined}
          busy={addDocument.isPending}
        >
          {addDocument.isPending ? T.kb.uploading : T.kb.upload}
        </Button>
        <p className="w-full text-caption text-ink-muted">{T.kb.roleHint}</p>
      </section>

      {documents.data.length === 0 ? (
        <EmptyState title={T.kb.empty} hint={T.kb.subtitle} />
      ) : (
        <section aria-label={T.kb.list} className="overflow-x-auto rounded-card border border-line bg-surface">
          <table className="w-full border-collapse text-base">
            <caption className="sr-only">{T.kb.list}</caption>
            <thead>
              <tr>
                <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted">
                  {T.kb.columns.name}
                </th>
                <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted">
                  {T.kb.columns.role}
                </th>
                <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted">
                  {T.kb.columns.scope}
                </th>
                <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-right text-caption font-semibold text-ink-muted">
                  {T.kb.columns.chunks}
                </th>
                <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-right text-caption font-semibold text-ink-muted">
                  <span className="sr-only">Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {documents.data.map((document) => (
                <tr key={document.doc_id}>
                  <th scope="row" className="border-b border-line/60 px-md py-sm text-left font-normal">
                    {document.title}
                    <span className="ml-sm text-caption text-ink-muted">
                      {document.filename} · {formatDateRu(document.created_at)}
                    </span>
                  </th>
                  <td className="border-b border-line/60 px-md py-sm">
                    <Badge variant="neutral">{T.kbRoles[document.doc_role]}</Badge>
                  </td>
                  <td className="border-b border-line/60 px-md py-sm">
                    {document.applies_to === null || document.applies_to.length === 0
                      ? T.kbAppliesTo.all
                      : document.applies_to.map((kind) => T.kbAppliesTo[kind]).join(", ")}
                  </td>
                  <td className="tnum border-b border-line/60 px-md py-sm text-right">{document.chunks}</td>
                  <td className="border-b border-line/60 px-md py-sm text-right">
                    {isAdmin ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget({ id: document.doc_id, filename: document.title })}
                      >
                        {T.kb.delete}
                      </Button>
                    ) : (
                      <span className="text-caption text-ink-muted">{T.kb.noRights}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => (!open ? setDeleteTarget(null) : undefined)}>
        <DialogContent>
          <DialogTitle className="text-subtitle font-semibold text-ink">{T.kb.delete}</DialogTitle>
          <DialogDescription className="mt-sm text-base text-ink-muted">
            {T.kb.deleteConfirm} {deleteTarget?.filename ?? ""}
          </DialogDescription>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="ghost">{T.app.cancel}</Button>
            </DialogClose>
            <Button variant="danger" onClick={() => void remove()} busy={deleteDocument.isPending}>
              {T.kb.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
