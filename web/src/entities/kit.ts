/**
 * Типы доменной модели KitV1 — зеркало `karkas/domain/kit.py` (Д4 §3, Д2 §5).
 *
 * Имена полей совпадают с backend-моделью один в один (snake_case), чтобы
 * JSON с сервера принимался без переименований. Итоги часов НЕ хранятся:
 * `Module.workload` и общий итог программы считаются функциями ниже.
 */

// ---------------------------------------------------------------------------
// Литеральные типы (совпадают с Literal[...] в kit.py)
// ---------------------------------------------------------------------------

export type SchemaVersion = "kit.v1";
export type OutcomeType = "knowledge" | "skill" | "experience";
export type ProgramKind = "dpp_pk" | "dop";
export type ProgramForm = "full_time" | "part_time" | "distance" | "internship";
export type DeliveryMode = "in_person" | "distance";
export type VerifyStatus = "verified" | "partially_verified" | "unverified" | "not_found" | "outdated";
export type IssueSeverity = "error" | "warning" | "info";
export type AssessmentKind =
  | "test_question"
  | "seminar_task"
  | "interview_question"
  | "final_project"
  | "exam_task"
  | "portfolio_item";
export type QuestionType =
  | "single"
  | "multiple"
  | "truefalse"
  | "short"
  | "matching"
  | "order"
  | "open";
export type SourceSection = "normative" | "main" | "additional" | "internet" | "software";
export type ContentBlockKind =
  | "module_program"
  | "lecture_plan"
  | "slides"
  | "template_section"
  | "annotation";

/** Виды работ с часами (ACTIVITIES в kit.py). */
export const ACTIVITIES = ["lecture", "practice", "lab", "self_study", "current_control"] as const;
export type Activity = (typeof ACTIVITIES)[number];

/** Контактные виды работ (CONTACT_ACTIVITIES в kit.py). */
export const CONTACT_ACTIVITIES = ["lecture", "practice", "lab"] as const;

/** Статусы программы (program_status, Д2 §5). */
export type ProgramStatus =
  | "draft"
  | "clarifying"
  | "framework_generating"
  | "framework_review"
  | "framework_approved"
  | "kit_generating"
  | "kit_review"
  | "kit_updating"
  | "archived"
  | "failed";

// ---------------------------------------------------------------------------
// Часы
// ---------------------------------------------------------------------------

/** Часы по видам работ. `total` — вычисляемый, хранить его нельзя (AD-3). */
export interface Workload {
  lecture: number;
  practice: number;
  lab: number;
  self_study: number;
  current_control: number;
  /** «из них дистанционно» — подмножество контактных часов. */
  distance: number;
}

export function emptyWorkload(init: Partial<Workload> = {}): Workload {
  return {
    lecture: 0,
    practice: 0,
    lab: 0,
    self_study: 0,
    current_control: 0,
    distance: 0,
    ...init,
  };
}

/** Итог строки: сумма всех видов работ. */
export function workloadTotal(w: Workload): number {
  return w.lecture + w.practice + w.lab + w.self_study + w.current_control;
}

/** Контактная работа: лекции + практика + лабораторные. */
export function workloadContact(w: Workload): number {
  return w.lecture + w.practice + w.lab;
}

/** Поэлементная сумма часов (модуль = Σ тем; программа = Σ модулей). */
export function sumWorkloads(items: Iterable<Workload>): Workload {
  const acc: Workload = emptyWorkload();
  for (const w of items) {
    acc.lecture += w.lecture;
    acc.practice += w.practice;
    acc.lab += w.lab;
    acc.self_study += w.self_study;
    acc.current_control += w.current_control;
    acc.distance += w.distance;
  }
  return acc;
}

// ---------------------------------------------------------------------------
// Каркас
// ---------------------------------------------------------------------------

export interface Outcome {
  ref: string; // LO1.2
  type: OutcomeType;
  text: string;
  bloom_level: number | null;
}

export interface ProfStandardRef {
  code: string; // 01.001
  title: string;
  status: "active" | "replaced" | "cancelled";
  order_number: string | null;
}

export interface LaborFunctionRef {
  code: string; // C/14.6
  title: string;
  otf_code: string | null;
}

export interface Competency {
  ref: string; // C1
  title: string;
  activity_kind: string | null;
  prof_standard: ProfStandardRef | null;
  labor_functions: LaborFunctionRef[];
  outcomes: Outcome[];
}

export interface Topic {
  ref: string; // T2.3
  title: string;
  summary: string | null;
  workload: Workload;
  outcome_refs: string[];
  control_form: string | null;
  complexity: number; // 1..5
  practicality: number; // 0 — теория, 1 — практика
  weight: number;
  /** Закреплённые ячейки в формате "practice:in_person" (kit.py). */
  locked: string[];
}

export interface Module {
  ref: string; // M2
  number: number;
  title: string;
  weight: number;
  att_form: string | null;
  topics: Topic[];
}

export interface CalendarSession {
  seq: number;
  week: number;
  day: number;
  topic_ref: string | null; // null = итоговая аттестация
  activity: string;
  mode: DeliveryMode;
  hours: number;
}

export interface Calendar {
  weeks: number;
  days: number;
  days_per_week: number;
  max_hours_per_day: number;
  sessions: CalendarSession[];
}

export interface FinalAttestation {
  form: string;
  hours: number;
}

export interface LegalBasis {
  ref: string;
  act: string;
  status: VerifyStatus;
}

export interface Framework {
  goal: string;
  tasks: string[];
  competencies: Competency[];
  modules: Module[];
  final_attestation: FinalAttestation;
  calendar: Calendar | null;
  gaps: string[];
}

// ---------------------------------------------------------------------------
// Содержание
// ---------------------------------------------------------------------------

export interface AssessmentOption {
  id: string;
  text: string;
}

export interface AnswerKey {
  correct: string[];
  explanation: string | null;
}

export interface Criterion {
  criterion: string;
  max_points: number;
  levels: string[];
}

export interface Assessment {
  ref: string; // Q-017
  kind: AssessmentKind;
  topic_ref: string | null;
  module_ref: string | null;
  stem: string;
  qtype: QuestionType | null;
  options: AssessmentOption[];
  answer_key: AnswerKey | null;
  rubric: Criterion[];
  outcome_refs: string[];
  difficulty: number | null;
}

export interface ContentBlock {
  ref: string;
  kind: ContentBlockKind;
  module_ref: string | null;
  topic_ref: string | null;
  body: Record<string, unknown>;
  generated_by: string | null;
  stale: boolean;
}

export interface Source {
  ref: string; // SRC-04
  section: SourceSection;
  citation: string;
  url: string | null;
  isbn: string | null;
  normative_act_ref: string | null;
  status: VerifyStatus;
  evidence: Record<string, unknown>;
}

export interface Content {
  module_programs: ContentBlock[];
  lecture_plans: ContentBlock[];
  slides: ContentBlock[];
  sections: ContentBlock[];
  assessments: Assessment[];
  sources: Source[];
}

// ---------------------------------------------------------------------------
// Программа, профиль, плейсхолдеры, отчёт, эффект
// ---------------------------------------------------------------------------

export interface ProgramHeader {
  kind: ProgramKind;
  title: string;
  form: ProgramForm;
  total_hours: number;
  final_attestation: FinalAttestation;
  document: string;
  legal_basis: LegalBasis[];
  organization: string | null;
  city: string | null;
  year: number | null;
}

export interface ProgramConstraints {
  min_practice_share_pct: number;
  self_study_only: boolean;
  unit_hours: number;
  max_hours_per_day: number;
  days_per_week: number;
  distance_share_pct: number;
  self_study_share_pct: number;
}

export interface ProgramProfile {
  audience: string | null;
  entry_level: string | null;
  schedule: string | null;
  duration_hint: string | null;
  notes: string | null;
  glossary: Record<string, string>;
  constraints: ProgramConstraints;
}

export interface TeacherPlaceholder {
  name: string;
  position: string;
  degree: string;
}

export interface SignaturePlaceholder {
  name: string;
  position: string;
}

/** Поля для ручного заполнения — всегда пустые (V-TPL-03). */
export interface Placeholders {
  order_number: string;
  order_date: string;
  teachers: TeacherPlaceholder[];
  signatures: SignaturePlaceholder[];
}

export interface ReportIssue {
  rule_code: string;
  severity: IssueSeverity;
  entity_ref: string | null;
  message: string;
  fix_hint: Record<string, unknown> | null;
}

export interface ReportSummary {
  hours?: { ok: boolean; checked: number };
  coverage?: { ok: boolean; outcomes: number; min_assessments: number };
  sources?: { verified: number; unverified: number; not_found: number };
  template?: { sections_total: number; filled: number };
  plagiarism?: { max_overlap: number };
  [key: string]: unknown;
}

export interface Report {
  passed: boolean;
  version: number | null;
  duration_ms: number;
  summary: ReportSummary;
  issues: ReportIssue[];
  gaps: string[];
  sample_findings: string[];
  assumptions: string[];
}

export interface Assumption {
  text: string;
  slot: string | null;
  accepted_value: string | null;
  source: "default" | "user" | "agent";
}

/** Деньги — Decimal на сервере; в JSON приходит строкой. */
export interface Usage {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  tokens: number;
  cost_rub: string;
  cache_hit_pct: number;
  p95_latency_ms?: number | null;
  savings_hours?: number | null;
  methodologist_active_hours?: number | null;
  manual_baseline_hours?: number | null;
  first_time_framework_approval?: boolean | null;
  duration_s?: number;
}

export interface KitV1 {
  schema_version: SchemaVersion;
  program: ProgramHeader;
  profile: ProgramProfile;
  placeholders: Placeholders;
  framework: Framework;
  content: Content;
  assumptions: Assumption[];
  report: Report | null;
  usage: Usage | null;
}

// ---------------------------------------------------------------------------
// Вычисляемые итоги (единственный источник — темы)
// ---------------------------------------------------------------------------

/** Часы модуля = Σ часов тем (вычисляется, не хранится: AD-3). */
export function moduleWorkload(module: Module): Workload {
  return sumWorkloads(module.topics.map((t) => t.workload));
}

/** Σ часов всех тем программы. */
export function kitFrameworkWorkload(kit: KitV1): Workload {
  return sumWorkloads(kit.framework.modules.flatMap((m) => m.topics.map((t) => t.workload)));
}

/** Σ тем + итоговая аттестация (должно равняться program.total_hours). */
export function kitGrandTotal(kit: KitV1): number {
  return workloadTotal(kitFrameworkWorkload(kit)) + kit.framework.final_attestation.hours;
}

export function iterTopics(kit: KitV1): Topic[] {
  return kit.framework.modules.flatMap((m) => m.topics);
}

export function iterOutcomes(kit: KitV1): Outcome[] {
  return kit.framework.competencies.flatMap((c) => c.outcomes);
}

export function findTopic(kit: KitV1, ref: string): Topic | undefined {
  return iterTopics(kit).find((t) => t.ref === ref);
}

export function findModule(kit: KitV1, ref: string): Module | undefined {
  return kit.framework.modules.find((m) => m.ref === ref);
}

export function findOutcome(kit: KitV1, ref: string): Outcome | undefined {
  return iterOutcomes(kit).find((o) => o.ref === ref);
}

export function findAssessment(kit: KitV1, ref: string): Assessment | undefined {
  return kit.content.assessments.find((a) => a.ref === ref);
}

// ---------------------------------------------------------------------------
// Закреплённые ячейки (замок в таблице часов)
// ---------------------------------------------------------------------------

/** Ключ закрепления ячейки: "practice:in_person" — как в kit.py. */
export function lockKey(activity: Activity, mode: DeliveryMode = "in_person"): string {
  return `${activity}:${mode}`;
}

export function isCellLocked(locked: readonly string[], activity: Activity): boolean {
  return locked.includes(lockKey(activity)) || locked.includes(activity);
}

export function toggleCellLock(locked: readonly string[], activity: Activity): string[] {
  const key = lockKey(activity);
  return locked.includes(key) ? locked.filter((k) => k !== key) : [...locked, key];
}

// ---------------------------------------------------------------------------
// API-типы (Д4 §6): карточки списка, вопросы, правки, выгрузки, версии, БЗ
// ---------------------------------------------------------------------------

export interface ProgramSummary {
  id: string;
  title: string;
  kind: ProgramKind | null;
  total_hours: number | null;
  status: ProgramStatus;
  updated_at: string;
  /** Поля ниже бэкенд в списке не отдаёт — доступны опционально (карточки деградируют мягко). */
  form?: ProgramForm;
  audience?: string | null;
  /** true — агент ждёт ответов на уточняющие вопросы. */
  needs_input?: boolean;
}

export interface ProgramListResponse {
  items: ProgramSummary[];
  next_cursor: string | null;
}

export interface ClarifyQuestion {
  id: string;
  slot: string;
  ord: number;
  text: string;
  why: string;
  options: string[];
  allow_default: boolean;
  allow_free_text: boolean;
}

export interface QuestionsResponse {
  status: ProgramStatus;
  detected: Record<string, string | null>;
  questions: ClarifyQuestion[];
}

export interface AnswerValue {
  id: string;
  value: string | null;
  use_default?: boolean;
}

export interface AnswersResponse {
  status: ProgramStatus;
  ready_for_framework: boolean;
  assumptions: string[];
}

export interface CheckIssue {
  rule_code: string;
  entity_ref: string | null;
  message: string;
  fix?: Record<string, unknown> | null;
}

export interface FrameworkChecks {
  passed: boolean;
  issues: CheckIssue[];
}

/** Сырой ответ GET /programs/{id}/framework (Д4 §6.4): KitV1 в конверте. */
export interface FrameworkApiResponse {
  version: number;
  status: ProgramStatus;
  kit: KitV1;
}

/** Ответ PATCH /programs/{id}/framework (Д4 §6.4): версия, проверки, изменения. */
export interface FrameworkPatchResponse {
  version: number;
  checks: FrameworkChecks;
  changed: Array<Record<string, unknown>>;
}

/**
 * Ответ GET /programs/{id}/framework в форме UI (view-model): плоская проекция
 * конверта `{version, status, kit}` — собирается в `queries.ts` (`frameworkFromApi`).
 */
export interface FrameworkResponse {
  version: number;
  status: ProgramStatus;
  program: ProgramHeader;
  profile: ProgramProfile;
  goal: string;
  tasks: string[];
  competencies: Competency[];
  modules: Module[];
  calendar: Calendar | null;
  checks: FrameworkChecks;
}

/** Операции правки каркаса (PATCH /framework). */
export type FrameworkOp =
  | { op: "set_hours"; ref: string; activity: Activity; hours: number; lock?: boolean }
  | { op: "rename"; ref: string; title: string }
  | { op: "move_topic"; ref: string; to_module: string; position: number }
  | { op: "link_outcome"; topic_ref: string; outcome_ref: string };

export interface RebalanceResponse {
  version: number;
  changed: Array<{ ref: string; [activity: string]: number | string | number[] | undefined }>;
  checks: FrameworkChecks;
}

/** Ответ POST /programs/{id}/edits — и dry_run (план), и применение (задача). */
export interface EditResponse {
  edit_id: string;
  status: "planned" | "running";
  affected: string[];
  unchanged: string[];
  job_id?: string | null;
}

export type ExportFormat = "docx" | "pptx" | "gift" | "moodle_xml" | "csv" | "json" | "report";

export interface ExportFile {
  kind: string;
  name?: string;
  url: string;
  expires_in?: number;
}

export interface ExportStatusResponse {
  status: "queued" | "running" | "ready" | "failed";
  version?: number;
  export_id?: string;
  files?: ExportFile[];
  error?: string;
}

/** Элемент ленты версий (GET /programs/{id}/versions, Д4 §6.2). */
export interface VersionSummary {
  version: number;
  reason: string;
  created_at: string;
  created_by: string | null;
}

/** Ответ GET .../versions/{version}/diff?to= (karkas.domain.diff). */
export interface VersionDiffResponse {
  changed: string[];
  added: string[];
  removed: string[];
}

/** Ответ POST /programs/{id}:adapt — фоновая задача (программа-потомок создаётся воркером). */
export interface AdaptResponse {
  job_id: string;
  status: string;
}

export type KbDocRole = "template" | "sample_program" | "local_act" | "prof_standard" | "fgos" | "other";
export type KbAppliesTo = "dpp_pk" | "dop";

/** Карточка программы GET /programs/{id} (Д4 §6.2). */
export interface ProgramDetails {
  id: string;
  title: string;
  kind: ProgramKind | null;
  total_hours: number | null;
  status: ProgramStatus;
  profile: Record<string, unknown>;
  constraints: Record<string, unknown>;
  lock_version: number;
}

/** Результат S22, сохраняемый в program.profile.actualize_result. */
export interface ActualizeResult {
  outdated: Array<{ element: string; current: string; reason: string }>;
  proposals: Array<{ was: string; proposed: string; rationale: string }>;
  snapshot_date: string;
  notes: string;
}

/** Элемент списка GET /kb/documents (Д4 §6.2, karkas/api/routers/kb.py). */
export interface KbDocument {
  doc_id: string;
  title: string;
  doc_role: KbDocRole;
  applies_to: KbAppliesTo[] | null;
  is_active: boolean;
  filename: string;
  size_bytes: number;
  chunks: number;
  created_at: string;
}

export interface JobInfo {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed";
  error: { code: string; detail: string } | null;
}

export interface ActualizeSuggestion {
  ref: string;
  was: string;
  proposed: string;
  reason: string;
  kind: "topic" | "tool" | "source";
}

export interface AdaptRequest {
  audience: string;
  total_hours: number;
  form: ProgramForm;
}

export interface CreateProgramRequest {
  brief: string;
  file_ids: Array<{ file_id: string; role: string }>;
  options: { auto_questions: boolean };
}

export interface CreatedProgramResponse {
  program_id: string;
  status: ProgramStatus;
  job_id: string;
  events: string;
  /** Что агент уже понял из брифа (появляется, когда разбор завершён). */
  detected?: Record<string, string | null>;
}

export interface UploadFileResponse {
  file_id: string;
  filename: string;
}
