/**
 * Правила проверки часов (клиентская копия V-HRS-01…09, Д3 §8, Д4 §5.8).
 *
 * RULES — единый JSON-объект: код → заголовок, серьёзность и шаблон текста.
 * Тексты — на русском, без технического жаргона (Д3 §12), с {подстановками},
 * которые заполняет formatRuleMessage.
 */

import type { IssueSeverity } from "../../entities/kit";

export interface RuleDefinition {
  /** Код правила из отчёта автопроверки. */
  code: string;
  /** Короткий заголовок для списка замечаний. */
  title: string;
  severity: IssueSeverity;
  /** Текст для методиста; {placeholder} заполняется через formatRuleMessage. */
  message: string;
}

export const RULES = {
  "V-HRS-01": {
    code: "V-HRS-01",
    title: "Сумма часов программы",
    severity: "error",
    message: "Сумма часов программы — {grand} ч, а объём — {total} ч.",
  },
  "V-HRS-02": {
    code: "V-HRS-02",
    title: "Тема без часов",
    severity: "error",
    message: "У темы {ref} не проставлены часы.",
  },
  "V-HRS-03": {
    code: "V-HRS-03",
    title: "Модуль без часов",
    severity: "error",
    message: "В модуле {ref} нет часов: ни у одной темы не заполнено время.",
  },
  "V-HRS-04": {
    code: "V-HRS-04",
    title: "Стажировка: только самостоятельная работа",
    severity: "error",
    message:
      "Программа-стажировка: лекций, практики и лабораторных быть не должно, а сейчас {contact} ч аудиторных.",
  },
  "V-HRS-05": {
    code: "V-HRS-05",
    title: "Минимальная доля практики",
    severity: "error",
    message:
      "Практика и лабораторные — {practice} ч, а нужно не меньше {need} ч ({pct} % от {total} ч).",
  },
  "V-HRS-06": {
    code: "V-HRS-06",
    title: "Сумма видов работ",
    severity: "error",
    message: "Сумма видов работ по теме {ref} — {sum} ч, а в строке «Всего» — {declared} ч.",
  },
  "V-HRS-07": {
    code: "V-HRS-07",
    title: "Сумма тем модуля",
    severity: "error",
    message: "Сумма тем модуля {ref} — {sum} ч, а по плану — {planned} ч.",
  },
  "V-HRS-08": {
    code: "V-HRS-08",
    title: "Кратность часов",
    severity: "error",
    message: "Часы темы {ref} — {sum} ч: число не кратно занятию {unit} ч.",
  },
  "V-HRS-09": {
    code: "V-HRS-09",
    title: "Дистанционные часы",
    severity: "error",
    message: "В теме {ref} дистанционных часов больше, чем аудиторных ({distance} из {contact} ч).",
  },
} as const satisfies Record<string, RuleDefinition>;

export type RuleCode = keyof typeof RULES;

/** Пороговые константы интерфейса (единое место, Д4 §12). */
export const THRESHOLDS = {
  /** V-COV-02: минимум оценочных средств на результат обучения. */
  minAssessmentsPerOutcome: 2,
  /** HoursCell в kit.py: часы одной ячейки — 0…500. */
  maxHoursPerCell: 500,
} as const;

/** Подстановка значений в шаблон текста правила. */
export function formatRuleMessage(code: RuleCode, params: Record<string, string | number>): string {
  const template = RULES[code].message as string;
  return template.replace(/\{(\w+)\}/g, (_match, key: string) => {
    const value = params[key];
    return value === undefined ? `{${key}}` : String(value);
  });
}
