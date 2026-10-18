"""Тесты выгрузки GIFT (karkas.infra.exporters.gift).

Здесь же собирается общая фикстура комплекта ``build_export_kit()``: 2 модуля,
3 темы, 4 тестовых вопроса (single, multiple, truefalse, short), задание семинара,
итоговый проект, источники verified/unverified, слайд-блок, план лекции и отчёт
самопроверки. Её импортируют соседние тесты выгрузок (moodle/csv/json, docx/pptx).
"""

from __future__ import annotations

import pytest

from karkas.domain.kit import (
    AnswerKey,
    Assessment,
    AssessmentOption,
    Assumption,
    Calendar,
    CalendarSession,
    Competency,
    Content,
    ContentBlock,
    Criterion,
    FinalAttestation,
    Framework,
    KitV1,
    LaborFunctionRef,
    LegalBasis,
    Module,
    Outcome,
    ProfStandardRef,
    ProgramHeader,
    ProgramProfile,
    Report,
    ReportIssue,
    Source,
    Topic,
    Workload,
)
from karkas.infra.exporters.gift import export_gift

ESCAPING_STEM = "Что выведет код, если x = 2 ~ 3 # важно: {5}?"


def build_export_kit() -> KitV1:
    """Комплект для тестов выгрузок: 2 модуля, 3 темы, 4 тестовых вопроса (Σ тем 34 + ИА 2 = 36)."""
    topic_1_1 = Topic(
        ref="T1.1",
        title="Введение в Python",
        workload=Workload(lecture=4, practice=6, self_study=2, distance=2),
        outcome_refs=["LO1.1", "LO1.2"],
        control_form="тест",
        complexity=1,
        practicality=0.7,
    )
    topic_1_2 = Topic(
        ref="T1.2",
        title="Функции и модули",
        workload=Workload(lecture=2, practice=4, current_control=2),
        outcome_refs=["LO1.2"],
        control_form="практическая работа",
        complexity=2,
        practicality=0.8,
    )
    topic_2_1 = Topic(
        ref="T2.1",
        title="Анализ данных в pandas",
        workload=Workload(lecture=4, practice=6, self_study=2, current_control=2, distance=2),
        outcome_refs=["LO2.1"],
        control_form="тест",
        complexity=3,
        practicality=0.9,
    )
    module_1 = Module(
        ref="M1",
        number=1,
        title="Основы Python",
        topics=[topic_1_1, topic_1_2],
        att_form="тест",
    )
    module_2 = Module(
        ref="M2",
        number=2,
        title="Обработка данных в pandas",
        topics=[topic_2_1],
        att_form="итоговый проект",
    )
    competencies = [
        Competency(
            ref="C1",
            title="Применять основы программирования на Python",
            activity_kind="разработка программ",
            prof_standard=ProfStandardRef(code="06.001", title="Программист", status="active"),
            labor_functions=[LaborFunctionRef(code="A/01.6", title="Разработка простых программных модулей")],
            outcomes=[
                Outcome(ref="LO1.1", type="knowledge", text="Знает базовый синтаксис и типы данных Python"),
                Outcome(ref="LO1.2", type="skill", text="Умеет писать функции и подключать модули"),
            ],
        ),
        Competency(
            ref="C2",
            title="Выполнять анализ данных средствами pandas",
            activity_kind="анализ данных",
            outcomes=[
                Outcome(
                    ref="LO2.1",
                    type="experience",
                    text="Владеет приёмами обработки табличных данных в pandas",
                )
            ],
        ),
    ]
    framework = Framework(
        goal="Сформировать практические навыки анализа данных на Python",
        tasks=["Освоить базовый синтаксис Python", "Научиться обрабатывать табличные данные в pandas"],
        competencies=competencies,
        modules=[module_1, module_2],
        final_attestation=FinalAttestation(form="защита итогового проекта", hours=2),
        calendar=Calendar(
            weeks=3,
            days=8,
            days_per_week=3,
            max_hours_per_day=4,
            sessions=[
                CalendarSession(seq=1, week=1, day=1, topic_ref="T1.1", activity="lecture", hours=4),
                CalendarSession(seq=2, week=1, day=2, topic_ref="T1.1", activity="practice", hours=4),
                CalendarSession(
                    seq=3,
                    week=3,
                    day=8,
                    topic_ref=None,
                    activity="final_attestation",
                    hours=2,
                ),
            ],
        ),
    )
    assessments = [
        Assessment(
            ref="Q-001",
            kind="test_question",
            topic_ref="T1.1",
            module_ref="M1",
            stem=ESCAPING_STEM,
            qtype="single",
            options=[
                AssessmentOption(id="a", text="print(x=2)"),
                AssessmentOption(id="b", text="print(x~2)"),
                AssessmentOption(id="c", text="print(x#2)"),
                AssessmentOption(id="d", text="print(x:2)"),
            ],
            answer_key=AnswerKey(correct=["a"], explanation="Верно: арифметика"),
            outcome_refs=["LO1.2"],
            difficulty=2,
        ),
        Assessment(
            ref="Q-002",
            kind="test_question",
            topic_ref="T2.1",
            module_ref="M2",
            stem="Какие методы дают обзор таблицы? Выберите все верные; верных может быть несколько.",
            qtype="multiple",
            options=[
                AssessmentOption(id="a", text="df.head()"),
                AssessmentOption(id="b", text="df.describe()"),
                AssessmentOption(id="c", text="df.drop_duplicates()"),
            ],
            answer_key=AnswerKey(
                correct=["a", "b"],
                explanation="head и describe показывают структуру и статистику",
            ),
            outcome_refs=["LO2.1"],
            difficulty=2,
        ),
        Assessment(
            ref="Q-003",
            kind="test_question",
            topic_ref="T2.1",
            module_ref="M2",
            stem="pandas — это библиотека Python для анализа данных.",
            qtype="truefalse",
            options=[
                AssessmentOption(id="t", text="Верно"),
                AssessmentOption(id="f", text="Неверно"),
            ],
            answer_key=AnswerKey(correct=["t"], explanation="Это библиотека анализа табличных данных"),
            outcome_refs=["LO2.1"],
            difficulty=1,
        ),
        Assessment(
            ref="Q-004",
            kind="test_question",
            topic_ref="T1.2",
            module_ref="M1",
            stem="Какой тип данных в Python называют «словарём»? Ответ одним словом.",
            qtype="short",
            options=[],
            answer_key=AnswerKey(correct=["dict"], explanation="Словарь — dict."),
            outcome_refs=["LO1.2"],
            difficulty=1,
        ),
        Assessment(
            ref="ST-T1.1-1",
            kind="seminar_task",
            topic_ref="T1.1",
            module_ref="M1",
            stem="Напишите программу, которая считает сумму чисел от 1 до N.",
            rubric=[
                Criterion(
                    criterion="Корректность работы",
                    max_points=5,
                    levels=["высокий", "средний", "низкий"],
                ),
                Criterion(criterion="Стиль кода", max_points=3),
            ],
            outcome_refs=["LO1.2"],
            difficulty=2,
        ),
        Assessment(
            ref="FP-M2",
            kind="final_project",
            module_ref="M2",
            stem="Проанализируйте предложенный набор данных и защитите выводы.",
            rubric=[Criterion(criterion="Полнота анализа", max_points=10, levels=["полный", "частичный"])],
            outcome_refs=["LO2.1"],
            difficulty=3,
        ),
    ]
    content = Content(
        module_programs=[
            ContentBlock(
                ref="MP-M1",
                kind="module_program",
                module_ref="M1",
                body={"text": "Рабочая программа модуля 1: синтаксис, функции, модули."},
            )
        ],
        lecture_plans=[
            ContentBlock(
                ref="LP-M1",
                kind="lecture_plan",
                module_ref="M1",
                body={
                    "lines": [
                        "План лекции: разбор примеров и демонстрация",
                        "Первая программа: печать и переменные",
                    ]
                },
            )
        ],
        slides=[
            ContentBlock(
                ref="SL-T1.1-1",
                kind="slides",
                module_ref="M1",
                topic_ref="T1.1",
                body={
                    "title": "Введение в Python",
                    "slides": [
                        {
                            "title": "Введение в Python",
                            "bullets": ["Что такое Python", "Переменные и типы данных", "Первая программа"],
                            "notes": "План лекции: разбор примеров и демонстрация",
                            "layout": "title_and_content",
                        },
                        {
                            "title": "Практика",
                            "bullets": ["Напишите программу hello world"],
                            "notes": "Раздать лист с заданием",
                            "layout": "title_and_content",
                        },
                    ],
                },
            )
        ],
        sections=[
            ContentBlock(
                ref="SEC-ANN",
                kind="annotation",
                body={"text": "Программа знакомит слушателей с анализом данных на Python."},
            ),
            ContentBlock(
                ref="SEC-3.1",
                kind="template_section",
                body={
                    "title": "Материально-техническое обеспечение",
                    "text": "Компьютерный класс с проектором.",
                },
            ),
        ],
        assessments=assessments,
        sources=[
            Source(
                ref="SRC-01",
                section="normative",
                citation="Федеральный закон от 29.12.2012 № 273-ФЗ «Об образовании в Российской Федерации»",
                status="verified",
                evidence={"registry": "normative_act"},
            ),
            Source(
                ref="SRC-02",
                section="main",
                citation="Иванов И.И. Python для анализа данных. — М.: ДМК Пресс, 2024",
                isbn="978-5-97060-000-0",
                status="unverified",
            ),
            Source(
                ref="SRC-03",
                section="software",
                citation="Python 3.12, библиотека pandas",
                url="https://www.python.org/",
                status="verified",
            ),
        ],
    )
    header = ProgramHeader(
        kind="dpp_pk",
        title="Анализ данных на Python",
        form="part_time",
        total_hours=36,
        final_attestation=FinalAttestation(form="защита итогового проекта", hours=2),
        document="удостоверение о повышении квалификации",
        legal_basis=[
            LegalBasis(
                ref="SRC-01",
                act="Федеральный закон от 29.12.2012 № 273-ФЗ «Об образовании в Российской Федерации»",
                status="verified",
            )
        ],
        organization="ООО «АЦР»",
        city="Москва",
        year=2026,
    )
    report = Report(
        passed=False,
        version=3,
        duration_ms=450,
        summary={"hours": {"ok": False, "checked": 3}, "sources": {"verified": 2, "unverified": 1}},
        issues=[
            ReportIssue(
                rule_code="V-SRC-04",
                severity="warning",
                entity_ref="SRC-02",
                message="Книга не найдена в доступных каталогах — помечена «не подтверждено»",
                fix_hint={"action": "replace_source"},
            )
        ],
        gaps=["Заказчик хочет уровень senior за 36 ч — реалистичен базовый уровень"],
        sample_findings=["Образец: итоговая строка СРС 174 ч ≠ сумме тем 168 ч"],
        assumptions=["Режим занятий не указан: принято 4 ч в день"],
    )
    return KitV1(
        program=header,
        profile=ProgramProfile(
            audience="Специалисты, работающие с данными",
            entry_level="Уверенное владение компьютером",
            schedule="3 недели, 4 ч в день",
        ),
        framework=framework,
        content=content,
        report=report,
        assumptions=[
            Assumption(
                text="Форма обучения принята очно-заочной",
                slot="form",
                accepted_value="part_time",
            )
        ],
    )


@pytest.fixture()
def kit() -> KitV1:
    return build_export_kit()


def _question_block(text: str, ref: str) -> str:
    """Вырезать блок вопроса из GIFT-файла (блоки разделены пустой строкой)."""
    start = text.index(f"::{ref} ")
    rest = text[start:]
    end = rest.find("\n\n")
    return rest if end == -1 else rest[:end]


def test_gift_escapes_special_characters(kit: KitV1) -> None:
    """~ = # { } : экранируются обратным слэшем в тексте вопроса и вариантах."""
    text = export_gift(kit)
    assert r"x \= 2 \~ 3 \# важно\: \{5\}" in text
    assert r"=print(x\=2)" in text
    assert ESCAPING_STEM not in text


def test_gift_escapes_explanation(kit: KitV1) -> None:
    """Пояснение из answer_key.explanation добавляется после # и тоже экранируется."""
    block = _question_block(export_gift(kit), "Q-001")
    assert r"#Верно\: арифметика" in block


def test_gift_categories_are_modules_in_order(kit: KitV1) -> None:
    """Категории — по одному модулю, в порядке каркаса, с номерами."""
    text = export_gift(kit)
    categories = [line for line in text.splitlines() if line.startswith("$CATEGORY:")]
    assert categories == [
        "$CATEGORY: $course$/М1 Основы Python",
        "$CATEGORY: $course$/М2 Обработка данных в pandas",
    ]


def test_gift_question_header_with_ref_and_outcome_tags(kit: KitV1) -> None:
    """Заголовок вопроса: ::ref [LO-tags]::."""
    text = export_gift(kit)
    assert "::Q-001 [LO1.2]::" in text
    assert "::Q-002 [LO2.1]::" in text
    assert "::Q-004 [LO1.2]::" in text


def test_gift_single_question_has_one_correct_marker(kit: KitV1) -> None:
    block = _question_block(export_gift(kit), "Q-001")
    assert block.count("\n=") == 1
    assert block.count("\n~") == 3


def test_gift_multiple_question_has_several_correct_markers(kit: KitV1) -> None:
    block = _question_block(export_gift(kit), "Q-002")
    assert block.count("\n=") == 2
    assert block.count("\n~") == 1


def test_gift_truefalse_uses_true_literal(kit: KitV1) -> None:
    block = _question_block(export_gift(kit), "Q-003")
    assert "{TRUE#" in block
    assert "FALSE" not in block


def test_gift_short_question_uses_answer_literal(kit: KitV1) -> None:
    block = _question_block(export_gift(kit), "Q-004")
    assert "{=dict" in block


def test_gift_excludes_seminar_and_project(kit: KitV1) -> None:
    """Задания (seminar_task, final_project) в GIFT не попадают."""
    text = export_gift(kit)
    assert "ST-T1.1-1" not in text
    assert "FP-M2" not in text


def test_gift_empty_kit_returns_comment() -> None:
    """Без тестовых вопросов — корректный файл с комментарием, без исключения."""
    kit = build_export_kit()
    kit.content.assessments = []
    text = export_gift(kit)
    assert "// Тестовых вопросов в комплекте нет" in text
    assert "$CATEGORY" not in text


def _only_assessments(kit: KitV1, *assessments: Assessment) -> KitV1:
    kit.content.assessments = list(assessments)
    return kit


def test_gift_truefalse_false_branch() -> None:
    """Верный ответ «Неверно» → {FALSE#…}."""
    kit = _only_assessments(
        build_export_kit(),
        Assessment(
            ref="Q-100",
            kind="test_question",
            module_ref="M2",
            stem="Два плюс два равно пяти.",
            qtype="truefalse",
            options=[
                AssessmentOption(id="t", text="Верно"),
                AssessmentOption(id="f", text="Неверно"),
            ],
            answer_key=AnswerKey(correct=["f"], explanation="2 + 2 = 4"),
            outcome_refs=["LO2.1"],
        ),
    )
    assert r"{FALSE#2 + 2 \= 4}" in export_gift(kit)


def test_gift_short_with_several_accepted_answers() -> None:
    kit = _only_assessments(
        build_export_kit(),
        Assessment(
            ref="Q-101",
            kind="test_question",
            module_ref="M1",
            stem="Тип данных для словаря?",
            qtype="short",
            options=[],
            answer_key=AnswerKey(correct=["dict", "dictionary"]),
            outcome_refs=["LO1.1"],
        ),
    )
    text = export_gift(kit)
    assert "{=dict =dictionary}" in text


def test_gift_matching_order_open_branches() -> None:
    """matching с парами → =элемент -> пара; order и open — открытые с комментариями."""
    kit = _only_assessments(
        build_export_kit(),
        Assessment(
            ref="Q-102",
            kind="test_question",
            module_ref="M1",
            stem="Сопоставьте типы данных.",
            qtype="matching",
            options=[
                AssessmentOption(id="1", text="list -> список"),
                AssessmentOption(id="2", text="dict -> словарь"),
            ],
            answer_key=AnswerKey(correct=[]),
            outcome_refs=["LO1.1"],
        ),
        Assessment(
            ref="Q-103",
            kind="test_question",
            module_ref="M1",
            stem="Упорядочьте шаги алгоритма.",
            qtype="order",
            options=[AssessmentOption(id="1", text="первый"), AssessmentOption(id="2", text="второй")],
            answer_key=AnswerKey(correct=["1", "2"]),
            outcome_refs=["LO1.1"],
        ),
        Assessment(
            ref="Q-104",
            kind="test_question",
            module_ref="M1",
            stem="Опишите подход к очистке данных.",
            qtype="open",
            options=[],
            answer_key=AnswerKey(correct=[], explanation="Оценивается полнота."),
            outcome_refs=["LO1.1"],
        ),
    )
    text = export_gift(kit)
    assert "=list -> список" in text
    assert "// верный порядок: первый -> второй" in text
    assert "::Q-104 [LO1.1]::Опишите подход к очистке данных.{}" in text
    assert "// Пояснение: Оценивается полнота." in text


def test_gift_matching_without_pairs_and_single_without_options() -> None:
    """Вырожденные данные → открытый вопрос с явным комментарием, без исключения."""
    kit = _only_assessments(
        build_export_kit(),
        Assessment(
            ref="Q-105",
            kind="test_question",
            module_ref="M1",
            stem="Соотнесите понятия.",
            qtype="matching",
            options=[AssessmentOption(id="1", text="без разделителя")],
            answer_key=AnswerKey(correct=[]),
            outcome_refs=["LO1.1"],
        ),
        Assessment(
            ref="Q-106",
            kind="test_question",
            module_ref="M1",
            stem="Выберите верное.",
            qtype="single",
            options=[],
            answer_key=AnswerKey(correct=["a"]),
            outcome_refs=["LO1.1"],
        ),
    )
    text = export_gift(kit)
    assert "// соответствие проверяется вручную" in text
    assert "// варианты ответа не заданы — вопрос проверяется вручную" in text


def test_gift_question_without_module_goes_to_unassigned_category() -> None:
    kit = _only_assessments(
        build_export_kit(),
        Assessment(
            ref="Q-107",
            kind="test_question",
            stem="Общий вопрос вне модулей.",
            qtype="truefalse",
            options=[
                AssessmentOption(id="t", text="Верно"),
                AssessmentOption(id="f", text="Неверно"),
            ],
            answer_key=AnswerKey(correct=["t"]),
            outcome_refs=["LO1.1"],
        ),
    )
    text = export_gift(kit)
    assert "$CATEGORY: $course$/Без модуля" in text
    assert "::Q-107 [LO1.1]::" in text
