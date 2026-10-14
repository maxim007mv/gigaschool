/**
 * ExportMenu — выгрузка комплекта (Д3 §4.5, US-9, Д4 §5.12).
 *
 * Форматы: программа .docx, слайды .pptx, тесты GIFT / Moodle XML / CSV,
 * комплект .json, отчёт проверки .docx. Ссылки на файлы живут 15 минут.
 */

import { useState } from "react";

import type { ExportFormat, ExportStatusResponse } from "../../entities/kit";
import { T } from "../../shared/i18n/ru";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  DialogTrigger,
} from "../../shared/ui/Dialog";

export interface ExportMenuProps {
  onExport: (formats: ExportFormat[]) => Promise<{ export_id: string }>;
  status?: ExportStatusResponse | null;
  defaultFormats?: ExportFormat[];
  disabled?: boolean;
}

const ALL_FORMATS: ExportFormat[] = ["docx", "pptx", "gift", "moodle_xml", "csv", "json", "report"];

/** Кликабельны только http(s)-ссылки: javascript:/data: из ответа API не выполняем. */
function isHttpUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

export function ExportMenu({
  onExport,
  status,
  defaultFormats = ["docx", "gift", "json"],
  disabled = false,
}: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<ExportFormat[]>(defaultFormats);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = (format: ExportFormat) => {
    setSelected((prev) =>
      prev.includes(format) ? prev.filter((f) => f !== format) : [...prev, format],
    );
  };

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      await onExport(selected);
    } catch (err) {
      setError(err instanceof Error ? err.message : T.export.failed);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" disabled={disabled} disabledReason={disabled ? T.kit.noKit : undefined}>
          {T.export.title}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle className="text-subtitle font-semibold text-ink">{T.export.title}</DialogTitle>
        <DialogDescription className="mt-xs text-base text-ink-muted">{T.export.subtitle}</DialogDescription>

        <fieldset className="mt-lg" disabled={busy}>
          <legend className="sr-only">{T.export.title}</legend>
          <ul className="grid grid-cols-1 gap-sm sm:grid-cols-2">
            {ALL_FORMATS.map((format) => (
              <li key={format}>
                <label className="flex cursor-pointer items-center gap-sm rounded-btn border border-line px-md py-sm hover:border-primary">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-primary"
                    checked={selected.includes(format)}
                    onChange={() => toggle(format)}
                  />
                  <span className="text-base">{T.export.formats[format]}</span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>

        {error ? (
          <p role="alert" className="mt-md rounded-btn bg-danger-bg px-md py-sm text-caption text-danger">
            {error}
          </p>
        ) : null}

        {/* Статус выгрузки: прогресс, готовые файлы или ошибка */}
        {status ? (
          <div aria-live="polite" className="mt-lg border-t border-line pt-lg">
            {status.status === "running" || status.status === "queued" ? (
              <Badge variant="info">{T.export.running}</Badge>
            ) : null}
            {status.status === "failed" ? <Badge variant="error">{T.export.failed}</Badge> : null}
            {status.status === "ready" ? (
              <div className="flex flex-col gap-sm">
                <Badge variant="ok">{T.export.ready}</Badge>
                <ul className="flex flex-col gap-xs">
                  {(status.files ?? []).map((file) => (
                    <li key={file.kind}>
                      {isHttpUrl(file.url) ? (
                        <a
                          className="text-primary underline underline-offset-2"
                          href={file.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {file.name ?? file.kind}
                        </a>
                      ) : (
                        // Ссылки выдаёт сервер; не-http(s) значения не делаем кликабельными.
                        <span>{file.name ?? file.kind}</span>
                      )}
                    </li>
                  ))}
                </ul>
                <p className="text-caption text-ink-muted">{T.export.linkHint}</p>
              </div>
            ) : null}
          </div>
        ) : null}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost">{T.app.close}</Button>
          </DialogClose>
          <Button
            variant="primary"
            onClick={start}
            disabled={selected.length === 0 || busy}
            busy={busy}
          >
            {T.export.start}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
