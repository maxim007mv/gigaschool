/**
 * HoursGrid — таблица учебного плана с живым пересчётом (Д3 §4.3).
 *
 * - редактируются только часы тем; строки модулей и итоги вычисляются;
 * - нарушения подсвечиваются на всех уровнях: ячейка → тема → модуль → итог;
 * - ячейки можно закрепить замком (солвер не меняет закреплённые значения);
 * - навигация как в Excel: стрелки, Enter, Tab; числа — tabular-nums;
 * - при форме с ДОТ появляется столбец «из них дистанционно»;
 * - «Утвердить каркас» недоступна, пока есть ошибки, рядом — причина.
 */

import { Fragment, useMemo, useRef, type KeyboardEvent } from "react";

import { emptyWorkload, isCellLocked, workloadTotal, type Activity, type Workload } from "../../entities/kit";
import { T } from "../../shared/i18n/ru";
import { Badge } from "../../shared/ui/Badge";
import { Button } from "../../shared/ui/Button";
import { cx } from "../../shared/ui/cx";
import { Table, TableCell, TableHeaderCell } from "../../shared/ui/Table";
import { ERROR_FORMS, formatCount } from "../../entities/formatters";
import { THRESHOLDS, type RuleCode } from "./rules";
import { SumCell, type SumCellState } from "./SumCell";
import { useLiveHours, type LiveConstraints, type LiveIssue, type LivePlan } from "./useLiveHours";

export interface HoursGridProps {
  plan: LivePlan;
  constraints: LiveConstraints;
  /** Показывать столбец «из них дистанционно» (форма с ДОТ). */
  hasDot?: boolean;
  /** Только чтение (эксперт, руководитель). */
  readOnly?: boolean;
  busy?: boolean;
  /** Есть ли право утверждать каркас (Human Gate: методист или руководитель). */
  canApprove?: boolean;
  /** Внешняя причина блокировки утверждения (несохранённые правки, замечания). */
  approveBlockedReason?: string;
  /** Показывать кнопку утверждения (скрывается для уже утверждённого каркаса). */
  showApprove?: boolean;
  onCellChange?: (topicRef: string, activity: Activity, hours: number) => void;
  onToggleLock?: (topicRef: string, activity: Activity) => void;
  onApprove?: () => void;
}

const ACTIVITY_COLUMNS: ReadonlyArray<{ key: Activity; label: string; full: string }> = [
  { key: "lecture", label: T.hours.columns.lecture, full: T.hours.activityFull.lecture },
  { key: "practice", label: T.hours.columns.practice, full: T.hours.activityFull.practice },
  { key: "lab", label: T.hours.columns.lab, full: T.hours.activityFull.lab },
  { key: "self_study", label: T.hours.columns.selfStudy, full: T.hours.activityFull.self_study },
  { key: "current_control", label: T.hours.columns.control, full: T.hours.activityFull.current_control },
];

const PROGRAM_ISSUES_KEY = "__program__";

function parseHours(raw: string): number {
  const digits = raw.replace(/[^\d]/g, "");
  if (digits === "") return 0;
  return Math.min(THRESHOLDS.maxHoursPerCell, Number.parseInt(digits, 10));
}

function caretAtEnd(input: HTMLInputElement): boolean {
  const position = input.selectionStart;
  return position === null || position >= input.value.length;
}

function caretAtStart(input: HTMLInputElement): boolean {
  const position = input.selectionStart;
  return position === null || position <= 0;
}

export function HoursGrid({
  plan,
  constraints,
  hasDot,
  readOnly = false,
  busy = false,
  canApprove = true,
  approveBlockedReason,
  showApprove = true,
  onCellChange,
  onToggleLock,
  onApprove,
}: HoursGridProps) {
  const result = useLiveHours(plan, constraints);
  const showDot = hasDot ?? constraints.distanceMode ?? false;
  const columnCount = ACTIVITY_COLUMNS.length + (showDot ? 1 : 0);
  // Клавиатурная навигация — только по редактируемым ячейкам (5 видов работ);
  // столбец «из них дистанционно» — вычисляемый (SumCell), в обходе не участвует.
  const navColumns = ACTIVITY_COLUMNS.length;

  // Карта замечаний: ref темы/модуля → список нарушений.
  const issuesByRef = useMemo(() => {
    const map = new Map<string, LiveIssue[]>();
    for (const item of result.issues) {
      const key = item.ref ?? PROGRAM_ISSUES_KEY;
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    return map;
  }, [result.issues]);

  const issuesFor = (ref: string): LiveIssue[] => issuesByRef.get(ref) ?? [];
  const programIssues = issuesByRef.get(PROGRAM_ISSUES_KEY) ?? [];
  const hasProgramRule = (rules: RuleCode[]): boolean => programIssues.some((i) => rules.includes(i.rule));

  // Порядок ячеек для клавиатурной навигации (по строкам, слева направо).
  const cellKeys = useMemo(() => {
    const keys: string[] = [];
    for (const module of plan.modules) {
      for (const topic of module.topics) {
        for (const column of ACTIVITY_COLUMNS) keys.push(`${topic.ref}:${column.key}`);
      }
    }
    return keys;
  }, [plan]);

  const cellRefs = useRef(new Map<string, HTMLInputElement>());
  const registerCell = (key: string) => (el: HTMLInputElement | null) => {
    if (el) cellRefs.current.set(key, el);
    else cellRefs.current.delete(key);
  };

  const moveVertical = (key: string, direction: number) => {
    const index = cellKeys.indexOf(key);
    if (index < 0) return;
    const next = index + direction * navColumns;
    if (next < 0 || next >= cellKeys.length) return;
    cellRefs.current.get(cellKeys[next])?.focus();
  };

  const moveHorizontal = (key: string, direction: number) => {
    const index = cellKeys.indexOf(key);
    if (index < 0) return;
    const rowStart = Math.floor(index / navColumns) * navColumns;
    const next = index + direction;
    if (next < rowStart || next >= rowStart + navColumns) return;
    cellRefs.current.get(cellKeys[next])?.focus();
  };

  const handleCellKeyDown = (event: KeyboardEvent<HTMLInputElement>, key: string) => {
    switch (event.key) {
      case "ArrowDown":
      case "Enter":
        event.preventDefault();
        moveVertical(key, 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        moveVertical(key, -1);
        break;
      case "ArrowRight":
        if (caretAtEnd(event.currentTarget)) {
          event.preventDefault();
          moveHorizontal(key, 1);
        }
        break;
      case "ArrowLeft":
        if (caretAtStart(event.currentTarget)) {
          event.preventDefault();
          moveHorizontal(key, -1);
        }
        break;
      default:
        break;
    }
  };

  const firstIssue = result.issues[0];
  const approveDisabled =
    readOnly || !result.passed || busy || !onApprove || Boolean(approveBlockedReason) || !canApprove;
  const approveReason = readOnly
    ? T.hours.noRights
    : approveBlockedReason
      ? approveBlockedReason
      : !result.passed && firstIssue
        ? firstIssue.message
        : !canApprove
          ? T.hours.noRights
          : undefined;

  /** Ячейка с числовым вводом и замком. */
  const renderEditableCell = (
    topicRef: string,
    topicLabel: string,
    activity: Activity,
    columnLabel: string,
    value: number,
    locked: boolean,
    extraClass?: string,
  ) => {
    const key = `${topicRef}:${activity}`;
    return (
      <TableCell numeric className={cx("hours-cell", extraClass)}>
        <span className="flex items-center justify-end gap-xs">
          <input
            ref={registerCell(key)}
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={String(value)}
            readOnly={readOnly}
            aria-label={`${columnLabel}: тема ${topicRef}${topicLabel ? ` «${topicLabel}»` : ""}`}
            className={cx(
              "tnum w-12 rounded-btn border border-line bg-surface px-xs py-xs text-right text-base",
              "focus-visible:border-primary",
            )}
            onChange={(event) => onCellChange?.(topicRef, activity, parseHours(event.target.value))}
            onKeyDown={(event) => handleCellKeyDown(event, key)}
          />
          {!readOnly && onToggleLock ? (
            <button
              type="button"
              aria-pressed={locked}
              data-locked={locked ? "true" : "false"}
              aria-label={`${locked ? T.hours.unlock : T.hours.lock}: ${columnLabel}, тема ${topicRef}`}
              title={locked ? T.hours.unlock : T.hours.lock}
              onClick={() => onToggleLock(topicRef, activity)}
              className={cx(
                "rounded-btn px-[2px] text-caption leading-none",
                locked ? "text-primary" : "text-line hover:text-ink-muted",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary",
              )}
            >
              <span aria-hidden="true">{locked ? "🔒" : "🔓"}</span>
            </button>
          ) : null}
        </span>
      </TableCell>
    );
  };

  return (
    <section aria-label={T.hours.title} className="flex flex-col gap-md">
      <header className="flex flex-wrap items-center justify-between gap-md">
        <div className="flex flex-col gap-xs">
          <h2 className="text-subtitle font-semibold text-ink">{T.hours.title}</h2>
          <p className="text-caption text-ink-muted">{T.hours.subtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-md">
          <span aria-live="polite">
            {result.passed ? (
              <Badge variant="ok">{T.hours.checksPassed}</Badge>
            ) : (
              <Badge variant="error">{formatCount(result.issues.length, ERROR_FORMS)}</Badge>
            )}
          </span>
          {showApprove ? (
            <Button
              variant="primary"
              onClick={onApprove}
              disabled={approveDisabled}
              disabledReason={approveReason}
            >
              {T.hours.approve}
            </Button>
          ) : null}
        </div>
      </header>

      <div className="overflow-x-auto rounded-card border border-line bg-surface">
        <Table label={T.hours.title} className="min-w-[760px]">
          <thead>
            <tr>
              <TableHeaderCell className="sticky top-0 z-10 bg-canvas">{T.hours.columns.topic}</TableHeaderCell>
              {ACTIVITY_COLUMNS.map((column) => (
                <TableHeaderCell key={column.key} className="sticky top-0 z-10 w-24 bg-canvas text-right">
                  <span title={column.full}>{column.label}</span>
                </TableHeaderCell>
              ))}
              {showDot ? (
                <TableHeaderCell className="sticky top-0 z-10 w-28 bg-canvas text-right">
                  {T.hours.columns.distance}
                </TableHeaderCell>
              ) : null}
              <TableHeaderCell className="sticky top-0 z-10 w-24 bg-canvas text-right">
                {T.hours.columns.total}
              </TableHeaderCell>
            </tr>
          </thead>
          <tbody>
            {plan.modules.map((module) => {
              const moduleHours = result.perModule.find((m) => m.ref === module.ref);
              const moduleIssues = issuesFor(module.ref);

              return (
                <ModuleBlock
                  key={module.ref}
                  module={{
                    ref: module.ref,
                    title: module.title,
                    issues: moduleIssues,
                    workload: moduleHours?.workload,
                    total: moduleHours?.total ?? 0,
                  }}
                  topics={module.topics}
                  showDot={showDot}
                  issuesFor={issuesFor}
                  renderEditableCell={renderEditableCell}
                />
              );
            })}

            {/* Итоговая аттестация: часы задаются в карточке программы. */}
            <tr>
              <TableHeaderCell scope="row" className="text-ink-muted">
                {T.hours.finalAttestation}
              </TableHeaderCell>
              {ACTIVITY_COLUMNS.map((column) => (
                <TableCell key={column.key} numeric className="text-ink-muted">
                  —
                </TableCell>
              ))}
              {showDot ? (
                <TableCell numeric className="text-ink-muted">
                  —
                </TableCell>
              ) : null}
              <TableCell numeric>
                <SumCell value={constraints.finalAttHours} state="muted" />
              </TableCell>
            </tr>

            {/* Всего по темам (живой регион: суммы пересчитываются на лету). */}
            <tr
              className="bg-canvas font-semibold"
              data-issue={hasProgramRule(["V-HRS-04", "V-HRS-05"]) || undefined}
            >
              <TableHeaderCell scope="row" className="bg-canvas">
                {T.hours.contentTotal}
              </TableHeaderCell>
              {ACTIVITY_COLUMNS.map((column) => {
                const state: SumCellState = hasProgramRule(["V-HRS-04"])
                  ? "error"
                  : hasProgramRule(["V-HRS-05"]) && (column.key === "practice" || column.key === "lab")
                    ? "error"
                    : "normal";
                return (
                  <TableCell key={column.key} numeric className="bg-canvas">
                    <SumCell value={result.workload[column.key]} state={state} strong />
                  </TableCell>
                );
              })}
              {showDot ? (
                <TableCell numeric className="bg-canvas">
                  <SumCell value={result.workload.distance} strong />
                </TableCell>
              ) : null}
              <TableCell numeric className="bg-canvas">
                <SumCell value={result.contentTotal} strong />
              </TableCell>
            </tr>

            {/* Итог программы: темы + итоговая аттестация против запрошенного объёма. */}
            <tr data-issue={hasProgramRule(["V-HRS-01"]) || undefined}>
              <TableHeaderCell scope="row" colSpan={columnCount} className="text-right text-ink-muted">
                {T.hours.programTotal}: {T.hours.programTotalNote} — {result.contentTotal} ч +{" "}
                {constraints.finalAttHours} ч
              </TableHeaderCell>
              <TableCell numeric className={cx(hasProgramRule(["V-HRS-01"]) && "bg-danger-bg/50")}>
                <SumCell
                  value={result.grand}
                  state={hasProgramRule(["V-HRS-01"]) ? "error" : "ok"}
                  strong
                  live
                  title={programIssues.map((i) => i.message).join(" ")}
                />
                <span className="ml-xs text-caption text-ink-muted">
                  {T.hours.required} {constraints.total} ч
                </span>
              </TableCell>
            </tr>
          </tbody>
        </Table>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Блок модуля: строка-итог модуля + строки тем
// ---------------------------------------------------------------------------

interface ModuleBlockProps {
  module: {
    ref: string;
    title?: string;
    issues: LiveIssue[];
    workload?: Workload;
    total: number;
  };
  topics: LivePlan["modules"][number]["topics"];
  showDot: boolean;
  issuesFor: (ref: string) => LiveIssue[];
  renderEditableCell: (
    topicRef: string,
    topicLabel: string,
    activity: Activity,
    columnLabel: string,
    value: number,
    locked: boolean,
    extraClass?: string,
  ) => JSX.Element;
}

function ModuleBlock({ module, topics, showDot, issuesFor, renderEditableCell }: ModuleBlockProps) {
  const moduleHasIssue = module.issues.length > 0;
  const workload: Workload = module.workload ?? emptyWorkload();

  return (
    <>
      <tr data-issue={moduleHasIssue || undefined} className={cx(moduleHasIssue && "bg-danger-bg/40")}>
        <TableHeaderCell scope="rowgroup" className="font-semibold">
          <span className="flex flex-col gap-[2px]">
            <span>
              {T.hours.module} {module.ref}
              {module.title ? ` · ${module.title}` : ""}
            </span>
            {module.issues.map((item) => (
              <span key={item.rule} className="text-caption font-normal text-danger">
                {item.message}
              </span>
            ))}
          </span>
        </TableHeaderCell>
        {ACTIVITY_COLUMNS.map((column) => (
          <TableCell key={column.key} numeric>
            <SumCell value={workload[column.key]} state="muted" strong />
          </TableCell>
        ))}
        {showDot ? (
          <TableCell numeric>
            <SumCell value={workload.distance} state="muted" strong />
          </TableCell>
        ) : null}
        <TableCell numeric>
          <SumCell value={module.total} state={moduleHasIssue ? "error" : "muted"} strong />
        </TableCell>
      </tr>

      {topics.map((topic) => {
        const topicIssues = issuesFor(topic.ref);
        const topicHasIssue = topicIssues.length > 0;
        const rowTotal = workloadTotal(topic.workload);
        const distanceTooBig = topicIssues.some((i) => i.rule === "V-HRS-09");

        return (
          <tr key={topic.ref} data-issue={topicHasIssue || undefined} className={cx(topicHasIssue && "bg-danger-bg/30")}>
            <TableHeaderCell scope="row" className="font-normal">
              <span className="flex flex-col gap-[2px]">
                <span>
                  <span className="tnum text-caption text-ink-muted">{topic.ref}</span>{" "}
                  {topic.title ?? "—"}
                </span>
                {topicHasIssue ? (
                  <span className="text-caption text-danger">{topicIssues.map((i) => i.message).join(" ")}</span>
                ) : null}
              </span>
            </TableHeaderCell>
            {ACTIVITY_COLUMNS.map((column) => (
              <Fragment key={column.key}>
                {renderEditableCell(
                  topic.ref,
                  topic.title ?? "",
                  column.key,
                  column.full,
                  topic.workload[column.key],
                  isCellLocked(topic.locked ?? [], column.key),
                )}
              </Fragment>
            ))}
            {showDot ? (
              <TableCell numeric className={cx(distanceTooBig && "bg-danger-bg/60")}>
                <SumCell
                  value={topic.workload.distance}
                  state={distanceTooBig ? "error" : "muted"}
                  title={topicIssues.find((i) => i.rule === "V-HRS-09")?.message}
                />
              </TableCell>
            ) : null}
            <TableCell numeric>
              <SumCell
                value={rowTotal}
                state={topicHasIssue ? "error" : "normal"}
                title={topicIssues.map((i) => i.message).join(" ")}
              />
            </TableCell>
          </tr>
        );
      })}
    </>
  );
}
