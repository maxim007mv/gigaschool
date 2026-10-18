/**
 * Моки данных для dev-режима, пока backend не поднят (quries.ts включает их,
 * только если import.meta.env.DEV и VITE_USE_MOCKS !== "0").
 *
 * Типы строго соответствуют entities/kit.ts, поэтому замена моков на
 * настоящий API не меняет код страниц.
 */

import {
  emptyWorkload,
  type ActualizeResult,
  type AnswersResponse,
  type CreatedProgramResponse,
  type EditResponse,
  type ExportStatusResponse,
  type FrameworkResponse,
  type KbDocument,
  type KitV1,
  type ProgramListResponse,
  type ProgramSummary,
  type QuestionsResponse,
  type Report,
  type Usage,
  type VersionDiffResponse,
  type VersionSummary,
} from "../../entities/kit";

/** Небольшая задержка, чтобы скелетоны были видны глазами. */
export function mockDelay(ms = 150): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Программы
// ---------------------------------------------------------------------------

export const MOCK_PROGRAMS: ProgramSummary[] = [
  {
    id: "p-100-python",
    title: "Python с нуля: первые шаги для школьников (16 ч)",
    kind: "dop",
    form: "full_time",
    total_hours: 16,
    status: "kit_review",
    audience: "Школьники 8–9 классов",
    updated_at: "2026-10-13T09:40:00Z",
    needs_input: false,
  },
  {
    id: "p-101-ai-teacher",
    title: "Искусственный интеллект для учителя",
    kind: "dpp_pk",
    form: "part_time",
    total_hours: 36,
    status: "framework_review",
    audience: "Учителя школ",
    updated_at: "2026-10-12T16:05:00Z",
    needs_input: false,
  },
  {
    id: "p-102-cyber",
    title: "Основы кибербезопасности",
    kind: "dpp_pk",
    form: "full_time",
    total_hours: 72,
    status: "clarifying",
    audience: "Студенты колледжа",
    updated_at: "2026-10-13T08:15:00Z",
    needs_input: true,
  },
  {
    id: "p-103-devops",
    title: "DevOps-стажировка",
    kind: "dpp_pk",
    form: "internship",
    total_hours: 256,
    status: "framework_approved",
    audience: "Начинающие инженеры",
    updated_at: "2026-10-11T12:00:00Z",
    needs_input: false,
  },
];

export function mockPrograms(filters: {
  status?: string;
  kind?: string;
  q?: string;
} = {}): ProgramListResponse {
  let items = MOCK_PROGRAMS;
  if (filters.status && filters.status !== "all") {
    items = items.filter((p) => p.status === filters.status);
  }
  if (filters.kind && filters.kind !== "all") {
    items = items.filter((p) => p.kind === filters.kind);
  }
  if (filters.q) {
    const q = filters.q.trim().toLowerCase();
    items = items.filter((p) => p.title.toLowerCase().includes(q));
  }
  return { items, next_cursor: null };
}

export function mockCreatedProgram(): CreatedProgramResponse {
  return {
    program_id: "p-102-cyber",
    status: "clarifying",
    job_id: "job-mock-1",
    events: "/api/v1/programs/p-102-cyber/events",
    detected: {
      kind: null,
      total_hours: null,
      audience: "студенты колледжа",
      form: null,
      final_attestation: null,
      schedule: "примерно месяц",
    },
  };
}

// ---------------------------------------------------------------------------
// Уточняющие вопросы
// ---------------------------------------------------------------------------

export function mockQuestions(): QuestionsResponse {
  return {
    status: "clarifying",
    detected: {
      kind: null,
      total_hours: null,
      audience: "студенты колледжа",
      form: null,
      final_attestation: null,
      schedule: "примерно месяц",
    },
    questions: [
      {
        id: "q1",
        slot: "kind",
        ord: 1,
        text: "Какой это тип программы?",
        why: "От этого зависят шаблон АЦР и документ об обучении",
        options: ["Повышение квалификации", "Общеразвивающая"],
        allow_default: true,
        allow_free_text: false,
      },
      {
        id: "q2",
        slot: "total_hours",
        ord: 2,
        text: "Сколько всего академических часов?",
        why: "«Около месяца» не задаёт объём",
        options: ["16", "36", "72", "144"],
        allow_default: true,
        allow_free_text: true,
      },
      {
        id: "q3",
        slot: "audience",
        ord: 3,
        text: "Кто будет учиться?",
        why: "От аудитории зависят формулировки и сложность заданий",
        options: ["Школьники", "Студенты колледжа", "Специалисты с опытом работы"],
        allow_default: true,
        allow_free_text: true,
      },
      {
        id: "q4",
        slot: "form",
        ord: 4,
        text: "Как будут проходить занятия: очно, очно-заочно, дистанционно?",
        why: "Форма обучения влияет на распределение часов и дистанционные занятия",
        options: ["Очная", "Очно-заочная", "Дистанционная"],
        allow_default: true,
        allow_free_text: false,
      },
      {
        id: "q5",
        slot: "final_attestation",
        ord: 5,
        text: "Как проверить результат в конце?",
        why: "Итоговая аттестация входит в объём программы",
        options: ["Зачёт", "Экзамен с практическим заданием", "Защита проекта"],
        allow_default: true,
        allow_free_text: true,
      },
    ],
  };
}

export function mockAnswers(): AnswersResponse {
  return {
    status: "draft",
    ready_for_framework: true,
    assumptions: [
      "Режим занятий не указан: принято не более 4 ч в день (ответ «на ваше усмотрение»)",
    ],
  };
}

// ---------------------------------------------------------------------------
// Каркас (16 ч: 14 содержания + 2 аттестация — сходится с ТК-1)
// ---------------------------------------------------------------------------

export function mockFramework(): FrameworkResponse {
  return {
    version: 5,
    status: "framework_review",
    program: {
      kind: "dop",
      title: "Основы Python",
      form: "distance",
      total_hours: 16,
      final_attestation: { form: "защита мини-проекта", hours: 2 },
      document: "сертификат об обучении",
      legal_basis: [
        { ref: "SRC-01", act: "273-ФЗ «Об образовании в Российской Федерации»", status: "verified" },
      ],
      organization: "Академия цифрового развития",
      city: "Москва",
      year: 2026,
    },
    profile: {
      audience: "Школьники 8–9 классов",
      entry_level: "Умеют пользоваться компьютером",
      schedule: "2 занятия в неделю по 2 часа",
      duration_hint: "1 месяц",
      notes: null,
      glossary: { "переменная": "ячейка с именем, где хранится значение" },
      constraints: {
        min_practice_share_pct: 50,
        self_study_only: false,
        unit_hours: 2,
        max_hours_per_day: 4,
        days_per_week: 2,
        distance_share_pct: 25,
        self_study_share_pct: 0,
      },
    },
    goal: "Познакомить школьников с основами программирования на Python и довести до первого самостоятельного мини-проекта.",
    tasks: [
      "Освоить базовый синтаксис и среду разработки",
      "Научиться писать программы с условиями и циклами",
      "Выполнить мини-проект и защитить его",
    ],
    competencies: [
      {
        ref: "C1",
        title: "Пишет и запускает простые программы на Python",
        activity_kind: "Программирование",
        prof_standard: null,
        labor_functions: [],
        outcomes: [
          {
            ref: "LO1.1",
            type: "knowledge",
            text: "Знает базовый синтаксис Python: переменные, типы, ввод и вывод",
            bloom_level: 2,
          },
          {
            ref: "LO1.2",
            type: "skill",
            text: "Пишет и запускает простые программы в среде разработки",
            bloom_level: 3,
          },
          {
            ref: "LO1.3",
            type: "experience",
            text: "Выполнил мини-проект и защитил его перед группой",
            bloom_level: 5,
          },
        ],
      },
      {
        ref: "C2",
        title: "Обрабатывает данные со списками и строками",
        activity_kind: "Работа с данными",
        prof_standard: null,
        labor_functions: [],
        outcomes: [
          {
            ref: "LO2.1",
            type: "knowledge",
            text: "Понимает, как работают условия и циклы",
            bloom_level: 2,
          },
          {
            ref: "LO2.2",
            type: "skill",
            text: "Обрабатывает списки и строки в программах",
            bloom_level: 3,
          },
        ],
      },
    ],
    modules: [
      {
        ref: "M1",
        number: 1,
        title: "Первые шаги в Python",
        weight: 1.3,
        att_form: null,
        topics: [
          {
            ref: "T1.1",
            title: "Знакомство со средой и первая программа",
            summary: "Среда разработки, запуск программы, вывод на экран",
            workload: emptyWorkload({ lecture: 1, practice: 3, distance: 1 }),
            outcome_refs: ["LO1.1"],
            control_form: null,
            complexity: 1,
            practicality: 0.7,
            weight: 1.0,
            locked: [],
          },
          {
            ref: "T1.2",
            title: "Переменные, ввод и вывод",
            summary: "Переменные, типы данных, ввод значений пользователем",
            workload: emptyWorkload({ lecture: 2, practice: 2, distance: 2 }),
            outcome_refs: ["LO1.1", "LO1.2"],
            control_form: null,
            complexity: 2,
            practicality: 0.5,
            weight: 1.0,
            locked: [],
          },
        ],
      },
      {
        ref: "M2",
        number: 2,
        title: "Условия, циклы и первый проект",
        weight: 1.0,
        att_form: "мини-проект",
        topics: [
          {
            ref: "T2.1",
            title: "Условия и циклы",
            summary: "if/else, for, while на примерах из жизни",
            workload: emptyWorkload({ lecture: 1, practice: 3, distance: 1 }),
            outcome_refs: ["LO2.1"],
            control_form: null,
            complexity: 3,
            practicality: 0.6,
            weight: 1.0,
            locked: [],
          },
          {
            ref: "T2.2",
            title: "Списки и строки",
            summary: "Хранение и обработка наборов данных",
            workload: emptyWorkload({ lecture: 1, practice: 1 }),
            outcome_refs: ["LO2.2", "LO1.3"],
            control_form: null,
            complexity: 3,
            practicality: 0.8,
            weight: 1.0,
            locked: ["practice:in_person"],
          },
        ],
      },
    ],
    calendar: {
      weeks: 4,
      days: 8,
      days_per_week: 2,
      max_hours_per_day: 2,
      sessions: [
        { seq: 1, week: 1, day: 1, topic_ref: "T1.1", activity: "practice", mode: "in_person", hours: 2 },
        { seq: 2, week: 1, day: 4, topic_ref: "T1.1", activity: "lecture", mode: "distance", hours: 2 },
        { seq: 3, week: 2, day: 1, topic_ref: "T1.2", activity: "practice", mode: "in_person", hours: 2 },
        { seq: 4, week: 2, day: 4, topic_ref: "T1.2", activity: "lecture", mode: "distance", hours: 2 },
        { seq: 5, week: 3, day: 1, topic_ref: "T2.1", activity: "practice", mode: "in_person", hours: 2 },
        { seq: 6, week: 3, day: 4, topic_ref: "T2.1", activity: "practice", mode: "in_person", hours: 2 },
        { seq: 7, week: 4, day: 1, topic_ref: "T2.2", activity: "practice", mode: "in_person", hours: 2 },
        { seq: 8, week: 4, day: 4, topic_ref: null, activity: "exam_task", mode: "in_person", hours: 2 },
      ],
    },
    checks: { passed: true, issues: [] },
  };
}

// ---------------------------------------------------------------------------
// Комплект
// ---------------------------------------------------------------------------

export function mockReport(): Report {
  return {
    passed: true,
    version: 7,
    duration_ms: 412,
    summary: {
      hours: { ok: true, checked: 38 },
      coverage: { ok: true, outcomes: 3, min_assessments: 2 },
      sources: { verified: 2, unverified: 0, not_found: 0 },
      template: { sections_total: 17, filled: 17 },
      plagiarism: { max_overlap: 0.06 },
    },
    issues: [
      {
        rule_code: "V-REA-01",
        severity: "warning",
        entity_ref: "LO1.3",
        message:
          "Практический опыт LO1.3 за 16 ч — нереалистично: за такой объём формируется начальный опыт, перенесите результат в умения или увеличьте объём",
        fix_hint: null,
      },
    ],
    gaps: [
      "Заказчик хочет «пойти работать в сферу»; за 16 часов реалистичен начальный уровень — показано в отчёте.",
    ],
    sample_findings: [],
    assumptions: [
      "Режим занятий не указан: принято не более 4 ч в день (ответ «на ваше усмотрение»)",
      "Дистанционные занятия: 4 часа лекций (значение по умолчанию для ДОП с ДОТ)",
    ],
  };
}

export function mockUsage(): Usage {
  // Тариф xiaomi/mimo-v2.6-flash (~¥0.70/¥2.10 за 1M → малые ₽).
  return {
    calls: 41,
    prompt_tokens: 148_900,
    completion_tokens: 163_800,
    tokens: 312_700,
    cost_rub: "5.23",
    duration_s: 95,
    cache_hit_pct: 17.1,
    savings_hours: 40,
    methodologist_active_hours: 3.5,
    manual_baseline_hours: 40,
    first_time_framework_approval: true,
  };
}

export function mockKit(): KitV1 {
  const framework = mockFramework();
  return {
    schema_version: "kit.v1",
    program: framework.program,
    profile: framework.profile,
    placeholders: { order_number: "", order_date: "", teachers: [], signatures: [] },
    framework: {
      goal: framework.goal,
      tasks: framework.tasks,
      competencies: framework.competencies,
      modules: framework.modules,
      final_attestation: framework.program.final_attestation,
      calendar: framework.calendar,
      gaps: [],
    },
    content: {
      module_programs: [
        {
          ref: "MP-M1",
          kind: "module_program",
          module_ref: "M1",
          topic_ref: null,
          body: {
            summary: "Знакомство со средой разработки и базовыми элементами языка.",
            sections: [
              { title: "1. Что такое программа", text: "Разбираем, как компьютер исполняет команды, и запускаем первую программу." },
              { title: "2. Переменные", text: "Переменные хранят значения с именами. Виды данных: числа, строки." },
            ],
          },
          generated_by: "S11",
          stale: false,
        },
        {
          ref: "MP-M2",
          kind: "module_program",
          module_ref: "M2",
          topic_ref: null,
          body: {
            summary: "Условия, циклы и обработка наборов данных.",
            sections: [
              { title: "1. Условия if/else", text: "Программа выбирает действие в зависимости от значения." },
              { title: "2. Циклы", text: "Повторяем действия: for по списку и while по условию." },
            ],
          },
          generated_by: "S11",
          stale: false,
        },
      ],
      lecture_plans: [
        {
          ref: "LP-T1.1",
          kind: "lecture_plan",
          module_ref: "M1",
          topic_ref: "T1.1",
          body: {
            goal: "Показать, как запустить первую программу и получить результат.",
            blocks: [
              { title: "Что такое программа", minutes: 20 },
              { title: "Среда разработки", minutes: 15 },
              { title: "Первая программа print()", minutes: 25 },
            ],
            self_check: ["Что выведет print(\"Привет\")?"],
          },
          generated_by: "S12",
          stale: false,
        },
        {
          ref: "LP-T2.1",
          kind: "lecture_plan",
          module_ref: "M2",
          topic_ref: "T2.1",
          body: {
            goal: "Научиться управлять ходом программы с помощью условий и циклов.",
            blocks: [
              { title: "Условия if/else", minutes: 25 },
              { title: "Цикл for", minutes: 25 },
              { title: "Цикл while и практика", minutes: 10 },
            ],
            self_check: ["Сколько раз выполнится тело цикла for i in range(3)?"],
          },
          generated_by: "S12",
          stale: true,
        },
      ],
      slides: [
        {
          ref: "SL-T1.1",
          kind: "slides",
          module_ref: "M1",
          topic_ref: "T1.1",
          body: {
            slides: [
              { title: "Первая программа", bullets: ["Команды выполняются по порядку", "print() выводит текст на экран"] },
              { title: "Среда разработки", bullets: ["Файл, запуск, результат", "Ошибки — это нормально"] },
            ],
          },
          generated_by: "S13",
          stale: false,
        },
      ],
      sections: [
        {
          ref: "SEC-ANN",
          kind: "annotation",
          module_ref: null,
          topic_ref: null,
          body: {
            text: "Программа знакомит школьников 8–9 классов с основами программирования на языке Python и завершается защитой мини-проекта.",
          },
          generated_by: "S11",
          stale: false,
        },
      ],
      assessments: [
        {
          ref: "Q-001",
          kind: "test_question",
          topic_ref: "T1.1",
          module_ref: "M1",
          stem: "Какая команда выводит текст на экран?",
          qtype: "single",
          options: [
            { id: "a", text: "print(\"Привет\")" },
            { id: "b", text: "input(\"Привет\")" },
            { id: "c", text: "len(\"Привет\")" },
          ],
          answer_key: { correct: ["a"], explanation: "print() печатает значение в консоль." },
          rubric: [],
          outcome_refs: ["LO1.1"],
          difficulty: 1,
        },
        {
          ref: "Q-002",
          kind: "test_question",
          topic_ref: "T1.2",
          module_ref: "M1",
          stem: "Что произойдёт при выполнении x = 11/2?",
          qtype: "single",
          options: [
            { id: "a", text: "x станет числом с дробной частью" },
            { id: "b", text: "Будет ошибка" },
            { id: "c", text: "x станет строкой" },
          ],
          answer_key: { correct: ["a"], explanation: "Одинарная косая черта — деление с дробной частью." },
          rubric: [],
          outcome_refs: ["LO1.1"],
          difficulty: 2,
        },
        {
          ref: "Q-004",
          kind: "test_question",
          topic_ref: "T1.2",
          module_ref: "M1",
          stem: "Как считать значение, введённое пользователем?",
          qtype: "single",
          options: [
            { id: "a", text: "Значение = input()" },
            { id: "b", text: "Значение = print()" },
            { id: "c", text: "Значение = list()" },
          ],
          answer_key: { correct: ["a"], explanation: "input() возвращает введённую строку." },
          rubric: [],
          outcome_refs: ["LO1.2"],
          difficulty: 2,
        },
        {
          ref: "Q-003",
          kind: "test_question",
          topic_ref: "T2.1",
          module_ref: "M2",
          stem: "Сколько раз выполнится тело цикла: for i in range(2)?",
          qtype: "single",
          options: [
            { id: "a", text: "Два раза" },
            { id: "b", text: "Три раза" },
            { id: "c", text: "Ни одного" },
          ],
          answer_key: { correct: ["a"], explanation: "range(2) даёт значения 0 и 1." },
          rubric: [],
          outcome_refs: ["LO2.1"],
          difficulty: 2,
        },
        {
          ref: "Q-005",
          kind: "test_question",
          topic_ref: "T2.2",
          module_ref: "M2",
          stem: "Какой оператор добавит элемент в конец списка?",
          qtype: "single",
          options: [
            { id: "a", text: "append()" },
            { id: "b", text: "sort()" },
            { id: "c", text: "clear()" },
          ],
          answer_key: { correct: ["a"], explanation: "append() добавляет элемент в конец списка." },
          rubric: [],
          outcome_refs: ["LO2.2"],
          difficulty: 2,
        },
        {
          ref: "ST-T1.2-1",
          kind: "seminar_task",
          topic_ref: "T1.2",
          module_ref: "M1",
          stem: "Напишите программу-анкету: спросите имя и возраст и выведите приветствие.",
          qtype: null,
          options: [],
          answer_key: null,
          rubric: [
            { criterion: "Программа запускается без ошибок", max_points: 2, levels: ["0 — не запускается", "2 — запускается"] },
            { criterion: "Использованы ввод и вывод", max_points: 2, levels: ["0 — нет", "1 — частично", "2 — есть"] },
          ],
          outcome_refs: ["LO1.2", "LO1.3"],
          difficulty: 2,
        },
        {
          ref: "ST-T2.2-1",
          kind: "seminar_task",
          topic_ref: "T2.2",
          module_ref: "M2",
          stem: "Соберите список покупок из 5 строк и выведите его по одной позиции на строку.",
          qtype: null,
          options: [],
          answer_key: null,
          rubric: [
            { criterion: "Список создан и заполнен", max_points: 2, levels: ["0 — нет", "2 — да"] },
            { criterion: "Вывод по одному элементу", max_points: 2, levels: ["0 — нет", "1 — частично", "2 — да"] },
          ],
          outcome_refs: ["LO2.2"],
          difficulty: 3,
        },
        {
          ref: "FP-01",
          kind: "final_project",
          topic_ref: "T2.2",
          module_ref: "M2",
          stem: "Мини-проект: программа, которая задаёт вопросы и обрабатывает ответы.",
          qtype: null,
          options: [],
          answer_key: null,
          rubric: [
            { criterion: "Программа решает заявленную задачу", max_points: 4, levels: ["0–1 — не решает", "2–3 — частично", "4 — решает"] },
            { criterion: "Защита: объяснил ход решения", max_points: 2, levels: ["0 — нет", "1 — с подсказками", "2 — уверенно"] },
          ],
          outcome_refs: ["LO1.3"],
          difficulty: 3,
        },
      ],
      sources: [
        {
          ref: "SRC-01",
          section: "normative",
          citation: "Федеральный закон от 29.12.2012 № 273-ФЗ «Об образовании в Российской Федерации»",
          url: null,
          isbn: null,
          normative_act_ref: "273-ФЗ",
          status: "verified",
          evidence: {},
        },
        {
          ref: "SRC-02",
          section: "main",
          citation: "Бизли Д. Python. Книга рецептов. — М.: ДМК Пресс, 2020",
          url: null,
          isbn: "978-5-97060-820-9",
          normative_act_ref: null,
          status: "unverified",
          evidence: { reason: "каталог библиотек недоступен" },
        },
        {
          ref: "SRC-03",
          section: "internet",
          citation: "Документация Python на русском языке",
          url: "https://docs.python.org/ru/3/",
          isbn: null,
          normative_act_ref: null,
          status: "verified",
          evidence: {},
        },
        {
          ref: "SRC-04",
          section: "software",
          citation: "Python 3.12 (бесплатная среда разработки IDLE)",
          url: "https://www.python.org/downloads/",
          isbn: null,
          normative_act_ref: null,
          status: "verified",
          evidence: { version: "3.12" },
        },
      ],
    },
    assumptions: [
      { text: "Режим занятий не указан: принято не более 4 ч в день", slot: "schedule", accepted_value: "4 ч в день", source: "default" },
      { text: "Дистанционные занятия: 4 часа лекций", slot: "distance_share_pct", accepted_value: "25 %", source: "agent" },
    ],
    report: mockReport(),
    usage: mockUsage(),
  };
}

// ---------------------------------------------------------------------------
// Правки, версии, выгрузка, база знаний, актуализация
// ---------------------------------------------------------------------------

export function mockEditResponse(dryRun: boolean): EditResponse {
  return {
    edit_id: "ed-mock-1",
    status: dryRun ? "planned" : "running",
    affected: ["T2.3", "LP-T2.3", "SL-T2.3", "Q-018", "Q-019", "Q-020", "ST-T2.3-1", "MP-M2"],
    unchanged: ["hours", "competencies", "M1", "M3", "M4", "M5", "M6"],
    job_id: dryRun ? null : "job-edit-mock",
  };
}

export function mockVersions(): VersionSummary[] {
  return [
    { version: 7, reason: "edit:ed-1 — замена темы 2.3", created_at: "2026-10-13T09:40:00Z", created_by: "Методист А. И." },
    { version: 6, reason: "framework:approve — каркас утверждён", created_at: "2026-10-12T15:10:00Z", created_by: "Руководитель центра" },
    { version: 5, reason: "framework:rebalance — пересчёт часов модуля 2", created_at: "2026-10-12T14:52:00Z", created_by: "Агент" },
    { version: 4, reason: "framework:generate — собран каркас", created_at: "2026-10-12T14:20:00Z", created_by: "Агент" },
    { version: 3, reason: "answers — ответы на уточняющие вопросы", created_at: "2026-10-12T14:05:00Z", created_by: "Методист А. И." },
  ];
}

export function mockVersionDiff(): VersionDiffResponse {
  return {
    changed: ["T2.3", "LP-T2.3", "SL-T2.3", "Q-018", "Q-019", "Q-020", "ST-T2.3-1", "MP-M2"],
    added: [],
    removed: [],
  };
}

export function mockExportStatus(): ExportStatusResponse {
  return {
    status: "ready",
    version: 7,
    files: [
      { kind: "program_docx", name: "Программа_Основы_Python_16ч_v7.docx", url: "https://example.local/files/program.docx", expires_in: 900 },
      { kind: "slides_pptx", name: "Слайды_М1.pptx", url: "https://example.local/files/slides.pptx", expires_in: 900 },
      { kind: "tests_gift", name: "Тесты_GIFT.txt", url: "https://example.local/files/tests.gift", expires_in: 900 },
      { kind: "kit_json", name: "Комплект_v7.json", url: "https://example.local/files/kit.json", expires_in: 900 },
    ],
  };
}

export function mockKbDocuments(): KbDocument[] {
  return [
    { doc_id: "kb-1", title: "Шаблон ДПП АЦР", filename: "Шаблон ДПП АЦР.docx", doc_role: "template", applies_to: ["dpp_pk"], is_active: true, size_bytes: 45000, chunks: 42, created_at: "2026-10-05T10:00:00Z" },
    { doc_id: "kb-2", title: "Порядок организации ДПП (локальный акт)", filename: "Порядок организации ДПП (локальный акт).pdf", doc_role: "local_act", applies_to: null, is_active: true, size_bytes: 120000, chunks: 88, created_at: "2026-10-06T12:30:00Z" },
    { doc_id: "kb-3", title: "Методические рекомендации по ДОП", filename: "Методические рекомендации по ДОП.docx", doc_role: "other", applies_to: ["dop"], is_active: true, size_bytes: 30000, chunks: 0, created_at: "2026-10-13T09:00:00Z" },
  ];
}

export function mockActualizeResult(): ActualizeResult {
  return {
    outdated: [
      {
        element: "Работа с pandas 1.x",
        current: "старые методы индексации",
        reason: "Версия pandas 1.x устарела (каталог сервисов, снимок 13.10.2026)",
      },
    ],
    proposals: [
      {
        was: "Python 3.8 в примерах",
        proposed: "Python 3.12 в примерах и инструкциях",
        rationale: "Python 3.8 больше не поддерживается",
      },
      {
        was: "Приказ Минобрнауки № 499 от 01.07.2013",
        proposed: "Приказ Минобрнауки № 266 от 24.03.2025",
        rationale: "Приказ № 499 утратил силу с 01.09.2025",
      },
    ],
    snapshot_date: "2026-10-13",
    notes: "",
  };
}
