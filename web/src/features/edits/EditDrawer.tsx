/**
 * EditDrawer — точечная правка элемента комплекта (Д3 §4.5, US-7).
 *
 * Поток: инструкция обычным языком → «Показать, что изменится» (dry_run) →
 * «Применить» → diff-сводка изменённых элементов. Escape закрывает,
 * фокус возвращается на элемент, открывший панель (Radix Dialog).
 */

import { useEffect, useState } from "react";

import type { EditResponse } from "../../entities/kit";
import { ApiError } from "../../shared/api/client";
import { T } from "../../shared/i18n/ru";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { IconCheck } from "../../shared/ui/icons";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "../../shared/ui/Dialog";
import { DiffView } from "./DiffView";
import { ImpactPreview } from "./ImpactPreview";

export interface EditDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  targetRef: string | null;
  targetTitle?: string | null;
  onPlan: (instruction: string) => Promise<EditResponse>;
  onApply: (instruction: string) => Promise<EditResponse>;
}

export function EditDrawer({ open, onOpenChange, targetRef, targetTitle, onPlan, onApply }: EditDrawerProps) {
  const [instruction, setInstruction] = useState("");
  const [plan, setPlan] = useState<EditResponse | null>(null);
  const [applied, setApplied] = useState<EditResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Чистое состояние при открытии на новом элементе.
  useEffect(() => {
    if (open) {
      setInstruction("");
      setPlan(null);
      setApplied(null);
      setError(null);
    }
  }, [open, targetRef]);

  const showImpact = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await onPlan(instruction.trim());
      setPlan(result);
      setApplied(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : T.app.error);
    } finally {
      setBusy(false);
    }
  };

  const applyEdit = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await onApply(instruction.trim());
      setApplied(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : T.app.error);
    } finally {
      setBusy(false);
    }
  };

  const canPlan = instruction.trim().length >= 3 && !busy;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent side="right">
        <DialogTitle className="text-subtitle font-semibold text-ink">{T.kit.edit}</DialogTitle>
        <DialogDescription className="mt-xs text-base text-ink-muted">{T.kit.editHint}</DialogDescription>

        {targetRef ? (
          <p className="mt-md flex items-center gap-sm text-base">
            <Badge variant="info" className="tnum">
              {targetRef}
            </Badge>
            {targetTitle ? <span className="text-ink-muted">{targetTitle}</span> : null}
          </p>
        ) : null}

        <label className="mt-lg flex flex-col gap-xs text-base">
          <span className="font-medium text-ink">Что изменить</span>
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            rows={3}
            placeholder={T.kit.editPlaceholder}
            className="rounded-btn border border-line bg-surface px-md py-sm text-base focus-visible:border-primary"
          />
        </label>

        {error ? (
          <p role="alert" className="mt-md rounded-btn bg-danger-bg px-md py-sm text-caption text-danger">
            {error}
          </p>
        ) : null}

        <div className="mt-lg flex flex-wrap gap-md">
          <Button variant="secondary" onClick={showImpact} disabled={!canPlan} busy={busy && !applied}>
            {T.kit.editPreview}
          </Button>
          <Button variant="primary" onClick={applyEdit} disabled={!plan || busy}>
            {T.kit.editApply}
          </Button>
        </div>

        {plan ? (
          <div className="mt-lg border-t border-line pt-lg">
            <ImpactPreview affected={plan.affected} unchanged={plan.unchanged} />
          </div>
        ) : null}

        {applied && plan ? (
          <div className="mt-lg border-t border-line pt-lg">
            <p className="mb-sm inline-flex items-center gap-xs text-base font-medium text-success" role="status">
              <IconCheck className="h-3.5 w-3.5" />
              {applied.status === "running" ? T.kit.editQueued : T.kit.editApplied}
            </p>
            <DiffView changedRefs={plan.affected} />
          </div>
        ) : null}

        <DialogFooter>
          <DialogClose asChild>
            <Button variant="ghost">{T.app.close}</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
