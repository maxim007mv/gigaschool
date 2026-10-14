"""Тесты правил группы «Часы» и «График» (V-HRS-01..09, V-CAL-01).

Для каждого правила — минимум один кейс «нарушение → issue» и «норма → нет issue».
"""

from __future__ import annotations

from typing import Any

import pytest

from karkas.domain.kit import (
    Calendar,
    CalendarSession,
    Competency,
    Content,
    ContentBlock,
    FinalAttestation,
    Framework,
    KitV1,
    Module,
    Outcome,
    ProgramConstraints,
    ProgramHeader,
    ProgramProfile,
    Topic,
    Workload,
)
from karkas.domain.validators import ValidationContext, run_validation


def topic(
    ref: str,
    *,
    lecture: int = 0,
    practice: int = 0,
    lab: int = 0,
    self_study: int = 0,
    current_control: int = 0,
    distance: int = 0,
    complexity: int = 1,
) -> Topic:
    return Topic(
        ref=ref,
        title=f"Тема {ref}",
        workload=Workload(
            lecture=lecture,
            practice=practice,
            lab=lab,
            self_study=self_study,
            current_control=current_control,
            distance=distance,
        ),
        outcome_refs=["LO1.1"],
        complexity=complexity,
    )


def calendar_16h() -> Calendar:
    """8 занятий по 2 ч за 4 недели (эталон ТК-1): T1.1 ×4, T1.2 ×3, ИА."""
    sessions = [
        CalendarSession(seq=i + 1, week=(i // 4) + 1, day=i + 1, topic_ref="T1.1", hours=2)
        for i in range(4)
    ]
    sessions += [
        CalendarSession(seq=5, week=2, day=5, topic_ref="T1.2", hours=2),
        CalendarSession(seq=6, week=2, day=6, topic_ref="T1.2", hours=2),
        CalendarSession(seq=7, week=2, day=7, topic_ref="T1.2", hours=2),
        CalendarSession(seq=8, week=2, day=8, topic_ref=None, activity="exam", hours=2),
    ]
    return Calendar(weeks=2, days=8, days_per_week=4, max_hours_per_day=4, sessions=sessions)


def build_kit(
    *,
    total_hours: int = 16,
    final_att_hours: int = 2,
    modules: list[Module] | None = None,
    constraints: ProgramConstraints | None = None,
    form: str = "full_time",
    calendar: Calendar | None = None,
    content: Content | None = None,
) -> KitV1:
    """Согласованный каркас 16 ч (14 ч тем + 2 ч ИА) с плавающими частями."""
    if modules is None:
        modules = [
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[topic("T1.1", lecture=4, practice=4), topic("T1.2", lecture=2, practice=4)],
            )
        ]
    header = ProgramHeader(
        kind="dop",
        title="Первые шаги в Python",
        form=form,
        total_hours=total_hours,
        final_attestation=FinalAttestation(form="защита проекта", hours=final_att_hours),
    )
    framework = Framework(
        goal="Научить основам программирования",
        competencies=[
            Competency(
                ref="C1",
                title="Основы программирования",
                outcomes=[Outcome(ref="LO1.1", type="knowledge", text="Знает основы")],
            )
        ],
        modules=modules,
        final_attestation=FinalAttestation(form="защита проекта", hours=final_att_hours),
        calendar=calendar if calendar is not None else calendar_16h(),
    )
    profile = ProgramProfile(entry_level="базовый", constraints=constraints or ProgramConstraints())
    return KitV1(program=header, profile=profile, framework=framework, content=content or Content())


def codes(kit: KitV1, **ctx_kwargs: Any) -> list[str]:
    report = run_validation(ValidationContext(kit=kit, **ctx_kwargs))
    return [i.rule_code for i in report.issues]


def issues_of(kit: KitV1, code: str, **ctx_kwargs: Any) -> list:
    report = run_validation(ValidationContext(kit=kit, **ctx_kwargs))
    return [i for i in report.issues if i.rule_code == code]


# ---------------------------------------------------------------------------
# V-HRS-01: Σ тем + ИА = объём
# ---------------------------------------------------------------------------


def test_hrs_01_ok():
    assert "V-HRS-01" not in codes(build_kit())


def test_hrs_01_mismatch_is_error():
    issues = issues_of(build_kit(total_hours=18), "V-HRS-01")
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "16 ч" in issues[0].message and "18 ч" in issues[0].message


# ---------------------------------------------------------------------------
# V-HRS-02/03: часы у темы и модуля
# ---------------------------------------------------------------------------


def test_hrs_02_topic_without_hours():
    empty = topic("T1.2")
    kit = build_kit(
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[topic("T1.1", lecture=4, practice=4), empty],
            )
        ]
    )
    issues = issues_of(kit, "V-HRS-02")
    assert [i.entity_ref for i in issues] == ["T1.2"]
    assert issues[0].severity == "error"


def test_hrs_02_ok():
    assert "V-HRS-02" not in codes(build_kit())


def test_hrs_03_module_without_topics():
    kit = build_kit(modules=[Module(ref="M1", number=1, title="Основы", topics=[])])
    issues = issues_of(kit, "V-HRS-03")
    assert len(issues) == 1 and issues[0].entity_ref == "M1"
    assert issues[0].severity == "error"


def test_hrs_03_ok():
    assert "V-HRS-03" not in codes(build_kit())


# ---------------------------------------------------------------------------
# V-HRS-04: стажировка без аудиторных занятий
# ---------------------------------------------------------------------------


def test_hrs_04_internship_with_contact_is_error():
    kit = build_kit(constraints=ProgramConstraints(self_study_only=True))
    issues = issues_of(kit, "V-HRS-04")
    assert issues and all(i.severity == "error" for i in issues)
    assert {i.entity_ref for i in issues} == {"T1.1", "T1.2"}


def test_hrs_04_internship_form_is_error():
    kit = build_kit(form="internship")
    assert issues_of(kit, "V-HRS-04")


def test_hrs_04_self_study_only_ok():
    kit = build_kit(
        constraints=ProgramConstraints(self_study_only=True),
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Стажировка",
                topics=[topic("T1.1", self_study=8), topic("T1.2", self_study=6)],
            )
        ],
    )
    assert "V-HRS-04" not in codes(kit)


# ---------------------------------------------------------------------------
# V-HRS-05: минимальная доля практики
# ---------------------------------------------------------------------------


def test_hrs_05_ok_on_threshold():
    kit = build_kit(constraints=ProgramConstraints(min_practice_share_pct=50))  # ПР 8 = ceil(0.5·16)
    assert "V-HRS-05" not in codes(kit)


def test_hrs_05_below_threshold_is_error():
    kit = build_kit(constraints=ProgramConstraints(min_practice_share_pct=60))
    issues = issues_of(kit, "V-HRS-05")
    assert len(issues) == 1 and issues[0].severity == "error"
    assert "60" in issues[0].message


# ---------------------------------------------------------------------------
# V-HRS-06: ЛК+ПР+ЛБ+СРС+контроль = «Всего» по строке (итог из образца)
# ---------------------------------------------------------------------------


def test_hrs_06_declared_row_mismatch_is_error():
    kit = build_kit()
    issues = issues_of(kit, "V-HRS-06", declared_totals={"rows": {"T1.1": 9}})
    assert [i.entity_ref for i in issues] == ["T1.1"]
    assert issues[0].severity == "error"


def test_hrs_06_matching_row_ok():
    kit = build_kit()
    assert "V-HRS-06" not in codes(kit, declared_totals={"rows": {"T1.1": 8, "T1.2": {"total": 6}}})


# ---------------------------------------------------------------------------
# V-HRS-07: Σ тем = часы модуля (заявленные итоги)
# ---------------------------------------------------------------------------


def test_hrs_07_module_program_hours_mismatch_is_error():
    content = Content(
        module_programs=[
            ContentBlock(ref="MP-M1", kind="module_program", module_ref="M1", body={"hours": 20})
        ]
    )
    kit = build_kit(content=content, modules=None)
    issues = issues_of(kit, "V-HRS-07")
    assert [i.entity_ref for i in issues] == ["M1"]
    assert issues[0].severity == "error"


def test_hrs_07_declared_modules_mismatch_is_error():
    issues = issues_of(build_kit(), "V-HRS-07", declared_totals={"modules": {"M1": 20}})
    assert [i.entity_ref for i in issues] == ["M1"]


def test_hrs_07_matching_declared_hours_ok():
    content = Content(
        module_programs=[
            ContentBlock(ref="MP-M1", kind="module_program", module_ref="M1", body={"hours": 14})
        ]
    )
    kit = build_kit(content=content)
    assert "V-HRS-07" not in codes(kit, declared_totals={"modules": {"M1": 14}})


# ---------------------------------------------------------------------------
# V-HRS-08: кратность часов занятия
# ---------------------------------------------------------------------------


def test_hrs_08_ok_when_multiple():
    kit = build_kit(constraints=ProgramConstraints(unit_hours=2))  # 8 и 6 кратны 2
    assert "V-HRS-08" not in codes(kit)


def test_hrs_08_not_multiple_is_error():
    kit = build_kit(
        constraints=ProgramConstraints(unit_hours=2),
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[topic("T1.1", lecture=4, practice=4), topic("T1.2", lecture=1, practice=4)],
            )
        ],
    )
    issues = issues_of(kit, "V-HRS-08")
    assert [i.entity_ref for i in issues] == ["T1.2"]
    assert issues[0].severity == "error"


# ---------------------------------------------------------------------------
# V-HRS-09: ДОТ и очные часы разделены явно
# ---------------------------------------------------------------------------


def test_hrs_09_distance_not_allocated_is_error():
    kit = build_kit(constraints=ProgramConstraints(distance_share_pct=20))
    issues = issues_of(kit, "V-HRS-09")
    assert len(issues) == 1 and issues[0].severity == "error"
    assert "ДОТ" in issues[0].message


def test_hrs_09_distance_allocated_ok():
    kit = build_kit(
        constraints=ProgramConstraints(distance_share_pct=20),
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[
                    topic("T1.1", lecture=4, practice=4, distance=4),
                    topic("T1.2", lecture=2, practice=4),
                ],
            )
        ],
    )
    assert "V-HRS-09" not in codes(kit)


def test_hrs_09_distance_more_than_contact_is_error():
    kit = build_kit(
        constraints=ProgramConstraints(distance_share_pct=20),
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[
                    topic("T1.1", lecture=4, practice=4, distance=9),
                    topic("T1.2", lecture=2, practice=4),
                ],
            )
        ],
    )
    issues = issues_of(kit, "V-HRS-09")
    assert [i.entity_ref for i in issues] == ["T1.1"]


# ---------------------------------------------------------------------------
# V-CAL-01: календарный график
# ---------------------------------------------------------------------------


def test_cal_01_ok():
    assert "V-CAL-01" not in codes(build_kit())


def test_cal_01_skipped_without_calendar():
    kit = build_kit()
    kit.framework.calendar = None
    report = run_validation(ValidationContext(kit=kit))
    assert "V-CAL-01" not in [i.rule_code for i in report.issues]
    assert "V-CAL-01" in report.summary["skipped"]


def test_cal_01_empty_sessions_is_error():
    kit = build_kit(calendar=Calendar(weeks=2, days=8, days_per_week=4, max_hours_per_day=4))
    assert "V-CAL-01" in codes(kit)


def test_cal_01_unknown_topic_is_error():
    calendar = calendar_16h()
    calendar.sessions[0].topic_ref = "T9.9"
    kit = build_kit(calendar=calendar)
    issues = issues_of(kit, "V-CAL-01")
    assert any(i.entity_ref == "T9.9" for i in issues)


def test_cal_01_hours_over_day_limit_is_error():
    calendar = calendar_16h()
    calendar.sessions.append(CalendarSession(seq=9, week=2, day=8, topic_ref="T1.1", hours=3))
    kit = build_kit(calendar=calendar)
    issues = issues_of(kit, "V-CAL-01")
    assert any("больше допустимых" in i.message for i in issues)


def test_cal_01_calendar_max_over_constraints_is_error():
    calendar = calendar_16h()
    calendar.max_hours_per_day = 6
    kit = build_kit(calendar=calendar, constraints=ProgramConstraints(max_hours_per_day=4))
    issues = issues_of(kit, "V-CAL-01")
    assert any("ограничениях запроса" in i.message for i in issues)


def test_cal_01_final_attestation_hours_mismatch_is_error():
    calendar = calendar_16h()
    calendar.sessions[-1].hours = 1
    kit = build_kit(calendar=calendar)
    issues = issues_of(kit, "V-CAL-01")
    assert any("Итоговая аттестация" in i.message for i in issues)


def test_cal_01_days_mismatch_is_error():
    calendar = calendar_16h()
    calendar.days = 9
    kit = build_kit(calendar=calendar)
    issues = issues_of(kit, "V-CAL-01")
    assert any("учебных дней" in i.message for i in issues)


def test_cal_01_weeks_not_enough_is_error():
    calendar = calendar_16h()
    calendar.weeks = 1
    kit = build_kit(calendar=calendar)
    issues = issues_of(kit, "V-CAL-01")
    assert any("недель" in i.message for i in issues)


def test_cal_01_sessions_total_mismatch_is_error():
    calendar = calendar_16h()
    calendar.sessions[-1].hours = 1  # ИА 1 ч: не сходится ни с грандом, ни с ИА
    calendar.days = 8
    kit = build_kit(calendar=calendar)
    issues = issues_of(kit, "V-CAL-01")
    assert any("графике" in i.message for i in issues)
