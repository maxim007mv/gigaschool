/**
 * Обработка ошибок API в формате RFC 9457 (application/problem+json).
 *
 * Server (Д4 §7) возвращает объект с полями type/title/status/detail/code,
 * а для ошибок часов — ещё и список issues с кодами правил V-HRS.
 */

import { T } from "../i18n/ru";

export interface ProblemIssue {
  rule_code?: string;
  entity_ref?: string | null;
  message?: string;
}

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  /** Код из каталога ошибок Д4 §7 (BAD_REQUEST, GATE_NOT_PASSED, …). */
  code?: string;
  detail?: string;
  instance?: string;
  issues?: ProblemIssue[];
  [key: string]: unknown;
}

/** Понятные методисту заголовки по кодам ошибок (Д4 §7). */
export const PROBLEM_TITLES: Record<string, string> = {
  BAD_REQUEST: "Некорректный запрос",
  UNAUTHORIZED: "Нужно войти в систему",
  FORBIDDEN: "Недостаточно прав",
  NOT_FOUND: "Не найдено",
  EDIT_TARGET_NOT_FOUND: "Элемент для правки не найден",
  GATE_NOT_PASSED: "Сначала утвердите каркас",
  HOURS_MISMATCH: "Часы не сходятся",
  CLARIFICATION_REQUIRED: "Нужны ответы на вопросы",
  JOB_IN_PROGRESS: "Задача уже выполняется",
  VERSION_CONFLICT: "Каркас изменил другой пользователь",
  FILE_TOO_LARGE: "Файл больше 50 МБ",
  UNSUPPORTED_FILE: "Неподдерживаемый тип файла",
  VALIDATION_ERROR: "Ошибка в данных",
  INFEASIBLE_CONSTRAINTS: "Ограничения часов несовместимы",
  RATE_LIMITED: "Слишком много запросов",
  LLM_BAD_OUTPUT: "Сервис вернул неразборчивый ответ",
  LLM_UNAVAILABLE: "Сервис сборки временно недоступен",
};

export function problemTitle(problem: ProblemDetails): string {
  if (problem.code && PROBLEM_TITLES[problem.code]) return PROBLEM_TITLES[problem.code];
  if (problem.title) return problem.title;
  return T.app.error;
}

export function problemMessage(problem: ProblemDetails): string {
  if (problem.detail) return problem.detail;
  if (problem.title) return problem.title;
  if (problem.code && PROBLEM_TITLES[problem.code]) return PROBLEM_TITLES[problem.code];
  return T.app.error;
}

/** Тексты нарушений из issues (например, HOURS_MISMATCH при утверждении). */
export function problemIssueMessages(problem: ProblemDetails): string[] {
  return (problem.issues ?? [])
    .map((i) => i.message)
    .filter((m): m is string => typeof m === "string" && m.length > 0);
}

export function isVersionConflict(problem: ProblemDetails): boolean {
  return problem.code === "VERSION_CONFLICT" || problem.status === 412;
}

export function isGateNotPassed(problem: ProblemDetails): boolean {
  return problem.code === "GATE_NOT_PASSED";
}
