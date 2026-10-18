/**
 * Матрица связей «результат обучения ↔ тема» (Д3 §4.4, CoverageMatrix).
 */

import { useMemo } from "react";

import type { Assessment, OutcomeType } from "../../entities/kit";
import { T } from "../../shared/i18n/ru";
import { cx } from "../../shared/ui/cx";

export interface CoverageOutcome {
  ref: string;
  type: OutcomeType;
  text: string;
}

export interface CoverageTopic {
  ref: string;
  title: string;
  outcome_refs: string[];
}

export interface CoverageMatrixProps {
  outcomes: CoverageOutcome[];
  topics: CoverageTopic[];
  assessments: Assessment[];
  showCounters: boolean;
  readOnly: boolean;
  onToggleLink: (outcomeRef: string, topicRef: string, nextLinked: boolean) => void;
}

function isLinked(topic: CoverageTopic, outcomeRef: string): boolean {
  return topic.outcome_refs.includes(outcomeRef);
}

export function CoverageMatrix({
  outcomes,
  topics,
  assessments,
  showCounters,
  readOnly,
  onToggleLink,
}: CoverageMatrixProps) {
  const assessCountByOutcome = useMemo(() => {
    const map = new Map<string, number>();
    for (const a of assessments) {
      for (const ref of a.outcome_refs ?? []) {
        map.set(ref, (map.get(ref) ?? 0) + 1);
      }
    }
    return map;
  }, [assessments]);

  if (outcomes.length === 0) {
    return (
      <p className="rounded-card border border-line bg-surface px-lg py-md text-base text-ink-muted">
        {T.coverage.empty}
      </p>
    );
  }

  return (
    <section aria-label={T.coverage.title} className="flex flex-col gap-md">
      <div>
        <h2 className="text-subtitle font-semibold text-ink">{T.coverage.title}</h2>
        <p className="mt-xs text-base text-ink-muted">{T.coverage.subtitle}</p>
      </div>

      <div className="overflow-auto rounded-card border border-line bg-surface">
        <table className="w-full min-w-[640px] border-collapse text-left text-base">
          <thead className="sticky top-0 z-10 bg-surface shadow-[0_1px_0_var(--color-line)]">
            <tr>
              <th className="sticky left-0 z-20 min-w-[12rem] bg-surface px-md py-sm text-caption font-semibold text-ink-muted">
                {T.coverage.columns.outcome}
              </th>
              {showCounters ? (
                <th className="min-w-[6rem] px-md py-sm text-caption font-semibold text-ink-muted">
                  {T.coverage.columns.assessments}
                </th>
              ) : null}
              {topics.map((topic) => (
                <th
                  key={topic.ref}
                  className="min-w-[5rem] max-w-[8rem] px-sm py-sm text-caption font-semibold text-ink-muted"
                  title={topic.title}
                >
                  <span className="line-clamp-2">{topic.ref}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {outcomes.map((outcome) => {
              const assessCount = assessCountByOutcome.get(outcome.ref) ?? 0;
              const assessOk = assessCount >= 2;
              return (
                <tr key={outcome.ref} className="border-t border-line">
                  <th
                    scope="row"
                    className="sticky left-0 z-10 bg-surface px-md py-sm align-top font-normal text-ink"
                  >
                    <span className="tnum text-caption text-ink-muted">{outcome.ref}</span>
                    <p className="mt-xs text-base">{outcome.text}</p>
                  </th>
                  {showCounters ? (
                    <td className="px-md py-sm align-top">
                      <span
                        className={cx(
                          "tnum inline-flex rounded-btn px-sm py-xs text-caption font-medium",
                          assessOk ? "bg-success-bg text-success" : "bg-warning-bg text-warning",
                        )}
                        title={assessOk ? T.coverage.countOk : T.coverage.countGap}
                      >
                        {assessCount}
                      </span>
                    </td>
                  ) : null}
                  {topics.map((topic) => {
                    const linked = isLinked(topic, outcome.ref);
                    return (
                      <td key={`${outcome.ref}-${topic.ref}`} className="px-sm py-sm text-center">
                        <button
                          type="button"
                          disabled={readOnly}
                          aria-pressed={linked}
                          aria-label={`${outcome.ref} — ${topic.ref}: ${linked ? T.coverage.linked : T.coverage.notLinked}`}
                          className={cx(
                            "inline-flex h-9 w-9 items-center justify-center rounded-btn border text-caption font-semibold transition-colors",
                            linked
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-line bg-page text-ink-muted hover:border-primary/40",
                            readOnly && "cursor-not-allowed opacity-60",
                          )}
                          onClick={() => onToggleLink(outcome.ref, topic.ref, !linked)}
                        >
                          {linked ? "✓" : "·"}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
