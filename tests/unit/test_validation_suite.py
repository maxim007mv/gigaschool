"""Интеграционные тесты самопроверки (S10/S19): весь прогон run_validation.

Минимальный корректный KitV1 проходит (passed=True), испорченные копии
ловятся с нужными кодами правил. Здесь же — кейсы правил V-LNG-01, V-PLG-01,
V-REA-01, V-REQ-01 и V-SMP-01 (у них нет отдельных файлов тестов).
"""

from __future__ import annotations

from typing import Any

import pytest

from karkas.domain.kit import (
    AnswerKey,
    Assessment,
    AssessmentOption,
    Calendar,
    CalendarSession,
    Competency,
    Content,
    ContentBlock,
    Criterion,
    FinalAttestation,
    Framework,
    KitV1,
    Module,
    Outcome,
    ProgramConstraints,
    ProgramHeader,
    ProgramProfile,
    Source,
    Topic,
    Workload,
)
from karkas.domain.validators import ValidationContext, run_validation

# ---------------------------------------------------------------------------
# Минимальный корректный KitV1: ДОП 80 ч (78 ч тем + 2 ч ИА), школьники.
# Намеренно без единого замечания — эталон для «испорченных копий».
# ---------------------------------------------------------------------------


def _calendar_80h() -> Calendar:
    sessions = [CalendarSession(seq=i + 1, week=(i // 4) + 1, day=i + 1, topic_ref="T1.1", hours=4) for i in range(10)]
    sessions += [
        CalendarSession(seq=11 + i, week=(10 + i) // 4 + 1, day=11 + i, topic_ref="T1.2", hours=4) for i in range(9)
    ]
    sessions += [
        CalendarSession(seq=20, week=5, day=20, topic_ref="T1.2", hours=2),
        CalendarSession(seq=21, week=5, day=20, topic_ref=None, activity="exam", hours=2),
    ]
    return Calendar(weeks=5, days=20, days_per_week=4, max_hours_per_day=4, sessions=sessions)


def _question(ref: str, outcomes: list[str], topic_ref: str) -> Assessment:
    return Assessment(
        ref=ref,
        kind="test_question",
        topic_ref=topic_ref,
        stem=f"Вопрос {ref}: выберите верный вариант ответа по теме",
        qtype="single",
        options=[
            AssessmentOption(id="a", text="Верный ответ"),
            AssessmentOption(id="b", text="Неверный вариант 1"),
            AssessmentOption(id="c", text="Неверный вариант 2"),
            AssessmentOption(id="d", text="Неверный вариант 3"),
        ],
        answer_key=AnswerKey(correct=["a"], explanation="Пояснение"),
        outcome_refs=outcomes,
    )


def build_clean_kit() -> KitV1:
    header = ProgramHeader(
        kind="dop",
        title="Первые шаги в Python",
        form="full_time",
        total_hours=80,
        final_attestation=FinalAttestation(form="защита проекта", hours=2),
    )
    framework = Framework(
        goal="Научить школьников основам программирования на Python",
        tasks=["Освоить переменные и циклы", "Защитить итоговый проект"],
        competencies=[
            Competency(
                ref="C1",
                title="Основы программирования на Python",
                outcomes=[
                    Outcome(ref="LO1.1", type="knowledge", text="Знает синтаксис переменных и циклов"),
                    Outcome(ref="LO1.2", type="skill", text="Умеет писать простые программы с циклами"),
                    Outcome(ref="LO1.3", type="experience", text="Есть опыт решения учебных задач"),
                ],
            )
        ],
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы Python",
                topics=[
                    Topic(
                        ref="T1.1",
                        title="Переменные и типы данных",
                        workload=Workload(lecture=20, practice=20),
                        outcome_refs=["LO1.1", "LO1.2"],
                        complexity=1,
                    ),
                    Topic(
                        ref="T1.2",
                        title="Циклы и коллекции",
                        workload=Workload(lecture=18, practice=20),
                        outcome_refs=["LO1.2", "LO1.3"],
                        complexity=2,
                    ),
                ],
            )
        ],
        final_attestation=FinalAttestation(form="защита проекта", hours=2),
        calendar=_calendar_80h(),
    )
    content = Content(
        assessments=[
            _question("Q-001", ["LO1.1"], "T1.1"),
            _question("Q-002", ["LO1.1"], "T1.1"),
            _question("Q-003", ["LO1.2"], "T1.1"),
            _question("Q-004", ["LO1.2"], "T1.2"),
            _question("Q-005", ["LO1.3"], "T1.2"),
            _question("Q-006", ["LO1.3"], "T1.2"),
            Assessment(
                ref="FP-01",
                kind="final_project",
                module_ref="M1",
                stem="Соберите приложение по заданию и защитите его",
                rubric=[Criterion(criterion="Работоспособность", max_points=5, levels=["зачтено"])],
                outcome_refs=["LO1.3"],
            ),
        ],
        sources=[
            Source(
                ref="SRC-01",
                section="main",
                citation="Иванов И.И. Основы программирования на Python. — М.: Наука, 2024",
                status="verified",
                evidence={"isbn_checked": True},
            )
        ],
        module_programs=[
            ContentBlock(
                ref="MP-M1",
                kind="module_program",
                module_ref="M1",
                body={"hours": 78, "text": "Содержание"},
            ),
        ],
        sections=[
            ContentBlock(ref="ANN-1", kind="annotation", body={"text": "Курс для школьников 8–9 классов."}),
            ContentBlock(ref="SEC-3.2", kind="template_section", body={"text": "Методические материалы"}),
            ContentBlock(
                ref="SEC-3.3",
                kind="template_section",
                body={"text": "Материально-техническое обеспечение"},
            ),
        ],
    )
    return KitV1(
        program=header,
        profile=ProgramProfile(
            audience="школьники 8–9 классов",
            entry_level="без опыта программирования",
            glossary={"цикл": "повторяющиеся действия", "переменная": "ячейка для значения"},
            constraints=ProgramConstraints(min_practice_share_pct=50, max_hours_per_day=4, days_per_week=4),
        ),
        framework=framework,
        content=content,
    )


def run(kit: KitV1, **ctx_kwargs: Any) -> Any:
    return run_validation(ValidationContext(kit=kit, **ctx_kwargs))


def codes(report: Any) -> list[str]:
    return [i.rule_code for i in report.issues]


# ---------------------------------------------------------------------------
# Эталонный прогон и испорченные копии
# ---------------------------------------------------------------------------


def test_clean_kit_passes_without_issues():
    report = run(build_clean_kit())
    assert report.issues == []
    assert report.passed is True
    assert report.duration_ms >= 0
    assert report.summary["stage"] == "kit"
    for group in ("hours", "coverage", "sources", "template", "plagiarism"):
        assert group in report.summary
    assert report.summary["hours"]["ok"] is True
    assert "V-PLG-01" in report.summary["skipped"]
    assert "V-SMP-01" in report.summary["skipped"]


def test_corrupted_hours_fail():
    kit = build_clean_kit()
    kit.program.total_hours = 90
    report = run(kit)
    assert report.passed is False
    assert any(i.rule_code == "V-HRS-01" and i.severity == "error" for i in report.issues)


def test_corrupted_coverage_fails():
    kit = build_clean_kit()
    kit.content.assessments = []
    report = run(kit)
    assert report.passed is False
    assert "V-COV-02" in codes(report)


def test_corrupted_sources_fail():
    kit = build_clean_kit()
    kit.content.sources[0].status = "not_found"
    report = run(kit)
    assert report.passed is False
    assert "V-SRC-04" in codes(report)


def test_corrupted_english_text_warns():
    kit = build_clean_kit()
    kit.program.title = "Python course for school students"
    report = run(kit)
    assert "V-LNG-01" in codes(report)
    assert all(i.severity == "warning" for i in report.issues if i.rule_code == "V-LNG-01")


def test_deterministic_runs():
    first = run(build_clean_kit())
    second = run(build_clean_kit())
    assert codes(first) == codes(second)
    assert first.passed == second.passed


# ---------------------------------------------------------------------------
# V-LNG-01: язык и глоссарий для школьников
# ---------------------------------------------------------------------------


def test_lng_01_school_audience_without_glossary_warns():
    kit = build_clean_kit()
    kit.profile.glossary = {}
    issues = [i for i in run(kit).issues if i.rule_code == "V-LNG-01"]
    assert len(issues) == 1 and issues[0].severity == "warning"
    assert "глоссарий" in issues[0].message


def test_lng_01_adult_audience_does_not_require_glossary():
    kit = build_clean_kit()
    kit.profile.audience = "специалисты предприятий"
    kit.profile.glossary = {}
    assert "V-LNG-01" not in codes(run(kit))


def test_lng_01_code_and_commands_exempt():
    kit = build_clean_kit()
    from karkas.domain.kit import ContentBlock

    kit.content.sections.append(
        ContentBlock(
            ref="SEC-CODE",
            kind="annotation",
            body={
                "code": "docker run -d -p 8080:80 --name web nginx:latest",
                "commands": "$ git clone https://github.com/repo && cd repo && make build",
                "python_code": "import os\ndef get_path():\n    return os.environ.get('PATH')",
            },
        )
    )
    assert "V-LNG-01" not in codes(run(kit))


def test_lng_01_code_options_and_expressions_exempt():
    """Варианты-код в тестах не должны считаться нерусским текстом."""
    kit = build_clean_kit()
    kit.content.assessments[0].options = [
        AssessmentOption(id="a", text="print()"),
        AssessmentOption(id="b", text="my_var"),
        AssessmentOption(id="c", text="x > 5 and x < 10"),
        AssessmentOption(id="d", text="fruits = {'fruit1': 'apple'}; print(fruits['fruit1'])"),
    ]
    assert "V-LNG-01" not in codes(run(kit))


# ---------------------------------------------------------------------------
# V-PLG-01: заимствования из референсов
# ---------------------------------------------------------------------------


def test_plg_01_copied_paragraph_is_error():
    kit = build_clean_kit()
    reference = "На этом занятии мы изучаем переменные и циклы языка Python на простых примерах"
    kit.framework.modules[0].topics[0].summary = reference
    report = run(kit, reference_texts=[reference])
    issues = [i for i in report.issues if i.rule_code == "V-PLG-01"]
    assert len(issues) == 1 and issues[0].severity == "error"
    assert issues[0].entity_ref == "T1.1"
    assert report.summary["plagiarism"]["max_overlap"] >= 0.9


def test_plg_01_paraphrase_ok():
    kit = build_clean_kit()
    kit.framework.modules[0].topics[0].summary = "Разбираем переменные и циклы на примерах задач"
    report = run(kit, reference_texts=["На занятии изучаются множества, словари и генераторы выражений"])
    assert "V-PLG-01" not in codes(report)


def test_plg_01_skipped_without_references():
    report = run(build_clean_kit())
    assert report.summary["plagiarism"]["max_overlap"] == 0.0
    assert "V-PLG-01" in report.summary["skipped"]


# ---------------------------------------------------------------------------
# V-REA-01: реалистичность (границы 72 ч и 2 ч на результат)
# ---------------------------------------------------------------------------


def rea_kit(total: int, outcome_types: list[str]) -> KitV1:
    outcomes = [
        Outcome(ref=f"LO1.{i + 1}", type=kind, text=f"Результат {i + 1}") for i, kind in enumerate(outcome_types)
    ]
    header = ProgramHeader(
        kind="dop",
        title="Проверка реалистичности",
        form="full_time",
        total_hours=total,
        final_attestation=FinalAttestation(form="зачёт", hours=2),
    )
    framework = Framework(
        goal="Цель",
        competencies=[Competency(ref="C1", title="Компетенция", outcomes=outcomes)],
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Модуль",
                topics=[
                    Topic(
                        ref="T1.1",
                        title="Тема",
                        workload=Workload(lecture=(total - 2) // 2, practice=(total - 2) - (total - 2) // 2),
                        outcome_refs=[outcomes[0].ref],
                    )
                ],
            )
        ],
        final_attestation=FinalAttestation(form="зачёт", hours=2),
    )
    return KitV1(program=header, framework=framework)


def test_rea_01_experience_at_72h_warns():
    report = run(rea_kit(72, ["experience"]))
    issues = [i for i in report.issues if i.rule_code == "V-REA-01"]
    assert any("нереалистично" in i.message for i in issues)


def test_rea_01_experience_above_72h_ok():
    report = run(rea_kit(73, ["experience"]))
    assert all(i.rule_code != "V-REA-01" for i in report.issues)


def test_rea_01_many_outcomes_warns():
    report = run(rea_kit(16, ["knowledge"] * 9))  # 9 > 16/2
    issues = [i for i in report.issues if i.rule_code == "V-REA-01"]
    assert any("Результатов обучения 9" in i.message for i in issues)


def test_rea_01_outcomes_at_boundary_ok():
    report = run(rea_kit(16, ["knowledge"] * 8))  # 8 == 16/2
    assert all(i.rule_code != "V-REA-01" for i in report.issues)


# ---------------------------------------------------------------------------
# V-REQ-01: явные пожелания брифа
# ---------------------------------------------------------------------------


def test_req_01_zero_final_attestation_is_error():
    kit = build_clean_kit()
    kit.framework.final_attestation.hours = 0
    report = run(kit)
    assert any(i.rule_code == "V-REQ-01" and i.severity == "error" for i in report.issues)


def test_req_01_requested_slides_missing_is_error():
    kit = build_clean_kit()
    kit.profile.notes = "Сгенерируйте слайды для модуля M1"
    report = run(kit)
    issues = [i for i in report.issues if i.rule_code == "V-REQ-01"]
    assert len(issues) == 1 and issues[0].severity == "error"
    assert issues[0].entity_ref == "M1"


def test_req_01_requested_slides_present_ok():
    kit = build_clean_kit()
    kit.profile.notes = "Сгенерируйте слайды для модуля M1"
    kit.content.slides = [ContentBlock(ref="SL-T1.1", kind="slides", module_ref="M1", topic_ref="T1.1")]
    assert all(i.rule_code != "V-REQ-01" for i in run(kit).issues)


def test_req_01_slides_not_requested_ok():
    assert all(i.rule_code != "V-REQ-01" for i in run(build_clean_kit()).issues)


def test_req_01_slides_by_session_numbers():
    kit = build_clean_kit()
    kit.profile.notes = "Сгенерируйте слайды для занятий 1 и 2"
    report = run(kit)
    issues = [i for i in report.issues if i.rule_code == "V-REQ-01"]
    assert len(issues) == 1 and issues[0].severity == "error"
    assert issues[0].entity_ref == "T1.1"  # занятия 1 и 2 — это тема T1.1
    kit.content.slides = [ContentBlock(ref="SL-T1.1", kind="slides", topic_ref="T1.1")]
    assert all(i.rule_code != "V-REQ-01" for i in run(kit).issues)


# ---------------------------------------------------------------------------
# V-SMP-01: расхождения образца (Д5 §6.7)
# ---------------------------------------------------------------------------


def test_smp_01_mismatch_warns_and_adds_findings():
    report = run(build_clean_kit(), declared_totals={"self_study": 174, "total": 248})
    issues = [i for i in report.issues if i.rule_code == "V-SMP-01"]
    assert len(issues) == 2
    assert all(i.severity == "warning" for i in issues)
    assert len(report.sample_findings) == 2
    assert all(f.startswith("Образец:") and "не перенесено" in f for f in report.sample_findings)
    assert any("174" in f and "0" in f for f in report.sample_findings)


def test_smp_01_row_mismatch_warns():
    report = run(build_clean_kit(), declared_totals={"rows": {"T1.1": {"practice": 12, "total": 40}}})
    findings = report.sample_findings
    assert any("T1.1" in f and "ПР 12" in f for f in findings)


def test_smp_01_matching_totals_ok():
    report = run(build_clean_kit(), declared_totals={"self_study": 0, "total": 80})
    assert [i for i in report.issues if i.rule_code == "V-SMP-01"] == []
    assert report.sample_findings == []


def test_smp_01_skipped_without_declared_totals():
    report = run(build_clean_kit())
    assert "V-SMP-01" in report.summary["skipped"]


# ---------------------------------------------------------------------------
# Прочее: детерминизм вспомогательных групп
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("group", ["hours", "coverage", "sources", "template", "duplicates", "services"])
def test_summary_has_ok_flags(group):
    report = run(build_clean_kit())
    assert "ok" in report.summary[group]
