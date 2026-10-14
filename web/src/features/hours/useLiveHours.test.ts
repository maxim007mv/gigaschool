/**
 * Тесты правил живого пересчёта часов (V-HRS-01…09).
 *
 * Фикстуры повторяют ТК-1: программа 16 ч = 14 ч темы + 2 ч аттестация,
 * ЛК 5 / ПР 9, занятия по 2 ч. Один корректный план и точечные поломки.
 */

import { describe, expect, it } from "vitest";

import { emptyWorkload, type Workload } from "../../entities/kit";
import { computeLiveHours, livePlanFromModules, type LiveConstraints, type LivePlan } from "./useLiveHours";

function workload(init: Partial<Workload>): Workload {
  return emptyWorkload(init);
}

function correctPlan(): LivePlan {
  return {
    modules: [
      {
        ref: "M1",
        title: "1. Первые шаги в Python",
        plannedTotal: 8,
        topics: [
          { ref: "T1.1", workload: workload({ lecture: 1, practice: 3, distance: 1 }) },
          { ref: "T1.2", workload: workload({ lecture: 2, practice: 2, distance: 2 }) },
        ],
      },
      {
        ref: "M2",
        title: "2. Условия и циклы",
        plannedTotal: 6,
        topics: [
          { ref: "T2.1", workload: workload({ lecture: 1, practice: 3, distance: 1 }) },
          { ref: "T2.2", workload: workload({ lecture: 1, practice: 1 }) },
        ],
      },
    ],
  };
}

function correctConstraints(): LiveConstraints {
  return {
    total: 16,
    finalAttHours: 2,
    unitHours: 2,
    minPracticeSharePct: 50,
    distanceMode: true,
    selfStudyOnly: false,
  };
}

describe("computeLiveHours: корректный план", () => {
  it("1. не даёт ложных срабатываний на плане 16 ч (14 + 2)", () => {
    const result = computeLiveHours(correctPlan(), correctConstraints());
    expect(result.issues).toEqual([]);
    expect(result.passed).toBe(true);
    expect(result.grand).toBe(16);
    expect(result.contentTotal).toBe(14);
  });

  it("2. считает часы модулей и контактную работу", () => {
    const result = computeLiveHours(correctPlan(), correctConstraints());
    const m1 = result.perModule.find((m) => m.ref === "M1");
    const m2 = result.perModule.find((m) => m.ref === "M2");
    expect(m1?.total).toBe(8);
    expect(m1?.contact).toBe(8);
    expect(m2?.total).toBe(6);
    expect(m2?.contact).toBe(6);
    expect(result.contact).toBe(14);
    expect(result.practiceAndLab).toBe(9);
    expect(result.workload.lecture).toBe(5);
    expect(result.workload.practice).toBe(9);
  });

  it("3. повторный вызов даёт тот же результат (детерминизм)", () => {
    const first = computeLiveHours(correctPlan(), correctConstraints());
    const second = computeLiveHours(correctPlan(), correctConstraints());
    expect(JSON.stringify(first)).toBe(JSON.stringify(second));
  });
});

describe("computeLiveHours: V-HRS-01…09", () => {
  it("4. V-HRS-02 — тема без часов", () => {
    const plan = correctPlan();
    plan.modules[0].topics[1].workload = workload({});
    const result = computeLiveHours(plan, correctConstraints());
    const issue = result.issues.find((i) => i.rule === "V-HRS-02");
    expect(issue).toBeDefined();
    expect(issue?.ref).toBe("T1.2");
    expect(issue?.message).toContain("T1.2");
  });

  it("5. V-HRS-03 — модуль без часов", () => {
    const plan = correctPlan();
    plan.modules[1].topics = plan.modules[1].topics.map((t) => ({ ...t, workload: workload({}) }));
    const result = computeLiveHours(plan, correctConstraints());
    expect(result.issues.some((i) => i.rule === "V-HRS-03" && i.ref === "M2")).toBe(true);
  });

  it("6. V-HRS-01 — сумма часов не сходится с объёмом", () => {
    const result = computeLiveHours(correctPlan(), { ...correctConstraints(), total: 20 });
    const issue = result.issues.find((i) => i.rule === "V-HRS-01");
    expect(issue).toBeDefined();
    expect(issue?.ref).toBeNull();
    expect(issue?.message).toBe("Сумма часов программы — 16 ч, а объём — 20 ч.");
  });

  it("7. V-HRS-04 — стажировка без аудиторных занятий", () => {
    const result = computeLiveHours(correctPlan(), { ...correctConstraints(), selfStudyOnly: true });
    const issue = result.issues.find((i) => i.rule === "V-HRS-04");
    expect(issue).toBeDefined();
    expect(issue?.message).toContain("14 ч");
  });

  it("8. V-HRS-05 — доля практики ниже минимума", () => {
    const result = computeLiveHours(correctPlan(), { ...correctConstraints(), minPracticeSharePct: 90 });
    const issue = result.issues.find((i) => i.rule === "V-HRS-05");
    expect(issue).toBeDefined();
    expect(issue?.message).toContain("9 ч");
    expect(issue?.message).toContain("15 ч");
  });

  it("9. V-HRS-06 — «Всего» строки не совпадает с суммой видов работ", () => {
    const plan = correctPlan();
    plan.modules[0].topics[0].declaredTotal = 5;
    const result = computeLiveHours(plan, correctConstraints());
    const issue = result.issues.find((i) => i.rule === "V-HRS-06");
    expect(issue).toBeDefined();
    expect(issue?.ref).toBe("T1.1");
    expect(issue?.message).toContain("5 ч");
  });

  it("10. V-HRS-07 — сумма тем модуля не совпадает с планом модуля", () => {
    const plan = correctPlan();
    plan.modules[0].plannedTotal = 10;
    const result = computeLiveHours(plan, correctConstraints());
    const issue = result.issues.find((i) => i.rule === "V-HRS-07");
    expect(issue).toBeDefined();
    expect(issue?.ref).toBe("M1");
    expect(issue?.message).toBe("Сумма тем модуля M1 — 8 ч, а по плану — 10 ч.");
  });

  it("11. V-HRS-08 — часы темы не кратны занятию", () => {
    const result = computeLiveHours(correctPlan(), { ...correctConstraints(), unitHours: 3 });
    expect(result.issues.some((i) => i.rule === "V-HRS-08" && i.ref === "T1.1")).toBe(true);
  });

  it("12. V-HRS-08 молчит при кратности 1", () => {
    const result = computeLiveHours(correctPlan(), { ...correctConstraints(), unitHours: 1 });
    expect(result.issues.some((i) => i.rule === "V-HRS-08")).toBe(false);
  });

  it("13. V-HRS-09 — дистанционных часов больше, чем аудиторных", () => {
    const plan = correctPlan();
    plan.modules[1].topics[0].workload = workload({ lecture: 1, practice: 3, distance: 5, self_study: 0 });
    const result = computeLiveHours(plan, correctConstraints());
    const issue = result.issues.find((i) => i.rule === "V-HRS-09");
    expect(issue).toBeDefined();
    expect(issue?.ref).toBe("T2.1");
  });

  it("14. V-HRS-09 не срабатывает, если форма без ДОТ", () => {
    const plan = correctPlan();
    plan.modules[1].topics[0].workload = workload({ lecture: 1, practice: 3, distance: 5 });
    const result = computeLiveHours(plan, { ...correctConstraints(), distanceMode: false, total: 18 });
    expect(result.issues.some((i) => i.rule === "V-HRS-09")).toBe(false);
  });

  it("15. замечание содержит правило, ссылку и понятный текст", () => {
    const result = computeLiveHours(correctPlan(), { ...correctConstraints(), total: 20 });
    for (const issue of result.issues) {
      expect(issue.rule).toMatch(/^V-HRS-\d{2}$/);
      expect(typeof issue.message).toBe("string");
      expect(issue.message.length).toBeGreaterThan(0);
      expect(issue.message).not.toContain("{");
    }
  });
});

describe("computeLiveHours: согласование с серверными правилами (после ревью)", () => {
  it("16. V-HRS-04 срабатывает для формы «стажировка» даже без флага self_study_only", () => {
    const result = computeLiveHours(correctPlan(), {
      ...correctConstraints(),
      internship: true,
      selfStudyOnly: false,
      total: 18,
    });
    expect(result.issues.some((i) => i.rule === "V-HRS-04")).toBe(true);
  });

  it("17. V-HRS-09 (программный уровень): есть ДОТ, но дистанционные часы не выделены", () => {
    const plan = correctPlan();
    for (const module of plan.modules) {
      for (const topic of module.topics) topic.workload.distance = 0;
    }
    const result = computeLiveHours(plan, correctConstraints());
    expect(result.issues.some((i) => i.rule === "V-HRS-09" && i.ref === null)).toBe(true);
  });

  it("18. livePlanFromModules не фиксирует устаревший «план» модуля — нет ложного V-HRS-07", () => {
    const modules = [
      {
        ref: "M1",
        number: 1,
        title: "Модуль",
        weight: 1,
        att_form: null,
        topics: [
          { ref: "T1.1", title: "Тема", workload: workload({ lecture: 2, practice: 4 }), locked: [] },
        ],
      },
    ] as unknown as Parameters<typeof livePlanFromModules>[0];
    const plan = livePlanFromModules(modules);
    expect(plan.modules[0].plannedTotal).toBeUndefined();
    // Правим часы темы — расхождения «с планом» быть не должно.
    plan.modules[0].topics[0].workload = workload({ lecture: 1, practice: 4 });
    const result = computeLiveHours(plan, { ...correctConstraints(), total: 7, distanceMode: false });
    expect(result.issues.some((i) => i.rule === "V-HRS-07")).toBe(false);
  });
});
