/**
 * Тесты проекции конверта GET /framework → view-model UI (frameworkFromApi).
 *
 * Контракт бэкенда: {version, status, kit: KitV1}; UI-страницы ожидают плоскую
 * форму {program, profile, goal, modules, …, checks}. Эти тесты фиксируют
 * соответствие, чтобы моки и реальный API не расходились.
 */

import { describe, expect, it } from "vitest";

import type { FrameworkApiResponse, KitV1, Report } from "../../entities/kit";
import { frameworkFromApi, isProgramBusy } from "./queries";

function kit(): KitV1 {
  return {
    schema_version: "kit.v1",
    program: {
      kind: "dop",
      title: "Первые шаги в Python",
      form: "full_time",
      total_hours: 16,
      final_attestation: { form: "защита проекта", hours: 2 },
      document: "сертификат",
      legal_basis: [],
      organization: null,
      city: null,
      year: 2026,
    },
    profile: {
      audience: "Школьники",
      entry_level: "Нулевой",
      schedule: null,
      duration_hint: null,
      notes: null,
      glossary: {},
      constraints: {
        min_practice_share_pct: 50,
        self_study_only: false,
        unit_hours: 2,
        max_hours_per_day: 2,
        days_per_week: 2,
        distance_share_pct: 0,
        self_study_share_pct: 0,
      },
    },
    placeholders: { order_number: "", order_date: "", teachers: [], signatures: [] },
    framework: {
      goal: "Познакомить с Python",
      tasks: ["Сформировать компетенцию: основы"],
      competencies: [],
      modules: [
        {
          ref: "M1",
          number: 1,
          title: "Основы",
          weight: 1,
          att_form: null,
          topics: [
            { ref: "T1.1", title: "Введение", summary: null, workload: { lecture: 5, practice: 9, lab: 0, self_study: 0, current_control: 0, distance: 0 }, outcome_refs: [], control_form: null, complexity: 1, practicality: 0.6, weight: 1, locked: [] },
          ],
        },
      ],
      final_attestation: { form: "защита проекта", hours: 2 },
      calendar: null,
      gaps: [],
    },
    content: {
      module_programs: [],
      lecture_plans: [],
      slides: [],
      sections: [],
      assessments: [],
      sources: [],
    },
    assumptions: [],
    report: null,
    usage: null,
  };
}

function apiResponse(): FrameworkApiResponse {
  return { version: 3, status: "framework_review", kit: kit() };
}

function report(): Report {
  return {
    passed: false,
    version: 3,
    duration_ms: 12,
    summary: {},
    issues: [
      { rule_code: "V-HRS-01", severity: "error", entity_ref: null, message: "Сумма 15 из 16 ч", fix_hint: null },
    ],
    gaps: [],
    sample_findings: [],
    assumptions: [],
  };
}

describe("frameworkFromApi", () => {
  it("разворачивает конверт {version, status, kit} в плоскую форму страниц", () => {
    const data = frameworkFromApi(apiResponse(), null);
    expect(data.version).toBe(3);
    expect(data.status).toBe("framework_review");
    expect(data.program.title).toBe("Первые шаги в Python");
    expect(data.profile.constraints.unit_hours).toBe(2);
    expect(data.goal).toBe("Познакомить с Python");
    expect(data.modules[0].topics[0].ref).toBe("T1.1");
    expect(data.checks).toEqual({ passed: true, issues: [] });
  });

  it("переносит замечания отчёта в checks (вкладка «Замечания» и блокировка утверждения)", () => {
    const data = frameworkFromApi(apiResponse(), report());
    expect(data.checks.passed).toBe(false);
    expect(data.checks.issues[0].rule_code).toBe("V-HRS-01");
    expect(data.checks.issues[0].message).toContain("15 из 16");
  });
});

describe("isProgramBusy", () => {
  it("опрашивает программу, пока идёт каркас или комплект", () => {
    expect(isProgramBusy("framework_generating")).toBe(true);
    expect(isProgramBusy("kit_generating")).toBe(true);
    expect(isProgramBusy("kit_updating")).toBe(true);
  });

  it("не опрашивает программу в спокойных статусах", () => {
    expect(isProgramBusy("framework_review")).toBe(false);
    expect(isProgramBusy("kit_review")).toBe(false);
    expect(isProgramBusy(undefined)).toBe(false);
  });
});
