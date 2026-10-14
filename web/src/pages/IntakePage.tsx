/**
 * «Новый запрос» (Д3 §4.1, US-1): свободный текст брифа, файлы с ролями,
 * панель «Что агент уже понял» и индикатор пяти шагов.
 */

import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";

import { useCreateProgram, useUploadFile } from "../shared/api/queries";
import { T } from "../shared/i18n/ru";
import { Badge } from "../shared/ui/Badge";
import { Button } from "../shared/ui/Button";
import { Skeleton } from "../shared/ui/Skeleton";
import { Stepper } from "../shared/ui/Stepper";
import { useToast } from "../shared/ui/Toast";

interface AttachedFile {
  id: string;
  file: File;
  role: string;
}

const FILE_ROLES = Object.keys(T.intake.fileRoles) as Array<keyof typeof T.intake.fileRoles>;

export function IntakePage() {
  const navigate = useNavigate();
  const toast = useToast();
  const uploadFile = useUploadFile();
  const createProgram = useCreateProgram();

  const [brief, setBrief] = useState("");
  const [files, setFiles] = useState<AttachedFile[]>([]);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [understood, setUnderstood] = useState<Record<string, string | null> | null>(null);

  const busy = uploadFile.isPending || createProgram.isPending;

  const submit = async () => {
    if (brief.trim().length === 0) {
      setBriefError(T.intake.briefError);
      return;
    }
    setBriefError(null);
    try {
      const uploaded = [];
      for (const attached of files) {
        const result = await uploadFile.mutateAsync(attached.file);
        uploaded.push({ file_id: result.file_id, role: attached.role });
      }
      const created = await createProgram.mutateAsync({ brief: brief.trim(), files: uploaded });
      toast.show("success", "Запрос разобран");
      setUnderstood(created.detected ?? {});
      // Даём методисту увидеть «что агент понял» перед переходом к вопросам.
      setTimeout(() => {
        void navigate({ to: "/programs/$programId/clarify", params: { programId: created.program_id } });
      }, 900);
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-col gap-sm">
        <Stepper current={0} />
        <h1 className="text-title font-bold text-ink">{T.intake.title}</h1>
      </header>

      <div className="grid grid-cols-1 gap-lg lg:grid-cols-[1.4fr_1fr]">
        <section aria-label={T.intake.brief} className="flex flex-col gap-md rounded-card border border-line bg-surface p-lg">
          <label className="flex flex-col gap-sm text-base">
            <span className="font-medium text-ink">{T.intake.brief}</span>
            <span className="text-caption text-ink-muted">{T.intake.briefHint}</span>
            <textarea
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              rows={8}
              aria-invalid={briefError ? true : undefined}
              aria-describedby={briefError ? "brief-error" : undefined}
              className="rounded-btn border border-line bg-surface px-md py-sm text-base focus-visible:border-primary"
            />
          </label>
          {briefError ? (
            <p id="brief-error" role="alert" className="text-caption text-danger">
              {briefError}
            </p>
          ) : null}

          <div className="flex flex-col gap-sm">
            <span className="font-medium text-ink">{T.intake.files}</span>
            <span className="text-caption text-ink-muted">{T.intake.fileHint}</span>
            <input
              type="file"
              multiple
              accept=".docx,.pdf,.txt,.md"
              aria-label={T.intake.files}
              onChange={(event) => {
                const selected = Array.from(event.target.files ?? []);
                setFiles((prev) => [
                  ...prev,
                  ...selected.map((file, index) => ({
                    id: `${file.name}-${file.size}-${prev.length + index}`,
                    file,
                    role: "sample_program",
                  })),
                ]);
                event.target.value = "";
              }}
              className="rounded-btn border border-dashed border-line bg-canvas px-md py-md text-base file:mr-md file:rounded-btn file:border-0 file:bg-primary-bg file:px-md file:py-sm file:text-primary"
            />

            {files.length > 0 ? (
              <ul className="flex flex-col gap-sm">
                {files.map((attached) => (
                  <li key={attached.id} className="flex flex-wrap items-center justify-between gap-sm rounded-btn bg-canvas px-md py-sm">
                    <span className="text-base text-ink">{attached.file.name}</span>
                    <span className="flex items-center gap-sm">
                      <label className="flex items-center gap-sm text-caption text-ink-muted">
                        {T.intake.fileRole}
                        <select
                          value={attached.role}
                          onChange={(event) =>
                            setFiles((prev) =>
                              prev.map((item) =>
                                item.id === attached.id ? { ...item, role: event.target.value } : item,
                              ),
                            )
                          }
                          className="rounded-btn border border-line bg-surface px-sm py-xs text-base text-ink"
                        >
                          {FILE_ROLES.map((role) => (
                            <option key={role} value={role}>
                              {T.intake.fileRoles[role]}
                            </option>
                          ))}
                        </select>
                      </label>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setFiles((prev) => prev.filter((item) => item.id !== attached.id))}
                      >
                        Убрать
                      </Button>
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>

          <div>
            <Button variant="primary" onClick={() => void submit()} busy={busy}>
              {busy ? T.intake.submitting : T.intake.submit}
            </Button>
          </div>
        </section>

        <aside aria-label={T.intake.understood} className="flex flex-col gap-md rounded-card border border-line bg-surface p-lg">
          <h2 className="text-subtitle font-semibold text-ink">{T.intake.understood}</h2>
          {busy ? (
            <div className="flex flex-col gap-sm" role="status" aria-label={T.app.loading}>
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-5 w-1/2" />
            </div>
          ) : understood === null ? (
            <p className="text-base text-ink-muted">{T.intake.understoodEmpty}</p>
          ) : (
            <dl className="flex flex-col gap-sm text-base">
              {Object.entries(understood).map(([slot, value]) => (
                <div key={slot} className="flex items-center justify-between gap-sm">
                  <dt className="text-ink-muted">
                    {T.intake.detected[slot as keyof typeof T.intake.detected] ?? slot}
                  </dt>
                  <dd>
                    {value ? <span className="text-ink">{value}</span> : <Badge variant="warning">уточним</Badge>}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </aside>
      </div>
    </div>
  );
}
