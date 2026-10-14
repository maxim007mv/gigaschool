/**
 * «Адаптация» (Д3 §4.6, US-11): новая аудитория или объём — мастер из 3 шагов
 * с предпросмотром нового учебного плана. Создаётся программа-потомок,
 * её каркас снова проходит Human Gate.
 */

import { useMemo, useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";

import type { ProgramForm } from "../entities/kit";
import { moduleWorkload, workloadTotal } from "../entities/kit";
import { T } from "../shared/i18n/ru";
import { Badge } from "../shared/ui/Badge";
import { Button } from "../shared/ui/Button";
import { Stepper } from "../shared/ui/Stepper";
import { useToast } from "../shared/ui/Toast";
import { useAdapt, useFramework } from "../shared/api/queries";
import { ErrorState, PageSkeleton } from "../app/states";

interface ModulePreview {
  ref: string;
  title: string;
  oldHours: number;
  newHours: number;
}

/** Предварительное распределение объёма пропорционально весам модулей. */
export function distributeHours(newContent: number, modules: Array<{ ref: string; title: string; hours: number }>): ModulePreview[] {
  const oldTotal = modules.reduce((sum, module) => sum + module.hours, 0) || 1;
  const quotas = modules.map((module) => (newContent * module.hours) / oldTotal);
  const base = quotas.map((quota) => Math.floor(quota));
  let rest = newContent - base.reduce((sum, value) => sum + value, 0);
  const order = modules
    .map((_module, index) => index)
    .sort((a, b) => quotas[b] - base[b] - (quotas[a] - base[a]) || a - b);
  for (const index of order) {
    if (rest <= 0) break;
    base[index] += 1;
    rest -= 1;
  }
  return modules.map((module, index) => ({
    ref: module.ref,
    title: module.title,
    oldHours: module.hours,
    newHours: base[index],
  }));
}

export function AdaptPage() {
  const { programId } = useParams({ strict: false });
  const id = programId ?? "";
  const toast = useToast();
  const navigate = useNavigate();

  const frameworkQuery = useFramework(id || null);
  const adapt = useAdapt(id);

  const [step, setStep] = useState(0);
  const [audience, setAudience] = useState("");
  const [hoursInput, setHoursInput] = useState("");
  const [form, setForm] = useState<ProgramForm>("part_time");

  const newHours = Number.parseInt(hoursInput, 10);
  const hoursValid = Number.isFinite(newHours) && newHours >= 16 && newHours <= 1000;

  const preview = useMemo(() => {
    if (!frameworkQuery.data || !hoursValid) return null;
    const finalAtt = frameworkQuery.data.program.final_attestation.hours;
    const newContent = Math.max(1, newHours - finalAtt);
    const modules = frameworkQuery.data.modules.map((module) => ({
      ref: module.ref,
      title: module.title,
      hours: workloadTotal(moduleWorkload(module)),
    }));
    return distributeHours(newContent, modules);
  }, [frameworkQuery.data, newHours, hoursValid]);

  if (frameworkQuery.isPending) return <PageSkeleton />;
  if (frameworkQuery.isError) {
    return <ErrorState message={T.app.error} onRetry={() => void frameworkQuery.refetch()} />;
  }

  const create = async () => {
    try {
      // Эндпоинт ставит фоновую задачу: программа-потомок создаётся воркером
      // (сразу после этого она появится в списке «Мои программы»).
      await adapt.mutateAsync({ audience, total_hours: newHours, form });
      toast.show("success", T.adapt.created);
      void navigate({ to: "/" });
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-col gap-xs">
        <Stepper
          current={step}
          maxReached={2}
          labels={[T.adapt.stepAudience, T.adapt.stepHours, T.adapt.stepPreview]}
          onSelect={setStep}
        />
        <h1 className="text-title font-bold text-ink">{T.adapt.title}</h1>
        <p className="text-base text-ink-muted">{T.adapt.subtitle}</p>
      </header>

      {step === 0 ? (
        <section aria-label={T.adapt.stepAudience} className="flex max-w-[640px] flex-col gap-md rounded-card border border-line bg-surface p-lg">
          <label className="flex flex-col gap-xs text-base">
            <span className="font-medium text-ink">{T.adapt.audienceLabel}</span>
            <input
              type="text"
              value={audience}
              onChange={(event) => setAudience(event.target.value)}
              placeholder={T.adapt.audiencePlaceholder}
              className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base"
            />
          </label>
          <label className="flex flex-col gap-xs text-base">
            <span className="font-medium text-ink">{T.adapt.formLabel}</span>
            <select
              value={form}
              onChange={(event) => setForm(event.target.value as ProgramForm)}
              className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base"
            >
              {Object.entries(T.forms).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div>
            <Button variant="primary" onClick={() => setStep(1)} disabled={audience.trim().length === 0}
              disabledReason={audience.trim().length === 0 ? "Опишите новую аудиторию" : undefined}>
              {T.app.next}
            </Button>
          </div>
        </section>
      ) : null}

      {step === 1 ? (
        <section aria-label={T.adapt.stepHours} className="flex max-w-[640px] flex-col gap-md rounded-card border border-line bg-surface p-lg">
          <label className="flex flex-col gap-xs text-base">
            <span className="font-medium text-ink">{T.adapt.hoursLabel}</span>
            <input
              type="text"
              inputMode="numeric"
              value={hoursInput}
              onChange={(event) => setHoursInput(event.target.value)}
              aria-invalid={hoursInput.length > 0 && !hoursValid ? true : undefined}
              className="min-h-[36px] w-40 rounded-btn border border-line bg-surface px-md py-sm text-base tnum"
            />
          </label>
          {hoursInput.length > 0 && !hoursValid ? (
            <p role="alert" className="text-caption text-danger">
              {T.adapt.invalidHours}
            </p>
          ) : null}
          <div className="flex gap-md">
            <Button variant="ghost" onClick={() => setStep(0)}>
              {T.app.back}
            </Button>
            <Button variant="primary" onClick={() => setStep(2)} disabled={!hoursValid}>
              {T.app.next}
            </Button>
          </div>
        </section>
      ) : null}

      {step === 2 && preview ? (
        <section aria-label={T.adapt.stepPreview} className="flex flex-col gap-md">
          <h2 className="text-subtitle font-semibold text-ink">{T.adapt.previewTitle}</h2>
          <p className="text-caption text-ink-muted">{T.adapt.previewNote}</p>

          <div className="overflow-x-auto rounded-card border border-line bg-surface">
            <table role="table" className="w-full border-collapse text-base">
              <thead>
                <tr>
                  <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-left text-caption font-semibold text-ink-muted">
                    {T.adapt.module}
                  </th>
                  <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-right text-caption font-semibold text-ink-muted">
                    {T.adapt.oldHours}
                  </th>
                  <th scope="col" className="border-b border-line bg-canvas px-md py-sm text-right text-caption font-semibold text-ink-muted">
                    {T.adapt.newHours}
                  </th>
                </tr>
              </thead>
              <tbody>
                {preview.map((module) => (
                  <tr key={module.ref}>
                    <th scope="row" className="border-b border-line/60 px-md py-sm text-left font-normal">
                      <span className="tnum text-caption text-ink-muted">{module.ref}</span> {module.title}
                    </th>
                    <td className="tnum border-b border-line/60 px-md py-sm text-right">{module.oldHours} ч</td>
                    <td className="tnum border-b border-line/60 px-md py-sm text-right">
                      <Badge variant={module.newHours === module.oldHours ? "neutral" : "info"}>
                        {module.newHours} ч
                      </Badge>
                    </td>
                  </tr>
                ))}
                <tr>
                  <th scope="row" className="px-md py-sm text-left font-semibold">
                    {T.hours.finalAttestation}
                  </th>
                  <td className="tnum px-md py-sm text-right">
                    {frameworkQuery.data.program.final_attestation.hours} ч
                  </td>
                  <td className="tnum px-md py-sm text-right">
                    {frameworkQuery.data.program.final_attestation.hours} ч
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap gap-md">
            <Button variant="ghost" onClick={() => setStep(1)}>
              {T.app.back}
            </Button>
            <Button variant="primary" onClick={() => void create()} busy={adapt.isPending}>
              {adapt.isPending ? T.adapt.creating : T.adapt.create}
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
