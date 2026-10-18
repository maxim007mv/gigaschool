/**
 * «Комплект» (Д3 §4.5): дерево материалов по разделам шаблона, предпросмотр,
 * точечная правка с планом влияния (dry_run), отчёт самопроверки и выгрузка.
 *
 * До утверждения каркаса экран закрыт (Human Gate, 409 GATE_NOT_PASSED).
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";

import type { Assessment, ContentBlock, KitV1, Source } from "../entities/kit";
import {
  formatAssessmentKind,
  formatCount,
  formatPercent,
  formatQuestionType,
  formatRub,
  formatSourceSection,
  formatTokens,
  formatVerifyStatus,
  ISSUE_FORMS,
} from "../entities/formatters";
import { ApiError } from "../shared/api/client";
import {
  USE_MOCKS,
  useCreateEdit,
  useExport,
  useExportStatus,
  useFramework,
  useGenerateKit,
  useKit,
  useRegenerateKitPart,
  useProgramEvents,
  useUsage,
} from "../shared/api/queries";
import { T } from "../shared/i18n/ru";
import { Badge } from "../shared/ui/Badge";
import { Button } from "../shared/ui/Button";
import { cx } from "../shared/ui/cx";
import { ProgramStatusBar } from "../features/progress/ProgramStatusBar";
import { Stepper } from "../shared/ui/Stepper";
import { useToast } from "../shared/ui/Toast";
import { ErrorState, PageSkeleton } from "../app/states";
import { EditDrawer } from "../features/edits/EditDrawer";
import { ExportMenu } from "../features/export/ExportMenu";
import { ReportPanel } from "../features/report/ReportPanel";
import { CoverageMatrix } from "../features/coverage/CoverageMatrix";
import { iterOutcomes, iterTopics } from "../entities/kit";

type Selection =
  | { kind: "block"; block: ContentBlock }
  | { kind: "assessments"; moduleRef: string | null }
  | { kind: "sources" }
  | { kind: "final" }
  | null;

export function KitPage() {
  const { programId } = useParams({ strict: false });
  const id = programId ?? "";
  const toast = useToast();

  const kitQuery = useKit(id || null);
  const frameworkQuery = useFramework(id || null);
  const generateKit = useGenerateKit(id);
  const createEdit = useCreateEdit(id);
  const regeneratePart = useRegenerateKitPart(id);
  const exportMutation = useExport(id);

  const [selection, setSelection] = useState<Selection>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [exportId, setExportId] = useState<string | null>(null);

  const exportStatus = useExportStatus(exportId);

  // Прогресс долгой сборки приходит по SSE (Д4 §6.7). В dev с моками поток не нужен.
  useProgramEvents(
    USE_MOCKS ? null : id || null,
    (event) => {
      if (event.name === "progress") {
        toast.show("success", `${event.payload.label} — ${event.payload.done} из ${event.payload.total}`);
      }
      if (event.name === "kit_ready") {
        toast.show("success", "Комплект готов");
        void kitQuery.refetch();
      }
      if (event.name === "job_failed") {
        toast.show("error", `Ошибка сборки: ${event.payload.detail}`);
      }
    },
    Boolean(id) && !USE_MOCKS,
  );

  const kit = kitQuery.data ?? null;

  // Сразу открываем первый материал — иначе экран выглядит «пустым».
  useEffect(() => {
    if (!kit || selection !== null) return;
    const first =
      kit.content.module_programs[0] ??
      kit.content.lecture_plans[0] ??
      kit.content.slides[0] ??
      null;
    if (first) {
      setSelection({ kind: "block", block: first });
      return;
    }
    if (kit.framework.modules[0]) {
      setSelection({ kind: "assessments", moduleRef: kit.framework.modules[0].ref });
    }
  }, [kit, selection]);

  const editTargetRef = useMemo(() => {
    if (!selection) return null;
    if (selection.kind === "block") {
      const block = selection.block;
      if (block.topic_ref) return block.topic_ref;
      if (block.module_ref && block.kind === "module_program") return block.module_ref;
      return block.ref;
    }
    if (selection.kind === "assessments") return selection.moduleRef;
    return null;
  }, [selection]);

  const regenerateParts = useMemo((): Array<"slides" | "tests" | "lecture_plan" | "module_program" | "tasks"> => {
    if (!selection || selection.kind !== "block") return ["slides", "tests", "lecture_plan"];
    if (selection.block.kind === "slides") return ["slides"];
    if (selection.block.kind === "lecture_plan") return ["lecture_plan"];
    if (selection.block.kind === "module_program") return ["module_program"];
    return ["slides", "tests", "lecture_plan"];
  }, [selection]);

  if (kitQuery.isPending) return <PageSkeleton />;

  // Human Gate: комплект недоступен до утверждения каркаса.
  if (kitQuery.isError) {
    const error = kitQuery.error;
    const gate = error instanceof ApiError && error.code === "GATE_NOT_PASSED";
    const frameworkApproved = frameworkQuery.data?.status === "framework_approved";
    return (
      <div className="flex flex-col gap-lg">
        <Stepper current={4} maxReached={frameworkApproved ? 4 : 2} />
        <section className="flex flex-col items-start gap-md rounded-card border border-warning/30 bg-warning-bg p-xl">
          <h1 className="text-title font-bold text-ink">
            {gate || !frameworkApproved ? T.kit.gateTitle : T.kit.noKit}
          </h1>
          <p className="max-w-[640px] text-base text-warning">
            {gate || !frameworkApproved ? T.kit.gateText : T.kit.generateEstimate}
          </p>
          {gate || !frameworkApproved ? (
            <Link
              to="/programs/$programId/framework"
              params={{ programId: id }}
              className="inline-flex min-h-[36px] items-center justify-center rounded-btn bg-primary px-lg py-sm font-medium text-white hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              {T.kit.gateButton}
            </Link>
          ) : (
            <Button
              variant="primary"
              busy={generateKit.isPending}
              onClick={() =>
                void generateKit
                  .mutateAsync()
                  .then(() => toast.show("success", T.kit.generating))
                  .catch((err: unknown) =>
                    toast.show("error", err instanceof Error ? err.message : T.app.error),
                  )
              }
            >
              {generateKit.isPending ? T.kit.generating : T.kit.generate}
            </Button>
          )}
        </section>
      </div>
    );
  }

  if (!kit) return <ErrorState message={T.app.error} onRetry={() => void kitQuery.refetch()} />;

  const editTargetTitle =
    selection?.kind === "block"
      ? blockTitle(selection.block)
      : selection?.kind === "assessments"
        ? `${T.kit.items.assessments}${selection.moduleRef ? ` · ${selection.moduleRef}` : ""}`
        : null;

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div className="flex flex-col gap-xs">
          <Stepper current={4} />
          <ProgramStatusBar programId={id} currentStep={4} />
          <h1 className="text-title font-bold text-ink">{kit.program.title}</h1>
          <p className="text-base text-ink-muted">
            Слева выберите материал — справа текст. Снизу можно скачать файлы.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-md">
          <Link
            to="/programs/$programId/framework"
            params={{ programId: id }}
            className="text-base text-primary underline underline-offset-2"
          >
            ← К часам
          </Link>
          <Button
            variant="secondary"
            onClick={() => setEditOpen(true)}
            disabled={!selection}
            disabledReason={!selection ? "Сначала выберите материал слева" : undefined}
          >
            {T.kit.edit}
          </Button>
          <Button
            variant="secondary"
            title={T.kit.regenerateHint}
            disabled={!editTargetRef || regeneratePart.isPending}
            disabledReason={!editTargetRef ? "Сначала выберите тему или модуль" : undefined}
            onClick={async () => {
              if (!editTargetRef) return;
              try {
                await regeneratePart.mutateAsync({
                  targetRef: editTargetRef,
                  parts: regenerateParts,
                });
                toast.show("success", T.kit.regenerateStarted);
              } catch (err) {
                toast.show("error", err instanceof ApiError ? err.message : T.app.error);
              }
            }}
          >
            {T.kit.regenerate}
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-lg xl:grid-cols-[240px_1fr_340px]">
        <KitTree kit={kit} selection={selection} onSelect={setSelection} />

        <section aria-label={T.kit.preview} className="flex flex-col gap-md rounded-card border border-line bg-surface p-lg">
          {selection === null ? (
            <p className="text-base text-ink-muted">{T.kit.previewEmpty}</p>
          ) : (
            <KitPreview kit={kit} selection={selection} />
          )}
        </section>

        <div className="flex flex-col gap-md">
          <CoverageMatrix
            outcomes={iterOutcomes(kit).map((o) => ({
              ref: o.ref,
              type: o.type,
              text: o.text,
            }))}
            topics={iterTopics(kit).map((t) => ({
              ref: t.ref,
              title: t.title,
              outcome_refs: t.outcome_refs,
            }))}
            assessments={kit.content.assessments}
            showCounters
            readOnly
            onToggleLink={() => {
              /* на экране комплекта связи только для просмотра */
            }}
          />
          <ReportPanel
            report={kit.report}
            className={kit.report && !kit.report.passed ? "border-2 border-error/40" : undefined}
            onExportReport={async () => {
              const result = await exportMutation.mutateAsync(["report"]);
              setExportId(result.export_id);
            }}
          />
          <EffectPanel programId={id} totalHours={kit.program.total_hours} />
          <ExportMenu
            onExport={async (formats) => {
              const result = await exportMutation.mutateAsync(formats);
              setExportId(result.export_id);
              return result;
            }}
            status={exportStatus.data ?? null}
          />
        </div>
      </div>

      <EditDrawer
        open={editOpen}
        onOpenChange={setEditOpen}
        targetRef={editTargetRef}
        targetTitle={editTargetTitle}
        onPlan={async (instruction) =>
          createEdit.mutateAsync({ targetRef: editTargetRef ?? "", instruction, dryRun: true })
        }
        onApply={async (instruction) => {
          const result = await createEdit.mutateAsync({
            targetRef: editTargetRef ?? "",
            instruction,
            dryRun: false,
          });
          // Правка поставлена фоновой задачей: результат придёт событием
          // edit_applied и перезапросом комплекта (см. useProgramEvents).
          return result;
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Дерево комплекта
// ---------------------------------------------------------------------------

function KitTree({
  kit,
  selection,
  onSelect,
}: {
  kit: KitV1;
  selection: Selection;
  onSelect: (selection: Selection) => void;
}) {
  const unverified = kit.content.sources.filter((source) => source.status !== "verified").length;
  const staleCount = [
    ...kit.content.module_programs,
    ...kit.content.lecture_plans,
    ...kit.content.slides,
  ].filter((block) => block.stale).length;

  const itemClass = (active: boolean) =>
    cx(
      "w-full rounded-btn px-md py-sm text-left text-base",
      "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
      active ? "bg-primary-bg font-medium text-primary" : "text-ink hover:bg-canvas",
    );

  return (
    <nav aria-label={T.kit.contents} className="flex flex-col gap-md rounded-card border border-line bg-surface p-md">
      <h2 className="px-sm text-caption font-semibold uppercase tracking-wide text-ink-muted">
        {T.kit.contents}
        {staleCount > 0 ? <Badge variant="warning" className="ml-sm">{formatCount(staleCount, ISSUE_FORMS)}</Badge> : null}
      </h2>

      {kit.framework.modules.map((module) => {
        const moduleProgram = kit.content.module_programs.find((b) => b.module_ref === module.ref);
        const lectures = kit.content.lecture_plans.filter((b) => b.module_ref === module.ref);
        const slides = kit.content.slides.filter((b) => b.module_ref === module.ref);
        const moduleAssessments = kit.content.assessments.filter(
          (a) => a.module_ref === module.ref || module.topics.some((t) => t.ref === a.topic_ref),
        );

        return (
          <section key={module.ref} aria-label={module.title} className="flex flex-col gap-xs">
            <h3 className="px-sm text-base font-semibold text-ink">
              <span className="tnum text-caption text-ink-muted">{module.ref}</span> {module.title}
            </h3>

            {moduleProgram ? (
              <TreeItem
                active={selection?.kind === "block" && selection.block.ref === moduleProgram.ref}
                onClick={() => onSelect({ kind: "block", block: moduleProgram })}
                label={T.kit.items.module_program}
                stale={moduleProgram.stale}
                itemClass={itemClass}
              />
            ) : null}

            {lectures.map((block) => (
              <TreeItem
                key={block.ref}
                active={selection?.kind === "block" && selection.block.ref === block.ref}
                onClick={() => onSelect({ kind: "block", block })}
                label={`${T.kit.items.lecture_plan} · ${block.topic_ref ?? block.ref}`}
                stale={block.stale}
                itemClass={itemClass}
              />
            ))}

            {slides.map((block) => (
              <TreeItem
                key={block.ref}
                active={selection?.kind === "block" && selection.block.ref === block.ref}
                onClick={() => onSelect({ kind: "block", block })}
                label={`${T.kit.items.slides} · ${block.topic_ref ?? block.ref}`}
                stale={block.stale}
                itemClass={itemClass}
              />
            ))}

            <TreeItem
              active={selection?.kind === "assessments" && selection.moduleRef === module.ref}
              onClick={() => onSelect({ kind: "assessments", moduleRef: module.ref })}
              label={`${T.kit.items.assessments} (${moduleAssessments.length})`}
              itemClass={itemClass}
            />
          </section>
        );
      })}

      <section aria-label={T.kit.items.sources} className="flex flex-col gap-xs border-t border-line pt-sm">
        <TreeItem
          active={selection?.kind === "sources"}
          onClick={() => onSelect({ kind: "sources" })}
          label={`${T.kit.items.sources} (${kit.content.sources.length})`}
          badge={unverified > 0 ? `${unverified} ${T.kit.unverifiedBadge}` : undefined}
          itemClass={itemClass}
        />
        <TreeItem
          active={selection?.kind === "final"}
          onClick={() => onSelect({ kind: "final" })}
          label={T.kit.items.final}
          itemClass={itemClass}
        />
      </section>
    </nav>
  );
}

function TreeItem({
  active,
  onClick,
  label,
  stale,
  badge,
  itemClass,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  stale?: boolean;
  badge?: string;
  itemClass: (active: boolean) => string;
}) {
  return (
    <button type="button" className={itemClass(active)} aria-pressed={active} onClick={onClick}>
      <span className="flex flex-wrap items-center gap-xs">
        <span>{label}</span>
        {stale ? <Badge variant="warning">{T.kit.staleBadge}</Badge> : null}
        {badge ? <Badge variant="warning">{badge}</Badge> : null}
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Предпросмотр
// ---------------------------------------------------------------------------

function KitPreview({ kit, selection }: { kit: KitV1; selection: NonNullable<Selection> }) {
  if (selection.kind === "block") return <BlockPreview block={selection.block} />;
  if (selection.kind === "assessments") return <AssessmentsPreview kit={kit} moduleRef={selection.moduleRef} />;
  if (selection.kind === "sources") return <SourcesPreview sources={kit.content.sources} />;
  return <FinalPreview kit={kit} />;
}

function blockTitle(block: ContentBlock): string {
  switch (block.kind) {
    case "module_program":
      return `${T.kit.items.module_program}${block.module_ref ? ` · ${block.module_ref}` : ""}`;
    case "lecture_plan":
      return `${T.kit.items.lecture_plan}${block.topic_ref ? ` · ${block.topic_ref}` : ""}`;
    case "slides":
      return `${T.kit.items.slides}${block.topic_ref ? ` · ${block.topic_ref}` : ""}`;
    case "annotation":
      return T.kit.items.annotations;
    default:
      return block.ref;
  }
}

function BlockPreview({ block }: { block: ContentBlock }) {
  const summary = asString(block.body.summary);
  const text = asString(block.body.text);
  const goal = asString(block.body.goal);
  const sections = asSections(block.body.sections);
  const blocks = asTitledBlocks(block.body.blocks);
  const slides = asSlides(block.body.slides);
  const selfCheck = asStringArray(block.body.self_check);

  return (
    <article className="flex flex-col gap-md">
      <header className="flex flex-wrap items-center gap-sm">
        <h2 className="text-subtitle font-semibold text-ink">{blockTitle(block)}</h2>
        <Badge variant="neutral" className="tnum">
          {block.ref}
        </Badge>
        {block.stale ? <Badge variant="warning">{T.kit.staleBadge}</Badge> : null}
      </header>

      {summary ? <p>{summary}</p> : null}
      {text ? <p>{text}</p> : null}
      {goal ? (
        <p>
          <strong>Цель занятия:</strong> {goal}
        </p>
      ) : null}

      {sections.length > 0 ? (
        <ol className="flex flex-col gap-sm">
          {sections.map((section) => (
            <li key={section.title} className="rounded-btn bg-canvas px-md py-sm">
              <h3 className="text-base font-semibold text-ink">{section.title}</h3>
              {section.text ? <p className="mt-xs text-base">{section.text}</p> : null}
            </li>
          ))}
        </ol>
      ) : null}

      {blocks.length > 0 ? (
        <ol className="flex flex-col gap-sm">
          {blocks.map((item) => (
            <li key={item.title} className="flex items-baseline justify-between gap-md rounded-btn bg-canvas px-md py-sm">
              <span>{item.title}</span>
              {typeof item.minutes === "number" ? <span className="tnum text-caption text-ink-muted">{item.minutes} мин</span> : null}
            </li>
          ))}
        </ol>
      ) : null}

      {slides.length > 0 ? (
        <ol className="flex flex-col gap-sm">
          {slides.map((slide) => (
            <li key={slide.title} className="rounded-btn border border-line px-md py-sm">
              <h3 className="text-base font-semibold text-ink">{slide.title}</h3>
              <ul className="mt-xs list-disc pl-lg text-base text-ink-muted">
                {slide.bullets.map((bullet) => (
                  <li key={bullet}>{bullet}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      ) : null}

      {selfCheck.length > 0 ? (
        <section>
          <h3 className="text-base font-semibold text-ink">Вопросы для самопроверки</h3>
          <ul className="list-disc pl-lg">
            {selfCheck.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {!summary && !text && !goal && sections.length === 0 && blocks.length === 0 && slides.length === 0 ? (
        <p className="text-base text-ink-muted">Предпросмотр содержания появится после полной сборки комплекта.</p>
      ) : null}

      <p className="text-caption text-ink-muted">
        Связи: тема {block.topic_ref ?? "—"}, модуль {block.module_ref ?? "—"}
      </p>
    </article>
  );
}

function AssessmentsPreview({ kit, moduleRef }: { kit: KitV1; moduleRef: string | null }) {
  const assessments = kit.content.assessments.filter((a) => {
    if (!moduleRef) return true;
    if (a.module_ref === moduleRef) return true;
    return kit.framework.modules
      .find((m) => m.ref === moduleRef)
      ?.topics.some((t) => t.ref === a.topic_ref);
  });

  return (
    <article className="flex flex-col gap-md">
      <h2 className="text-subtitle font-semibold text-ink">
        {T.kit.items.assessments}
        {moduleRef ? ` · ${moduleRef}` : ""}: {assessments.length}
      </h2>

      {assessments.map((assessment) => (
        <AssessmentCard key={assessment.ref} assessment={assessment} />
      ))}
    </article>
  );
}

function AssessmentCard({ assessment }: { assessment: Assessment }) {
  return (
    <section data-kind={assessment.kind} className="flex flex-col gap-sm rounded-card border border-line p-lg">
      <header className="flex flex-wrap items-center gap-sm">
        <Badge variant="info">{formatAssessmentKind(assessment.kind)}</Badge>
        <span className="tnum text-caption text-ink-muted">{assessment.ref}</span>
        {assessment.qtype ? (
          <span className="text-caption text-ink-muted">{formatQuestionType(assessment.qtype)}</span>
        ) : null}
        {assessment.outcome_refs.map((ref) => (
          <Badge key={ref} variant="neutral" className="tnum">
            {ref}
          </Badge>
        ))}
      </header>

      <p className="text-base text-ink">{assessment.stem}</p>

      {assessment.options.length > 0 ? (
        <ul className="flex flex-col gap-xs">
          {assessment.options.map((option) => {
            const correct = assessment.answer_key?.correct.includes(option.id) ?? false;
            return (
              <li key={option.id} className={cx("flex items-center gap-sm rounded-btn px-md py-xs", correct && "bg-success-bg")}>
                <span aria-hidden="true" className={cx("font-bold", correct ? "text-success" : "text-line")}>
                  {correct ? "✓" : "○"}
                </span>
                <span className={cx("text-base", correct && "text-success")}>{option.text}</span>
                {correct ? <span className="sr-only">правильный ответ</span> : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {assessment.answer_key?.explanation ? (
        <p className="text-caption text-ink-muted">Пояснение: {assessment.answer_key.explanation}</p>
      ) : null}

      {assessment.rubric.length > 0 ? (
        <table className="w-full border-collapse text-caption">
          <caption className="sr-only">Критерии оценивания</caption>
          <thead>
            <tr>
              <th scope="col" className="border-b border-line py-xs text-left font-semibold text-ink-muted">
                Критерий
              </th>
              <th scope="col" className="border-b border-line py-xs text-right font-semibold text-ink-muted">
                Баллы
              </th>
              <th scope="col" className="border-b border-line py-xs text-left font-semibold text-ink-muted">
                Уровни
              </th>
            </tr>
          </thead>
          <tbody>
            {assessment.rubric.map((criterion) => (
              <tr key={criterion.criterion}>
                <td className="border-b border-line/60 py-xs">{criterion.criterion}</td>
                <td className="tnum border-b border-line/60 py-xs text-right">{criterion.max_points}</td>
                <td className="border-b border-line/60 py-xs text-ink-muted">{criterion.levels.join("; ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

function SourcesPreview({ sources }: { sources: Source[] }) {
  const unverified = sources.filter((source) => source.status !== "verified").length;

  return (
    <article className="flex flex-col gap-md">
      <header className="flex flex-wrap items-center gap-sm">
        <h2 className="text-subtitle font-semibold text-ink">{T.kit.items.sources}</h2>
        {unverified > 0 ? <Badge variant="warning">{unverified} {T.kit.unverifiedBadge}</Badge> : null}
      </header>

      {(["normative", "main", "additional", "internet", "software"] as const).map((section) => {
        const items = sources.filter((source) => source.section === section);
        if (items.length === 0) return null;
        return (
          <section key={section}>
            <h3 className="mb-sm text-base font-semibold text-ink">{formatSourceSection(section)}</h3>
            <ul className="flex flex-col gap-sm">
              {items.map((source) => (
                <li key={source.ref} className="flex flex-wrap items-center gap-sm rounded-btn bg-canvas px-md py-sm">
                  <span className="tnum text-caption text-ink-muted">{source.ref}</span>
                  <span className="text-base">{source.citation}</span>
                  <Badge variant={source.status === "verified" ? "ok" : "warning"}>
                    {formatVerifyStatus(source.status)}
                  </Badge>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </article>
  );
}

function FinalPreview({ kit }: { kit: KitV1 }) {
  const finalItems = kit.content.assessments.filter((a) =>
    ["final_project", "exam_task", "interview_question", "portfolio_item"].includes(a.kind),
  );

  return (
    <article className="flex flex-col gap-md">
      <h2 className="text-subtitle font-semibold text-ink">{T.kit.items.final}</h2>
      <p className="text-base">
        Форма: <strong>{kit.framework.final_attestation.form}</strong>,{" "}
        <span className="tnum">{kit.framework.final_attestation.hours} ч</span>
      </p>
      {finalItems.map((assessment) => (
        <AssessmentCard key={assessment.ref} assessment={assessment} />
      ))}
    </article>
  );
}

/** Блок «Эффект» (Д3 §4.5): метрики для защиты — токены Cloud.ru и экономия методиста. */
function EffectPanel({ programId, totalHours }: { programId: string; totalHours: number }) {
  const usage = useUsage(programId || null);
  if (usage.isPending || !usage.data) return null;
  const data = usage.data;
  const manualBaselineHours = data.manual_baseline_hours ?? 2 * 40 * 0.5;
  return (
    <section aria-label={T.kit.effect} className="flex flex-col gap-sm rounded-card border border-line bg-surface p-lg">
      <h2 className="text-base font-semibold text-ink">{T.kit.effect}</h2>
      <p className="text-caption text-ink-muted">
        Для защиты: стоимость генерации программы ({totalHours} ч) в токенах Cloud.ru и оценка экономии
        времени методиста относительно ручной сборки (~2 нед. × 50% занятости).
      </p>
      <dl className="grid grid-cols-2 gap-sm">
        <div>
          <dt className="text-caption text-ink-muted">Токены на программу</dt>
          <dd className="tnum text-base text-ink">{formatTokens(data.tokens)}</dd>
        </div>
        <div>
          <dt className="text-caption text-ink-muted">Стоимость Cloud.ru</dt>
          <dd className="tnum text-base text-ink">{formatRub(data.cost_rub)}</dd>
        </div>
        <div>
          <dt className="text-caption text-ink-muted">Вызовов модели</dt>
          <dd className="tnum text-base text-ink">{data.calls}</dd>
        </div>
        <div>
          <dt className="text-caption text-ink-muted">Из кэша</dt>
          <dd className="tnum text-base text-ink">{formatPercent(data.cache_hit_pct)}</dd>
        </div>
        {typeof data.methodologist_active_hours === "number" ? (
          <div>
            <dt className="text-caption text-ink-muted">Активное время методиста</dt>
            <dd className="tnum text-base text-ink">{data.methodologist_active_hours} ч</dd>
          </div>
        ) : null}
        {typeof data.savings_hours === "number" ? (
          <div className="col-span-2">
            <dt className="text-caption text-ink-muted">Экономия времени методиста</dt>
            <dd className="tnum text-base text-ink">
              {data.savings_hours} ч (база {manualBaselineHours} ч − активная проверка)
            </dd>
          </div>
        ) : null}
        {data.first_time_framework_approval !== null && data.first_time_framework_approval !== undefined ? (
          <div className="col-span-2">
            <dt className="text-caption text-ink-muted">First-Time Approval (каркас)</dt>
            <dd className="text-base text-ink">
              {data.first_time_framework_approval ? "да, с первой итерации" : "нет, были доработки"}
            </dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Безопасное чтение произвольного body у блока содержания
// ---------------------------------------------------------------------------

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function asSections(value: unknown): Array<{ title: string; text: string | null }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "object" || item === null) return [];
    const record = item as Record<string, unknown>;
    const title = asString(record.title);
    if (!title) return [];
    return [{ title, text: asString(record.text) }];
  });
}

function asTitledBlocks(value: unknown): Array<{ title: string; minutes: number | null }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "object" || item === null) return [];
    const record = item as Record<string, unknown>;
    const title = asString(record.title);
    if (!title) return [];
    const minutes = typeof record.minutes === "number" ? record.minutes : null;
    return [{ title, minutes }];
  });
}

function asSlides(value: unknown): Array<{ title: string; bullets: string[] }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "object" || item === null) return [];
    const record = item as Record<string, unknown>;
    const title = asString(record.title);
    if (!title) return [];
    return [{ title, bullets: asStringArray(record.bullets) }];
  });
}
