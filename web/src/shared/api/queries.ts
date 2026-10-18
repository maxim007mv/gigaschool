/**
 * Хуки данных TanStack Query (Д3 §8): ключи кэша, запросы и мутации к /api/v1.
 *
 * В dev-режиме (и при VITE_USE_MOCKS !== "0") работают моки из mocks.ts —
 * чтобы демонстрировать интерфейс без поднятого backend. Типы в обоих
 * режимах одинаковые (entities/kit.ts), поэтому страницы не меняются.
 */

import { useEffect } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiFetch, apiUpload, ApiError, newIdempotencyKey } from "./client";
import * as mocks from "./mocks";
import { openProgramEvents, type ProgramEvent } from "./sse";
import type {
  AdaptRequest,
  AdaptResponse,
  AnswersResponse,
  AnswerValue,
  CreatedProgramResponse,
  EditResponse,
  ExportFormat,
  ExportStatusResponse,
  FrameworkApiResponse,
  FrameworkOp,
  FrameworkPatchResponse,
  FrameworkResponse,
  JobInfo,
  KbAppliesTo,
  KbDocument,
  KbDocRole,
  KitV1,
  ProgramDetails,
  ProgramListResponse,
  QuestionsResponse,
  RebalanceResponse,
  Report,
  UploadFileResponse,
  Usage,
  VersionDiffResponse,
  VersionSummary,
} from "../../entities/kit";

/** Ответ сервера вместе с ETag текущей версии (для If-Match). */
export type FrameworkData = FrameworkResponse & { etag: string | null };
export type KitData = KitV1 & { etag: string | null };

/** Проекция конверта GET /framework ({version, status, kit}) в view-model UI. */
export function frameworkFromApi(payload: FrameworkApiResponse, report: Report | null): FrameworkResponse {
  return {
    version: payload.version,
    status: payload.status,
    program: payload.kit.program,
    profile: payload.kit.profile,
    goal: payload.kit.framework.goal,
    tasks: payload.kit.framework.tasks,
    competencies: payload.kit.framework.competencies,
    modules: payload.kit.framework.modules,
    calendar: payload.kit.framework.calendar,
    // Проверки каркаса — из последнего отчёта самопроверки (если он есть).
    checks: {
      passed: report ? report.passed : true,
      issues: report
        ? report.issues.map((issue) => ({
            rule_code: issue.rule_code,
            entity_ref: issue.entity_ref,
            message: issue.message,
          }))
        : [],
    },
  };
}

/** В dev включаем моки, пока backend не поднят; в сборке — всегда реальный API. */
export const USE_MOCKS: boolean =
  (import.meta.env.DEV || import.meta.env.MODE === "test") &&
  import.meta.env.VITE_USE_MOCKS !== "0";

// Демонстрационное состояние моков: каркас программы p-100 считается
// утверждённым после вызова framework:approve.
let mockP100Approved = false;

// ---------------------------------------------------------------------------
// Ключи кэша (Д3 §8: ['program', id], ['framework', id, version], ['kit', id, version])
// ---------------------------------------------------------------------------

export interface ProgramFilters {
  status?: string;
  kind?: string;
  q?: string;
}

export const queryKeys = {
  programs: (filters: ProgramFilters = {}) => ["programs", filters] as const,
  program: (id: string) => ["program", id] as const,
  questions: (id: string) => ["questions", id] as const,
  framework: (id: string) => ["framework", id] as const,
  kit: (id: string) => ["kit", id] as const,
  report: (id: string) => ["report", id] as const,
  versions: (id: string) => ["versions", id] as const,
  versionDiff: (id: string, from: number, to: number) => ["versionDiff", id, from, to] as const,
  kb: () => ["kb"] as const,
  exportStatus: (exportId: string) => ["export", exportId] as const,
};

function withEtag<T extends object>(data: T, etag: string | null): T & { etag: string | null } {
  return { ...data, etag };
}

// ---------------------------------------------------------------------------
// Запросы
// ---------------------------------------------------------------------------

export function usePrograms(filters: ProgramFilters = {}): UseQueryResult<ProgramListResponse> {
  return useQuery({
    queryKey: queryKeys.programs(filters),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        return mocks.mockPrograms(filters);
      }
      // «all» — значение UI-фильтра «все», в API не передаём (иначе CAST enum → 500).
      const response = await apiFetch<ProgramListResponse>("/programs", {
        query: {
          status: filters.status && filters.status !== "all" ? filters.status : undefined,
          kind: filters.kind && filters.kind !== "all" ? filters.kind : undefined,
          q: filters.q || undefined,
        },
      });
      return response.data;
    },
    staleTime: 15_000,
  });
}

export function useProgram(programId: string | null): UseQueryResult<ProgramDetails> {
  return useQuery({
    queryKey: queryKeys.program(programId ?? ""),
    enabled: Boolean(programId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        const program = mocks.mockPrograms({}).items[0];
        return {
          id: program.id,
          title: program.title,
          kind: program.kind,
          total_hours: program.total_hours,
          status: program.status,
          profile: {},
          constraints: {},
          lock_version: 3,
        };
      }
      return (await apiFetch<ProgramDetails>(`/programs/${programId}`)).data;
    },
  });
}

export function useQuestions(programId: string | null): UseQueryResult<QuestionsResponse> {  return useQuery({
    queryKey: queryKeys.questions(programId ?? ""),
    enabled: Boolean(programId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        return mocks.mockQuestions();
      }
      return (await apiFetch<QuestionsResponse>(`/programs/${programId}/questions`)).data;
    },
  });
}

export function useFramework(programId: string | null): UseQueryResult<FrameworkData> {
  return useQuery({
    queryKey: queryKeys.framework(programId ?? ""),
    enabled: Boolean(programId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        const framework = mocks.mockFramework();
        // Демонстрация Human Gate: после «framework:approve» каркас считается
        // утверждённым, и комплект становится доступен (см. useKit).
        if (mockP100Approved) {
          return withEtag(
            { ...framework, status: "framework_approved" as const, version: 6 },
            '"v6-mock"',
          );
        }
        return withEtag(framework, '"v5-mock"');
      }
      const response = await apiFetch<FrameworkApiResponse>(`/programs/${programId}/framework`);
      // Отчёт самопроверки — best-effort: до первой генерации его может не быть (404).
      let report: Report | null = null;
      try {
        report = (await apiFetch<Report>(`/programs/${programId}/report`)).data;
      } catch {
        report = null;
      }
      return withEtag(frameworkFromApi(response.data, report), response.etag);
    },
  });
}

export function useKit(programId: string | null): UseQueryResult<KitData> {
  return useQuery({
    queryKey: queryKeys.kit(programId ?? ""),
    enabled: Boolean(programId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        // Human Gate: до утверждения каркаса комплекта нет (409 GATE_NOT_PASSED).
        if (!mockP100Approved && programId !== "p-101-ai-teacher") {
          throw new ApiError(409, {
            code: "GATE_NOT_PASSED",
            detail: "Сначала утвердите каркас: цель, компетенции и часы",
          });
        }
        return withEtag(mocks.mockKit(), '"v7-mock"');
      }
      const response = await apiFetch<KitV1>(`/programs/${programId}/kit`);
      return withEtag(response.data, response.etag);
    },
  });
}

export function useReport(programId: string | null): UseQueryResult<Report> {
  return useQuery({
    queryKey: queryKeys.report(programId ?? ""),
    enabled: Boolean(programId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        return mocks.mockReport();
      }
      return (await apiFetch<Report>(`/programs/${programId}/report`)).data;
    },
  });
}

export function useVersions(programId: string | null): UseQueryResult<VersionSummary[]> {
  return useQuery({
    queryKey: queryKeys.versions(programId ?? ""),
    enabled: Boolean(programId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        return mocks.mockVersions();
      }
      return (await apiFetch<{ items: VersionSummary[] }>(`/programs/${programId}/versions`)).data.items;
    },
  });
}

export function useVersionDiff(
  programId: string | null,
  from: number | null,
  to: number | null,
): UseQueryResult<VersionDiffResponse> {
  return useQuery({
    queryKey: queryKeys.versionDiff(programId ?? "", from ?? 0, to ?? 0),
    enabled: Boolean(programId && from && to && from !== to),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        return mocks.mockVersionDiff();
      }
      return (
        await apiFetch<VersionDiffResponse>(
          `/programs/${programId}/versions/${from}/diff`,
          { query: { to: to ?? undefined } },
        )
      ).data;
    },
  });
}

export function useKbDocuments(): UseQueryResult<KbDocument[]> {
  return useQuery({
    queryKey: queryKeys.kb(),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        return mocks.mockKbDocuments();
      }
      return (await apiFetch<{ items: KbDocument[] }>("/kb/documents")).data.items;
    },
  });
}

export function useExportStatus(exportId: string | null): UseQueryResult<ExportStatusResponse> {
  return useQuery({
    queryKey: queryKeys.exportStatus(exportId ?? ""),
    enabled: Boolean(exportId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay(400);
        return mocks.mockExportStatus();
      }
      return (await apiFetch<ExportStatusResponse>(`/exports/${exportId}`)).data;
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "ready" || status === "failed" ? false : 1500;
    },
  });
}

export function useUsage(programId: string | null): UseQueryResult<Usage> {
  return useQuery({
    queryKey: ["usage", programId ?? ""],
    enabled: Boolean(programId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay();
        return mocks.mockUsage();
      }
      return (await apiFetch<Usage>(`/programs/${programId}/usage`)).data;
    },
  });
}

// ---------------------------------------------------------------------------
// Мутации: программы и уточнения
// ---------------------------------------------------------------------------

export function useUploadFile() {
  return useMutation({
    mutationFn: async (file: File): Promise<UploadFileResponse> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(250);
        return { file_id: `file-${file.name}-${file.size}`, filename: file.name };
      }
      return (await apiUpload<UploadFileResponse>("/files", file)).data;
    },
  });
}

export function useCreateProgram() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: {
      brief: string;
      files: Array<{ file_id: string; role: string }>;
      autoQuestions?: boolean;
    }): Promise<CreatedProgramResponse> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(400);
        return mocks.mockCreatedProgram();
      }
      return (
        await apiFetch<CreatedProgramResponse>("/programs", {
          method: "POST",
          body: {
            brief: vars.brief,
            file_ids: vars.files,
            options: { auto_questions: vars.autoQuestions ?? true },
          },
          idempotencyKey: newIdempotencyKey(),
        })
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["programs"] });
    },
  });
}

export function useSubmitAnswers(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (answers: AnswerValue[]): Promise<AnswersResponse> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(350);
        return mocks.mockAnswers();
      }
      return (
        await apiFetch<AnswersResponse>(`/programs/${programId}/answers`, {
          method: "POST",
          body: { answers },
        })
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.questions(programId) });
    },
  });
}

// ---------------------------------------------------------------------------
// Мутации: каркас и Human Gate
// ---------------------------------------------------------------------------

export function useGenerateFramework(programId: string) {
  return useMutation({
    mutationFn: async (): Promise<{ job_id: string }> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(500);
        return { job_id: "job-framework-mock" };
      }
      return (await apiFetch<{ job_id: string }>(`/programs/${programId}/framework:generate`, { method: "POST" })).data;
    },
  });
}

/** Локальное применение операций PATCH — для оптимистичного отката (Д3 §8). */
function applyOpsLocally(framework: FrameworkData, ops: FrameworkOp[]): FrameworkData {
  const next: FrameworkData = {
    ...framework,
    modules: framework.modules.map((m) => ({
      ...m,
      topics: m.topics.map((t) => ({ ...t, workload: { ...t.workload }, locked: [...t.locked] })),
    })),
  };

  for (const op of ops) {
    if (op.op === "set_hours") {
      const topic = next.modules.flatMap((m) => m.topics).find((t) => t.ref === op.ref);
      if (topic) {
        topic.workload[op.activity] = op.hours;
        if (op.lock === true && !topic.locked.includes(`${op.activity}:in_person`)) {
          topic.locked.push(`${op.activity}:in_person`);
        }
        if (op.lock === false) {
          topic.locked = topic.locked.filter((k) => k !== `${op.activity}:in_person`);
        }
      }
    } else if (op.op === "rename") {
      for (const m of next.modules) {
        const topic = m.topics.find((t) => t.ref === op.ref);
        if (topic) topic.title = op.title;
        if (m.ref === op.ref) m.title = op.title;
      }
    } else if (op.op === "link_outcome") {
      const topic = next.modules.flatMap((m) => m.topics).find((t) => t.ref === op.topic_ref);
      if (topic && !topic.outcome_refs.includes(op.outcome_ref)) {
        topic.outcome_refs = [...topic.outcome_refs, op.outcome_ref];
      }
    }
    // move_topic не поддерживается оптимистично — сервер вернёт истину.
  }
  return next;
}

export function useSaveFramework(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { ops: FrameworkOp[]; etag: string | null }): Promise<FrameworkPatchResponse> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(300);
        const current = mocks.mockFramework();
        const updated = applyOpsLocally(withEtag(current, null), vars.ops);
        return {
          version: current.version + 1,
          checks: { passed: true, issues: [] },
          changed: updated.modules.flatMap((m) => m.topics.map((t) => ({ ref: t.ref }))),
        };
      }
      return (
        await apiFetch<FrameworkPatchResponse>(`/programs/${programId}/framework`, {
          method: "PATCH",
          body: { ops: vars.ops },
          ifMatch: vars.etag,
        })
      ).data;
    },
    onMutate: async (vars) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.framework(programId) });
      const previous = queryClient.getQueryData<FrameworkData>(queryKeys.framework(programId));
      if (previous) {
        queryClient.setQueryData(queryKeys.framework(programId), applyOpsLocally(previous, vars.ops));
      }
      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(queryKeys.framework(programId), context.previous);
      }
    },
    onSuccess: () => {
      // Сервер вернул {version, checks, changed}: истина — в перезапросе
      // (снимок версии + отчёт), поэтому инвалидируем, а не кладём ответ в кэш.
      void queryClient.invalidateQueries({ queryKey: queryKeys.framework(programId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.report(programId) });
    },
  });
}

export function useRebalanceFramework(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (scope?: string): Promise<RebalanceResponse> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(300);
        const current = mocks.mockFramework();
        return { version: current.version + 1, changed: [], checks: { passed: true, issues: [] } };
      }
      return (
        await apiFetch<RebalanceResponse>(`/programs/${programId}/framework:rebalance`, {
          method: "POST",
          body: { scope: scope ?? null, keep_locked: true },
        })
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.framework(programId) });
    },
  });
}

export function useApproveFramework(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { comment?: string; etag: string | null }) => {
      if (USE_MOCKS) {
        await mocks.mockDelay(350);
        mockP100Approved = true;
        return {
          status: "framework_approved" as const,
          version: 6,
          approved_by: "Методист (демо)",
          approved_at: new Date().toISOString(),
        };
      }
      return (
        await apiFetch<{ status: string; version: number; approved_by: string; approved_at: string }>(
          `/programs/${programId}/framework:approve`,
          { method: "POST", body: { comment: vars.comment ?? "" }, ifMatch: vars.etag },
        )
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.framework(programId) });
      void queryClient.invalidateQueries({ queryKey: ["programs"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Мутации: комплект, правки, выгрузка, версии, актуализация, адаптация, БЗ
// ---------------------------------------------------------------------------

export function useGenerateKit(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<{ job_id: string; estimate_minutes: number }> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(500);
        return { job_id: "job-kit-mock", estimate_minutes: 12 };
      }
      return (
        await apiFetch<{ job_id: string; estimate_minutes: number }>(
          `/programs/${programId}/kit:generate`,
          { method: "POST", body: {} },
        )
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.kit(programId) });
    },
  });
}

export function useRegenerateKitPart(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: {
      targetRef: string;
      parts: Array<"module_program" | "lecture_plan" | "slides" | "tests" | "tasks">;
    }): Promise<{ job_id: string }> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(300);
        return { job_id: "job-regen-mock" };
      }
      return (
        await apiFetch<{ job_id: string }>(`/programs/${programId}/kit:regenerate`, {
          method: "POST",
          body: { target_ref: vars.targetRef, parts: vars.parts },
        })
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.kit(programId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.report(programId) });
    },
  });
}

export function useCreateEdit(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: {
      targetRef: string;
      instruction: string;
      dryRun: boolean;
    }): Promise<EditResponse> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(400);
        return mocks.mockEditResponse(vars.dryRun);
      }
      return (
        await apiFetch<EditResponse>(`/programs/${programId}/edits`, {
          method: "POST",
          body: {
            target_ref: vars.targetRef,
            instruction: vars.instruction,
            dry_run: vars.dryRun,
          },
        })
      ).data;
    },
    onSuccess: (_data, vars) => {
      if (!vars.dryRun) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.kit(programId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.report(programId) });
      }
    },
  });
}

export function useExport(programId: string) {
  return useMutation({
    mutationFn: async (formats: ExportFormat[]): Promise<{ export_id: string }> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(300);
        return { export_id: "exp-mock-1" };
      }
      return (
        await apiFetch<{ export_id: string }>(`/programs/${programId}/exports`, {
          method: "POST",
          body: { formats },
        })
      ).data;
    },
  });
}

export function useRestoreVersion(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (version: number): Promise<{ version: number }> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(300);
        return { version: 8 };
      }
      return (
        await apiFetch<{ version: number }>(`/programs/${programId}/versions/${version}:restore`, {
          method: "POST",
        })
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.versions(programId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.framework(programId) });
    },
  });
}

export function useActualize(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { fileIds?: string[] } = {}): Promise<{ job_id: string }> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(700);
        return { job_id: "job-actualize-mock" };
      }
      // Файл уже загружен в /files; эндпоинт прикрепляет его к программе и
      // ставит задачу S22. Результат появится в program.profile.actualize_result.
      return (
        await apiFetch<{ job_id: string }>(`/programs/${programId}:actualize`, {
          method: "POST",
          body: { file_ids: vars.fileIds ?? [] },
        })
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.program(programId) });
    },
  });
}

export function useAdapt(programId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (request: AdaptRequest): Promise<AdaptResponse> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(500);
        return { job_id: "job-adapt-mock", status: "queued" };
      }
      // Программа-потомок создаётся воркером; эндпоинт отдаёт только задачу.
      return (
        await apiFetch<AdaptResponse>(`/programs/${programId}:adapt`, {
          method: "POST",
          body: request satisfies AdaptRequest,
        })
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["programs"] });
    },
  });
}

export function useAddKbDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: {
      file: File;
      role: KbDocRole;
      appliesTo: KbAppliesTo[] | null;
    }): Promise<{ doc_id: string }> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(500);
        return { doc_id: `kb-${Date.now()}` };
      }
      const uploaded = await apiUpload<UploadFileResponse>("/files", vars.file);
      return (
        await apiFetch<{ doc_id: string }>("/kb/documents", {
          method: "POST",
          body: {
            file_id: uploaded.data.file_id,
            title: vars.file.name,
            doc_role: vars.role,
            applies_to: vars.appliesTo,
          },
        })
      ).data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.kb() });
    },
  });
}

export function useDeleteKbDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (docId: string): Promise<void> => {
      if (USE_MOCKS) {
        await mocks.mockDelay(250);
        return;
      }
      await apiFetch<void>(`/kb/documents/${docId}`, { method: "DELETE" });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.kb() });
    },
  });
}

export function useMe(): UseQueryResult<{ role: string; email: string | null; display_name?: string }> {
  return useQuery({
    queryKey: ["me"],
    staleTime: 60_000,
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay(50);
        return { role: "methodist", email: "methodist@demo.local" };
      }
      return (await apiFetch<{ role: string; email: string | null }>("/me")).data;
    },
  });
}

export function useJob(jobId: string | null): UseQueryResult<JobInfo> {
  return useQuery({
    queryKey: ["job", jobId ?? ""],
    enabled: Boolean(jobId),
    queryFn: async () => {
      if (USE_MOCKS) {
        await mocks.mockDelay(200);
        return { id: jobId ?? "", kind: "framework", status: "succeeded" as const, error: null };
      }
      return (await apiFetch<JobInfo>(`/jobs/${jobId}`)).data;
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 2000;
    },
  });
}

// ---------------------------------------------------------------------------
// SSE: события программы
// ---------------------------------------------------------------------------

/**
 * Подписка на события программы (Д4 §6.7). Хук сам закрывает поток
 * при размонтировании и при смене программы.
 */
export function useProgramEvents(
  programId: string | null,
  onEvent: (event: ProgramEvent) => void,
  enabled = true,
): void {
  useEffect(() => {
    if (!programId || !enabled) return;
    const stream = openProgramEvents(programId, {
      onEvent,
      maxRetries: 5,
    });
    return () => stream.close();
    // onEvent намеренно не в зависимостях: подписка не пересоздаётся на каждом
    // рендере; обработчик читает актуальное состояние на стороне вызова.
  }, [programId, enabled]);
}

/** Вспомогательное: можно ли утверждать каркас при данных ограничениях. */
export function canApproveFramework(checks: { passed: boolean } | undefined): boolean {
  return Boolean(checks?.passed);
}
