/**
 * Форматтеры отображения: часы, даты, проценты, длительности.
 * Все числа — русская типографика, деньги — из строки (Decimal на сервере).
 */

import { T } from "../shared/i18n/ru";
import type {
  AssessmentKind,
  OutcomeType,
  ProgramForm,
  ProgramKind,
  ProgramStatus,
  QuestionType,
  SourceSection,
  VerifyStatus,
} from "./kit";

/** «16 ч» */
export function formatHours(hours: number): string {
  return `${hours} ч`;
}

/** Склонение существительных: pluralRu(2, ["час", "часа", "часов"]) → «часа». */
export function pluralRu(n: number, forms: readonly [string, string, string]): string {
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs > 10 && abs < 20) return forms[2];
  if (last > 1 && last < 5) return forms[1];
  if (last === 1) return forms[0];
  return forms[2];
}

/** «1 ошибка», «2 ошибки», «5 ошибок» */
export function formatCount(n: number, forms: readonly [string, string, string]): string {
  return `${n} ${pluralRu(n, forms)}`;
}

export const ERROR_FORMS = ["ошибка", "ошибки", "ошибок"] as const;
export const WARNING_FORMS = ["предупреждение", "предупреждения", "предупреждений"] as const;
export const ISSUE_FORMS = ["замечание", "замечания", "замечаний"] as const;

/** 45 → «45 с»; 105 → «1 мин 45 с»; 690 → «11 мин 30 с». */
export function formatDurationSec(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} с`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest === 0 ? `${minutes} мин` : `${minutes} мин ${rest} с`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes === 0 ? `${hours} ч` : `${hours} ч ${restMinutes} мин`;
}

/** 412 → «412 мс»; 1240 → «1,2 с». */
export function formatMillis(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} мс`;
  return `${(ms / 1000).toFixed(1).replace(".", ",")} с`;
}

/** ISO 8601 (UTC) → «13.10.2026». */
export function formatDateRu(iso: string | null | undefined): string {
  if (!iso) return T.app.none;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return T.app.none;
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** ISO 8601 (UTC) → «13.10.2026, 14:05». */
export function formatDateTimeRu(iso: string | null | undefined): string {
  if (!iso) return T.app.none;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return T.app.none;
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 712400 → «712 400» (пробелы как в русской типографике). */
export function formatInteger(n: number): string {
  return n.toLocaleString("ru-RU");
}

/** «0,74 млн токенов» — только для экрана «Эффект» (Д3 §12). */
export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2).replace(".", ",")} млн токенов`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(".", ",")} тыс. токенов`;
  return `${n} токенов`;
}

/** «0,74 ₽» — сумма приходит строкой (Decimal) или числом. */
export function formatRub(value: string | number): string {
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return T.app.none;
  return `${n.toFixed(2).replace(".", ",")} ₽`;
}

/** Доля 0.45 → «45 %». */
export function formatPercent(share: number): string {
  return `${Math.round(share * 100)} %`;
}

// Подписи значений из справочников (словарь Д3 §12)

export function formatProgramKind(kind: ProgramKind): string {
  return T.kinds[kind];
}

export function formatProgramForm(form: ProgramForm): string {
  return T.forms[form];
}

export function formatStatus(status: ProgramStatus): string {
  return T.statuses[status];
}

export function formatOutcomeType(type: OutcomeType): string {
  return T.outcomeTypes[type];
}

export function formatOutcomeTypeShort(type: OutcomeType): string {
  return T.outcomeTypeShort[type];
}

export function formatVerifyStatus(status: VerifyStatus): string {
  return T.verifyStatus[status];
}

export function formatSourceSection(section: SourceSection): string {
  return T.sourceSections[section];
}

export function formatAssessmentKind(kind: AssessmentKind): string {
  return T.assessmentKinds[kind];
}

export function formatQuestionType(qtype: QuestionType): string {
  return T.questionTypes[qtype];
}
