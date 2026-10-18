/**
 * «Каркас» (Д3 §4.3, §4.4): вкладки «Учебный план», «Связи», «Замечания».
 *
 * Учебный план — HoursGrid с живым пересчётом; правки копятся в черновике
 * и отправляются одним PATCH (If-Match: lock_version). Пока каркас не
 * утверждён (Human Gate), генерация комплекта недоступна.
 */

import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "@tanstack/react-router";

import {
  isCellLocked,
  toggleCellLock,
  type Activity,
  type FrameworkOp,
} from "../entities/kit";
import { formatStatus } from "../entities/formatters";
import { ApiError } from "../shared/api/client";
import { problemIssueMessages } from "../shared/api/problem";
import {
  useApproveFramework,
  useFramework,
  useRebalanceFramework,
  useSaveFramework,
} from "../shared/api/queries";
import { T } from "../shared/i18n/ru";
import { Badge } from "../shared/ui/Badge";
import { Button } from "../shared/ui/Button";
import { IconCheck } from "../shared/ui/icons";
import { ProgramStatusBar } from "../features/progress/ProgramStatusBar";
import { Stepper } from "../shared/ui/Stepper";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../shared/ui/Tabs";
import { useToast } from "../shared/ui/Toast";
import { ErrorState, PageSkeleton } from "../app/states";
import { CoverageMatrix } from "../features/coverage/CoverageMatrix";
import { ConstraintBar } from "../features/hours/ConstraintBar";
import { HoursGrid } from "../features/hours/HoursGrid";
import {
  computeLiveHours,
  livePlanFromModules,
  type LiveConstraints,
  type LivePlan,
} from "../features/hours/useLiveHours";

/** Ключ правки ячейки: "T2.1:practice". */
type CellKey = `${string}:${Activity}`;

export function FrameworkPage() {
  const { programId } = useParams({ strict: false });
  const id = programId ?? "";
  const toast = useToast();

  const frameworkQuery = useFramework(id || null);
  const saveFramework = useSaveFramework(id);
  const rebalance = useRebalanceFramework(id);
  const approve = useApproveFramework(id);

  const [draft, setDraft] = useState<LivePlan | null>(null);
  const [changes, setChanges] = useState<Map<CellKey, number>>(new Map());
  const [lockChanges, setLockChanges] = useState<Map<CellKey, boolean>>(new Map());
  /** Желаемое состояние связей «тема ↔ результат», которых коснулся методист. */
  const [linkDraft, setLinkDraft] = useState<Map<string, boolean>>(new Map());
  const [tab, setTab] = useState("plan");

  const version = frameworkQuery.data?.version;

  // Новая версия каркаса — черновик перечитывается с сервера.
  useEffect(() => {
    if (frameworkQuery.data) {
      setDraft(livePlanFromModules(frameworkQuery.data.modules));
      setChanges(new Map());
      setLockChanges(new Map());
      setLinkDraft(new Map());
    }
    // Зависимость только от номера версии: оптимистичные правки кэша
    // не должны стирать черновик, пока сервер не подтвердил новую версию.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version]);

  const constraints: LiveConstraints | null = useMemo(() => {
    const data = frameworkQuery.data;
    if (!data) return null;
    return {
      total: data.program.total_hours,
      finalAttHours: data.program.final_attestation.hours,
      selfStudyOnly: data.profile.constraints.self_study_only,
      internship: data.program.form === "internship",
      minPracticeSharePct: data.profile.constraints.min_practice_share_pct,
      unitHours: data.profile.constraints.unit_hours,
      distanceMode: data.program.form === "distance" || data.profile.constraints.distance_share_pct > 0,
    };
  }, [frameworkQuery.data]);

  const liveResult = useMemo(
    () => (draft && constraints ? computeLiveHours(draft, constraints) : null),
    [draft, constraints],
  );

  if (frameworkQuery.isPending) return <PageSkeleton />;
  if (frameworkQuery.isError) {
    return <ErrorState message={T.app.error} onRetry={() => void frameworkQuery.refetch()} />;
  }

  const data = frameworkQuery.data;
  const approved = data.status === "framework_approved" || data.status.startsWith("kit");

  const currentHours = (topicRef: string, activity: Activity): number => {
    const topic = draft?.modules.flatMap((m) => m.topics).find((t) => t.ref === topicRef);
    return topic ? topic.workload[activity] : 0;
  };

  const updateTopicWorkload = (topicRef: string, activity: Activity, hours: number) => {
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        modules: prev.modules.map((m) => ({
          ...m,
          topics: m.topics.map((t) =>
            t.ref === topicRef ? { ...t, workload: { ...t.workload, [activity]: hours } } : t,
          ),
        })),
      };
    });
    setChanges((prev) => new Map(prev).set(`${topicRef}:${activity}`, hours));
  };

  const toggleLock = (topicRef: string, activity: Activity) => {
    const topic = draft?.modules.flatMap((m) => m.topics).find((t) => t.ref === topicRef);
    const wasLocked = topic ? isCellLocked(topic.locked ?? [], activity) : false;
    const nextLocked = !wasLocked;
    setDraft((prev) => {
      if (!prev) return prev;
      return {
        modules: prev.modules.map((m) => ({
          ...m,
          topics: m.topics.map((t) =>
            t.ref === topicRef ? { ...t, locked: toggleCellLock(t.locked ?? [], activity) } : t,
          ),
        })),
      };
    });
    setLockChanges((prev) => new Map(prev).set(`${topicRef}:${activity}`, nextLocked));
  };

  const buildOps = (): FrameworkOp[] => {
    const ops: FrameworkOp[] = [];
    for (const [key, hours] of changes) {
      const [ref, activity] = key.split(":") as [string, Activity];
      ops.push({ op: "set_hours", ref, activity, hours });
    }
    for (const [key, locked] of lockChanges) {
      const [ref, activity] = key.split(":") as [string, Activity];
      ops.push({ op: "set_hours", ref, activity, hours: currentHours(ref, activity), lock: locked });
    }
    // Связывание РО и темы поддерживается операцией link_outcome;
    // отвязка серверным контрактом не предусмотрена — правьте на вкладке «Связи» до сохранения.
    for (const [key, linked] of linkDraft) {
      if (!linked) continue;
      const [topicRef, outcomeRef] = key.split("|");
      const serverLinked = data.competencies
        .flatMap((c) => c.outcomes)
        .some(
          (o) =>
            o.ref === outcomeRef &&
            data.modules
              .flatMap((m) => m.topics)
              .some((t) => t.ref === topicRef && t.outcome_refs.includes(outcomeRef)),
        );
      if (!serverLinked) ops.push({ op: "link_outcome", topic_ref: topicRef, outcome_ref: outcomeRef });
    }
    return ops;
  };

  const pendingOps = buildOps();
  const hasUnsaved = pendingOps.length > 0;

  const save = async () => {
    try {
      await saveFramework.mutateAsync({ ops: pendingOps, etag: data.etag });
      toast.show("success", T.hours.saved);
    } catch (error) {
      if (error instanceof ApiError && error.status === 412) {
        // Конфликт версий: каркас изменил другой пользователь — перечитываем.
        toast.show("error", "Каркас изменил другой пользователь — данные обновлены, повторите правку.");
        void frameworkQuery.refetch();
        return;
      }
      toast.show("error", error instanceof Error ? error.message : T.app.error);
    }
  };

  const approveBlockedReason = hasUnsaved
    ? "Сохраните часы перед утверждением."
    : liveResult && !liveResult.passed
      ? liveResult.issues[0].message
      : !data.checks.passed
        ? "Есть замечания проверки — откройте вкладку «Замечания»."
        : undefined;

  const approveFramework = async () => {
    try {
      await approve.mutateAsync({ comment: "Утверждаю каркас", etag: data.etag });
      toast.show("success", T.framework.approved);
    } catch (error) {
      toast.show("error", error instanceof Error ? error.message : T.framework.approveError);
    }
  };

  // Эффективные связи с учётом несохранённых правок.
  const effectiveTopics = (draft?.modules ?? []).flatMap((m) =>
    m.topics.map((t) => {
      const baseRefs =
        data.modules.flatMap((mod) => mod.topics).find((modTopic) => modTopic.ref === t.ref)?.outcome_refs ?? [];
      const refs = new Set(baseRefs);
      for (const [key, linked] of linkDraft) {
        const [topicRef, outcomeRef] = key.split("|");
        if (topicRef !== t.ref) continue;
        if (linked) refs.add(outcomeRef);
        else refs.delete(outcomeRef);
      }
      return { ref: t.ref, title: t.title ?? t.ref, outcome_refs: [...refs] };
    }),
  );

  const outcomes = data.competencies.flatMap((c) =>
    c.outcomes.map((o) => ({ ref: o.ref, type: o.type, text: o.text })),
  );

  return (
    <div className="flex flex-col gap-lg">
      <header className="flex flex-col gap-sm">
        <Stepper current={approved ? 3 : 2} maxReached={approved ? 4 : 2} />
        {id ? <ProgramStatusBar programId={id} currentStep={approved ? 3 : 2} /> : null}
        <div className="flex flex-wrap items-center justify-between gap-md">
          <div className="flex flex-col gap-xs">
            <h1 className="text-title font-bold text-ink">{data.program.title}</h1>
            <p className="text-base text-ink-muted">
              {data.program.total_hours} ч · {formatStatus(data.status)}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-md">
            <Link to="/" className="text-base text-primary underline underline-offset-2">
              ← К списку
            </Link>
            {approved ? (
              <Link
                to="/programs/$programId/kit"
                params={{ programId: id }}
                className="inline-flex min-h-[44px] items-center justify-center rounded-btn bg-primary px-xl py-sm text-base font-semibold text-white hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
              >
                Открыть материалы →
              </Link>
            ) : null}
          </div>
        </div>
      </header>

      {approved ? (
        <p
          className="inline-flex items-center gap-sm rounded-card border border-success/30 bg-success-bg px-lg py-md text-base text-success"
          role="status"
        >
          <IconCheck className="h-3.5 w-3.5 shrink-0" />
          Часы утверждены. Дальше — материалы комплекта.
        </p>
      ) : (
        <p className="rounded-card border border-line bg-surface px-lg py-md text-base text-ink-muted">
          Смотрите таблицу часов. Если ошибок нет — нажмите «Утвердить каркас» внизу справа.
        </p>
      )}

      {approve.error instanceof ApiError && approve.error.code === "HOURS_MISMATCH" ? (
        <div role="alert" className="rounded-card border border-danger/30 bg-danger-bg px-lg py-md text-base text-danger">
          <strong>{T.framework.approveError}:</strong>
          <ul className="mt-xs list-disc pl-lg">
            {problemIssueMessages(approve.error.problem).map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList label={T.framework.title}>
          <TabsTrigger value="plan">{T.framework.tabs.plan}</TabsTrigger>
          <TabsTrigger value="links">{T.framework.tabs.links}</TabsTrigger>
          <TabsTrigger value="issues">{T.framework.tabs.issues}</TabsTrigger>
        </TabsList>

        <TabsContent value="plan">
          {draft && constraints && liveResult ? (
            <div className="grid grid-cols-1 gap-lg xl:grid-cols-[2.2fr_1fr]">
              <div className="flex flex-col gap-md">
                <div className="flex flex-wrap items-center justify-between gap-md rounded-card border border-line bg-surface px-lg py-md">
                  <span aria-live="polite" className="text-caption text-ink-muted">
                    {hasUnsaved
                      ? `Несохранённых правок: ${pendingOps.length}`
                      : "Все правки сохранены"}
                  </span>
                  <Button
                    variant="secondary"
                    onClick={() => void save()}
                    disabled={!hasUnsaved || saveFramework.isPending || approved}
                    disabledReason={approved ? "Каркас утверждён — для изменения часов верните его на доработку" : undefined}
                    busy={saveFramework.isPending}
                  >
                    {T.hours.save}
                  </Button>
                </div>

                <HoursGrid
                  plan={draft}
                  constraints={constraints}
                  readOnly={approved}
                  busy={approve.isPending || saveFramework.isPending}
                  approveBlockedReason={approved ? undefined : approveBlockedReason}
                  showApprove={!approved}
                  onCellChange={updateTopicWorkload}
                  onToggleLock={toggleLock}
                  onApprove={() => void approveFramework()}
                />
              </div>

              <ConstraintBar
                constraints={constraints}
                result={liveResult}
                busy={rebalance.isPending}
                onRebalance={
                  approved || hasUnsaved ? undefined : () => rebalance.mutate(undefined)
                }
              />
            </div>
          ) : (
            <PageSkeleton />
          )}
        </TabsContent>

        <TabsContent value="links">
          <CoverageMatrix
            outcomes={outcomes}
            topics={effectiveTopics}
            assessments={[]}
            showCounters={false}
            readOnly={approved}
            onToggleLink={(outcomeRef, topicRef, nextLinked) => {
              // Операции отвязки в контракте PATCH /framework нет (Д4 §6.4):
              // не делаем вид, что отвязка сохранится.
              if (!nextLinked) {
                toast.show(
                  "error",
                  "Отвязать связь пока нельзя: отвязка выполняется при правке содержания комплекта.",
                );
                return;
              }
              setLinkDraft((prev) => new Map(prev).set(`${topicRef}|${outcomeRef}`, true));
            }}
          />
        </TabsContent>

        <TabsContent value="issues">
          <section aria-label={T.framework.tabs.issues} className="flex flex-col gap-sm rounded-card border border-line bg-surface p-lg">
            <h2 className="text-subtitle font-semibold text-ink">
              {T.report.issues}: {data.checks.issues.length}
            </h2>
            {data.checks.issues.length === 0 ? (
              <Badge variant="ok">{T.report.issuesNone}</Badge>
            ) : (
              <ul className="flex flex-col gap-sm">
                {data.checks.issues.map((issue) => (
                  <li
                    key={`${issue.rule_code}-${issue.entity_ref ?? issue.message}`}
                    className="flex flex-col gap-xs rounded-btn border border-warning/30 bg-warning-bg/60 px-md py-sm"
                  >
                    <span className="flex flex-wrap items-center gap-sm">
                      <span className="tnum text-caption text-ink-muted">{issue.rule_code}</span>
                      {issue.entity_ref ? (
                        <span className="tnum text-caption text-ink-muted">· {issue.entity_ref}</span>
                      ) : null}
                    </span>
                    <span className="text-base text-ink">{issue.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
