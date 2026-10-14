/**
 * useLiveHours — живой пересчёт часов на клиенте (Д3 §8).
 *
 * Повторяет правила V-HRS-01…09, чтобы методист мгновенно видел расхождения
 * («время обнаружения расхождения часов — 0 с»). Источник истины остаётся
 * за сервером: framework:validate / framework:rebalance.
 *
 * Вход:
 *   plan.modules[i]      = { ref, topics: [{ ref, workload, locked, declaredTotal? }], plannedTotal? }
 *   constraints          = { total, finalAttHours, selfStudyOnly?, minPracticeSharePct?, unitHours?, distanceMode? }
 * Выход:
 *   { perModule: { ref, total, contact, … }[], grand, issues: { rule, ref, message }[] }
 */

import { useMemo } from "react";

import {
  CONTACT_ACTIVITIES,
  emptyWorkload,
  workloadContact,
  workloadTotal,
  type IssueSeverity,
  type Module,
  type Workload,
} from "../../entities/kit";
import { formatRuleMessage, RULES, type RuleCode } from "./rules";

export interface LiveTopicIn {
  ref: string;
  title?: string;
  workload: Workload;
  /** Закреплённые ячейки "practice:in_person" (замок в таблице). */
  locked?: string[];
  /** «Всего» строки из внешнего источника — для проверки V-HRS-06. */
  declaredTotal?: number;
}

export interface LiveModuleIn {
  ref: string;
  title?: string;
  topics: LiveTopicIn[];
  /** Плановые часы модуля (из плана солвера) — для проверки V-HRS-07. */
  plannedTotal?: number;
}

export interface LivePlan {
  modules: LiveModuleIn[];
}

export interface LiveConstraints {
  /** Запрошенный объём программы, ч. */
  total: number;
  /** Часы итоговой аттестации, ч. */
  finalAttHours: number;
  /** Стажировка без аудиторных занятий. */
  selfStudyOnly?: boolean;
  /** Форма обучения — стажировка (program.form === "internship"): как на сервере. */
  internship?: boolean;
  /** Минимальная доля практики и лабораторных, % от объёма. */
  minPracticeSharePct?: number;
  /** Кратность часов темы («пары»), по умолчанию 1. */
  unitHours?: number;
  /** Форма с дистанционными занятиями: показываем столбец «из них дистанционно». */
  distanceMode?: boolean;
}

/** Замечание клиентской проверки: { rule, ref, message } (см. задание). */
export interface LiveIssue {
  rule: RuleCode;
  ref: string | null;
  message: string;
  severity: IssueSeverity;
}

export interface ModuleHours {
  ref: string;
  title?: string;
  total: number;
  contact: number;
  /** Практика + лабораторные (для проверки доли практики). */
  practiceAndLab: number;
  workload: Workload;
  plannedTotal?: number;
}

export interface LiveHoursResult {
  perModule: ModuleHours[];
  /** Σ тем + итоговая аттестация. */
  grand: number;
  /** Σ часов всех тем (без аттестации). */
  contentTotal: number;
  /** Контактные часы: ЛК + ПР + ЛБ. */
  contact: number;
  practiceAndLab: number;
  /** Итог по видам работ (по всем темам). */
  workload: Workload;
  issues: LiveIssue[];
  passed: boolean;
}

function issue(rule: RuleCode, ref: string | null, params: Record<string, string | number>): LiveIssue {
  return {
    rule,
    ref,
    message: formatRuleMessage(rule, params),
    severity: RULES[rule].severity,
  };
}

/** Чистая функция пересчёта — основа хука и юнит-тестов. */
export function computeLiveHours(plan: LivePlan, constraints: LiveConstraints): LiveHoursResult {
  const unit = constraints.unitHours ?? 1;
  const issues: LiveIssue[] = [];
  const perModule: ModuleHours[] = [];
  const totals = emptyWorkload();

  for (const module of plan.modules) {
    const moduleWork = emptyWorkload();

    for (const topic of module.topics) {
      const w = topic.workload;
      const topicTotal = workloadTotal(w);
      const topicContact = workloadContact(w);

      // V-HRS-02: у каждой темы есть часы.
      if (topicTotal === 0) {
        issues.push(issue("V-HRS-02", topic.ref, { ref: topic.ref }));
      }

      // V-HRS-06: «Всего» строки = сумме видов работ.
      if (topic.declaredTotal !== undefined && topic.declaredTotal !== topicTotal) {
        issues.push(
          issue("V-HRS-06", topic.ref, { ref: topic.ref, sum: topicTotal, declared: topic.declaredTotal }),
        );
      }

      // V-HRS-08: часы темы кратны длительности занятия.
      if (unit > 1 && topicTotal > 0 && topicTotal % unit !== 0) {
        issues.push(issue("V-HRS-08", topic.ref, { ref: topic.ref, sum: topicTotal, unit }));
      }

      // V-HRS-09: дистанционные часы — только «из них», не больше аудиторных.
      if (constraints.distanceMode && w.distance > topicContact) {
        issues.push(
          issue("V-HRS-09", topic.ref, { ref: topic.ref, distance: w.distance, contact: topicContact }),
        );
      }

      moduleWork.lecture += w.lecture;
      moduleWork.practice += w.practice;
      moduleWork.lab += w.lab;
      moduleWork.self_study += w.self_study;
      moduleWork.current_control += w.current_control;
      moduleWork.distance += w.distance;
    }

    const moduleTotal = workloadTotal(moduleWork);

    // V-HRS-03: у каждого модуля есть часы.
    if (moduleTotal === 0) {
      issues.push(issue("V-HRS-03", module.ref, { ref: module.ref }));
    }

    // V-HRS-07: Σ тем модуля = плановые часы модуля (когда план известен).
    if (module.plannedTotal !== undefined && module.plannedTotal !== moduleTotal) {
      issues.push(issue("V-HRS-07", module.ref, { ref: module.ref, sum: moduleTotal, planned: module.plannedTotal }));
    }

    perModule.push({
      ref: module.ref,
      title: module.title,
      total: moduleTotal,
      contact: workloadContact(moduleWork),
      practiceAndLab: moduleWork.practice + moduleWork.lab,
      workload: moduleWork,
      plannedTotal: module.plannedTotal,
    });

    totals.lecture += moduleWork.lecture;
    totals.practice += moduleWork.practice;
    totals.lab += moduleWork.lab;
    totals.self_study += moduleWork.self_study;
    totals.current_control += moduleWork.current_control;
    totals.distance += moduleWork.distance;
  }

  const contentTotal = workloadTotal(totals);
  const contact = workloadContact(totals);
  const practiceAndLab = totals.practice + totals.lab;
  const grand = contentTotal + constraints.finalAttHours;

  // V-HRS-01: Σ тем + итоговая аттестация = запрошенный объём.
  if (grand !== constraints.total) {
    issues.push(issue("V-HRS-01", null, { grand, total: constraints.total }));
  }

  // V-HRS-04: стажировка без аудиторных занятий (флаг ограничения или форма
  // «стажировка» — так же, как _is_internship на сервере).
  if ((constraints.selfStudyOnly === true || constraints.internship === true) && contact > 0) {
    issues.push(issue("V-HRS-04", null, { contact }));
  }

  // V-HRS-09: есть ДОТ, но дистанционные часы нигде не выделены (серверная ветка).
  if (constraints.distanceMode && contact > 0 && totals.distance === 0) {
    issues.push(issue("V-HRS-09", null, { ref: "—", distance: totals.distance, contact }));
  }

  // V-HRS-05: минимальная доля практики и лабораторных.
  const minShare = constraints.minPracticeSharePct ?? 0;
  if (minShare > 0) {
    const need = Math.ceil((minShare / 100) * constraints.total);
    if (practiceAndLab < need) {
      issues.push(
        issue("V-HRS-05", null, { practice: practiceAndLab, need, pct: minShare, total: constraints.total }),
      );
    }
  }

  return {
    perModule,
    grand,
    contentTotal,
    contact,
    practiceAndLab,
    workload: totals,
    issues,
    passed: issues.length === 0,
  };
}

/** Хук живого пересчёта; мемоизирует результат по плану и ограничениям. */
export function useLiveHours(plan: LivePlan, constraints: LiveConstraints): LiveHoursResult {
  return useMemo(() => computeLiveHours(plan, constraints), [plan, constraints]);
}

/** Преобразование доменных модулей (kit.py) в live-план. */
export function livePlanFromModules(modules: readonly Module[]): LivePlan {
  return {
    modules: modules.map((m) => ({
      ref: m.ref,
      title: `${m.number}. ${m.title}`,
      // «Плановые» часы модуля НЕ фиксируем: в модели КАРКАС итог модуля
      // вычисляется из тем, а объявленные часы (module_program.body.hours)
      // проверяет серверный V-HRS-07. Иначе после любой правки ячейки
      // клиент показывал бы ложное расхождение с устаревшим снимком.
      topics: m.topics.map((t) => ({
        ref: t.ref,
        title: t.title,
        workload: t.workload,
        locked: t.locked,
      })),
    })),
  };
}

export { CONTACT_ACTIVITIES };
