/**
 * «Уточнения» (Д3 §4.2, US-3): не более 5 карточек вопросов, варианты-кнопки,
 * свободный ответ и «На ваше усмотрение». Агент не додумывает за методиста:
 * без ответов каркас не собирается (409 CLARIFICATION_REQUIRED).
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";

import type { AnswerValue, ClarifyQuestion } from "../entities/kit";
import { useGenerateFramework, useQuestions, useSubmitAnswers } from "../shared/api/queries";
import { T } from "../shared/i18n/ru";
import { Badge } from "../shared/ui/Badge";
import { Button } from "../shared/ui/Button";
import { cx } from "../shared/ui/cx";
import { ProgramStatusBar } from "../features/progress/ProgramStatusBar";
import { Stepper } from "../shared/ui/Stepper";
import { useToast } from "../shared/ui/Toast";
import { ErrorState, PageSkeleton } from "../app/states";

interface AnswerDraft {
  value: string | null;
  free: string;
  useDefault: boolean;
}

const EMPTY_ANSWER: AnswerDraft = { value: null, free: "", useDefault: false };

function isAnswered(draft: AnswerDraft | undefined): boolean {
  if (!draft) return false;
  return draft.useDefault || draft.free.trim().length > 0 || (draft.value ?? "").trim().length > 0;
}

export function ClarifyPage() {
  const { programId } = useParams({ strict: false });
  const id = programId ?? "";
  const navigate = useNavigate();
  const toast = useToast();

  const questionsQuery = useQuestions(id || null);
  const submitAnswers = useSubmitAnswers(id);
  const generateFramework = useGenerateFramework(id);

  const [answers, setAnswers] = useState<Record<string, AnswerDraft>>({});
  const [ready, setReady] = useState(false);

  if (questionsQuery.isPending) return <PageSkeleton />;
  if (questionsQuery.isError) {
    return <ErrorState message={T.app.error} onRetry={() => void questionsQuery.refetch()} />;
  }

  const { questions, detected, status } = questionsQuery.data;
  const allAnswered = questions.every((question) => isAnswered(answers[question.id]));
  const answeredCount = questions.filter((question) => isAnswered(answers[question.id])).length;

  const setDraft = (questionId: string, patch: Partial<AnswerDraft>) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: { ...EMPTY_ANSWER, ...prev[questionId], ...patch },
    }));
  };

  const send = async () => {
    const payload: AnswerValue[] = questions.map((question) => {
      const draft = answers[question.id] ?? EMPTY_ANSWER;
      if (draft.useDefault) return { id: question.id, value: null, use_default: true };
      const value = draft.free.trim().length > 0 ? draft.free.trim() : draft.value;
      return { id: question.id, value };
    });
    try {
      const response = await submitAnswers.mutateAsync(payload);
      setReady(response.ready_for_framework);
      toast.show("success", "Ответы отправлены");
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  const buildFramework = async () => {
    try {
      await generateFramework.mutateAsync();
      toast.show("success", T.clarify.building);
      void navigate({ to: "/programs/$programId/framework", params: { programId: id } });
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  const frameworkAlreadyBuilt = status.startsWith("framework") || status.startsWith("kit");

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-col gap-sm">
        <Stepper current={1} />
        {id ? <ProgramStatusBar programId={id} currentStep={1} /> : null}
        <h1 className="text-title font-bold text-ink">{T.clarify.title}</h1>
        <p className="text-base text-ink-muted">{T.clarify.subtitle}</p>
      </header>

      {/* Что агент уже понял из брифа */}
      <section aria-label={T.intake.understood} className="flex flex-wrap items-center gap-sm rounded-card border border-line bg-surface px-lg py-md">
        <span className="text-caption font-medium text-ink-muted">{T.intake.understood}:</span>
        {Object.entries(detected).map(([slot, value]) => (
          <span key={slot} className="flex items-center gap-xs text-caption">
            <span className="text-ink-muted">{T.intake.detected[slot as keyof typeof T.intake.detected] ?? slot}</span>
            {value ? <Badge variant="ok">{value}</Badge> : <Badge variant="warning">уточним</Badge>}
          </span>
        ))}
      </section>

      {/* Карточка «Агент заметил»: разрыв между пожеланием и реалистичным объёмом */}
      {detected.duration_hint && !detected.total_hours ? (
        <section aria-label={T.clarify.notice} className="rounded-card border border-warning/30 bg-warning-bg px-lg py-md text-base text-warning">
          <strong className="mr-xs">{T.clarify.notice}:</strong>
          в запросе указано «{detected.duration_hint}», а объём в часах не назван. При двух занятиях в
          неделю по 2 часа это около 16 часов — сколько часов нужно на самом деле?
        </section>
      ) : null}

      {frameworkAlreadyBuilt ? (
        <section className="flex flex-wrap items-center gap-md rounded-card border border-success/30 bg-success-bg p-lg">
          <Badge variant="ok">{T.clarify.allAnswered}</Badge>
          <p className="text-base text-success">{T.clarify.ready}</p>
          <Link
            to="/programs/$programId/framework"
            params={{ programId: id }}
            className="inline-flex min-h-[36px] items-center justify-center rounded-btn bg-primary px-lg py-sm font-medium text-white hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            {status === "framework_generating"
              ? "Сборка идёт — открыть прогресс"
              : T.clarify.buildFramework}
          </Link>
        </section>
      ) : questions.length === 0 ? (
        <section className="flex flex-wrap items-center gap-md rounded-card border border-success/30 bg-success-bg p-lg">
          <Badge variant="ok">{T.clarify.ready}</Badge>
          <Button variant="primary" onClick={() => void buildFramework()} busy={generateFramework.isPending}>
            {generateFramework.isPending ? T.clarify.building : T.clarify.buildFramework}
          </Button>
        </section>
      ) : (
        <>
          <p aria-live="polite" className="text-caption text-ink-muted">
            {T.clarify.progress}: {answeredCount} {T.clarify.of} {questions.length}
          </p>

          <ul className="flex flex-col gap-md">
            {questions.map((question) => (
              <QuestionCard
                key={question.id}
                question={question}
                draft={answers[question.id] ?? EMPTY_ANSWER}
                onChange={(patch) => setDraft(question.id, patch)}
              />
            ))}
          </ul>

          <div className="flex flex-wrap items-center gap-md">
            <Button
              variant="primary"
              onClick={() => void send()}
              disabled={!allAnswered || submitAnswers.isPending || ready}
              disabledReason={
                !allAnswered
                  ? "Ответьте на все вопросы или выберите «На ваше усмотрение»"
                  : undefined
              }
              busy={submitAnswers.isPending}
            >
              {T.clarify.submit}
            </Button>

            {ready ? (
              <Button variant="primary" onClick={() => void buildFramework()} busy={generateFramework.isPending}>
                {generateFramework.isPending ? T.clarify.building : T.clarify.buildFramework}
              </Button>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}

function QuestionCard({
  question,
  draft,
  onChange,
}: {
  question: ClarifyQuestion;
  draft: AnswerDraft;
  onChange: (patch: Partial<AnswerDraft>) => void;
}) {
  const answered = isAnswered(draft);

  return (
    <li
      data-answered={answered || undefined}
      className={cx(
        "flex flex-col gap-sm rounded-card border bg-surface p-lg",
        answered ? "border-success/40" : "border-line",
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-sm">
        <h2 className="text-subtitle font-semibold text-ink">
          <span className="tnum mr-sm text-caption text-ink-muted">{question.ord}.</span>
          {question.text}
        </h2>
        {answered ? <Badge variant="ok">Ответ принят</Badge> : null}
      </div>

      <p className="text-caption text-ink-muted">
        {T.clarify.why}: {question.why}
      </p>

      {question.options.length > 0 ? (
        <div className="flex flex-wrap gap-sm" role="group" aria-label={question.text}>
          {question.options.map((option) => (
            <Button
              key={option}
              variant={draft.value === option && !draft.useDefault ? "primary" : "secondary"}
              size="sm"
              aria-pressed={draft.value === option && !draft.useDefault}
              onClick={() => onChange({ value: option, free: "", useDefault: false })}
            >
              {option}
            </Button>
          ))}
        </div>
      ) : null}

      {question.allow_free_text ? (
        <label className="flex flex-col gap-xs text-caption text-ink-muted">
          {T.clarify.freeText}
          <input
            type="text"
            value={draft.free}
            onChange={(event) => onChange({ free: event.target.value, value: null, useDefault: false })}
            className="min-h-[36px] rounded-btn border border-line bg-surface px-md py-sm text-base text-ink focus-visible:border-primary"
          />
        </label>
      ) : null}

      {question.allow_default ? (
        <div className="flex items-center gap-sm">
          <Button
            variant={draft.useDefault ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={draft.useDefault}
            onClick={() => onChange({ useDefault: true, value: null, free: "" })}
          >
            {T.clarify.useDefault}
          </Button>
          {draft.useDefault ? <span className="text-caption text-ink-muted">{T.clarify.defaultHint}</span> : null}
        </div>
      ) : null}
    </li>
  );
}
