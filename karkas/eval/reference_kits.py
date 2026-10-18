"""Эталонные KitV1 для открытых ТК-1…ТК-5 (детерминированные фикстуры eval, без LLM)."""

from __future__ import annotations

from typing import Callable

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
    LaborFunctionRef,
    LegalBasis,
    Module,
    Outcome,
    ProfStandardRef,
    ProgramConstraints,
    ProgramHeader,
    ProgramProfile,
    Source,
    Topic,
    Workload,
)


def _question(ref: str, outcomes: list[str], topic_ref: str) -> Assessment:
    return Assessment(
        ref=ref,
        kind="test_question",
        topic_ref=topic_ref,
        stem=f"Вопрос {ref}",
        qtype="single",
        options=[
            AssessmentOption(id="a", text="Верно"),
            AssessmentOption(id="b", text="Неверно"),
        ],
        answer_key=AnswerKey(correct=["a"], explanation="Пояснение"),
        outcome_refs=outcomes,
    )


def _dop_content(module_ref: str = "M1") -> Content:
    return Content(
        assessments=[
            _question("Q-001", ["LO1.1"], "T1.1"),
            _question("Q-002", ["LO1.1"], "T1.1"),
            _question("Q-003", ["LO1.2"], "T1.2"),
            _question("Q-004", ["LO1.2"], "T1.2"),
            Assessment(
                ref="FP-01",
                kind="final_project",
                module_ref=module_ref,
                stem="Защита учебного проекта",
                rubric=[Criterion(criterion="Работоспособность", max_points=5, levels=["зачтено"])],
                outcome_refs=["LO1.2"],
            ),
        ],
        sources=[
            Source(
                ref="SRC-01",
                section="main",
                citation="Учебник по Python для школьников",
                status="verified",
                evidence={"isbn_checked": True},
            )
        ],
        module_programs=[
            ContentBlock(
                ref="MP-M1",
                kind="module_program",
                module_ref=module_ref,
                body={"hours": 14, "text": "Содержание модуля"},
            ),
        ],
        sections=[
            ContentBlock(ref="ANN-1", kind="annotation", body={"text": "Курс для школьников."}),
            ContentBlock(ref="SEC-3.2", kind="template_section", body={"text": "Методические материалы"}),
            ContentBlock(ref="SEC-3.3", kind="template_section", body={"text": "МТО"}),
        ],
    )


def build_tk1_kit() -> KitV1:
    sessions = [
        CalendarSession(seq=i + 1, week=(i // 2) + 1, day=i + 1, topic_ref="T1.1" if i < 4 else "T1.2", hours=2)
        for i in range(8)
    ]
    return KitV1(
        program=ProgramHeader(
            kind="dop",
            title="Первые шаги в Python",
            form="full_time",
            total_hours=16,
            final_attestation=FinalAttestation(form="защита проекта", hours=2),
        ),
        profile=ProgramProfile(
            audience="школьники 8–9 классов",
            entry_level="без опыта программирования",
            constraints=ProgramConstraints(min_practice_share_pct=50, max_hours_per_day=2, days_per_week=2),
        ),
        framework=Framework(
            goal="Освоить основы Python",
            competencies=[
                Competency(
                    ref="C1",
                    title="Основы программирования",
                    outcomes=[
                        Outcome(ref="LO1.1", type="knowledge", text="Знает переменные и условия"),
                        Outcome(ref="LO1.2", type="skill", text="Умеет писать простые программы"),
                    ],
                )
            ],
            modules=[
                Module(
                    ref="M1",
                    number=1,
                    title="Python для начинающих",
                    topics=[
                        Topic(
                            ref="T1.1",
                            title="Переменные и условия",
                            workload=Workload(lecture=2, practice=5),
                            outcome_refs=["LO1.1"],
                        ),
                        Topic(
                            ref="T1.2",
                            title="Циклы и проект",
                            workload=Workload(lecture=2, practice=5),
                            outcome_refs=["LO1.2"],
                        ),
                    ],
                )
            ],
            final_attestation=FinalAttestation(form="защита проекта", hours=2),
            calendar=Calendar(weeks=4, days=8, days_per_week=2, max_hours_per_day=2, sessions=sessions),
        ),
        content=_dop_content(),
    )


def _pk_competency() -> Competency:
    return Competency(
        ref="C1",
        title="Применение ИИ в педагогической деятельности",
        prof_standard=ProfStandardRef(code="01.001", title="Педагог", status="active"),
        labor_functions=[LaborFunctionRef(code="A/01.1", title="Обучение и воспитание")],
        outcomes=[
            Outcome(ref="LO1.1", type="skill", text="Умеет готовить материалы с помощью ИИ"),
            Outcome(ref="LO1.2", type="knowledge", text="Знает риски и этику использования ИИ"),
        ],
    )


def _pk_content(topics: list[str]) -> Content:
    assessments = [
        _question("Q-001", ["LO1.1"], topics[0]),
        _question("Q-002", ["LO1.2"], topics[1]),
        Assessment(
            ref="PF-01",
            kind="portfolio_item",
            stem="Портфолио из трёх материалов",
            rubric=[Criterion(criterion="Качество", max_points=5, levels=["зачтено"])],
            outcome_refs=["LO1.1"],
        ),
    ]
    return Content(
        assessments=assessments,
        sources=[
            Source(ref="SRC-01", section="software", citation="GigaChat", status="verified"),
        ],
        module_programs=[
            ContentBlock(ref="MP-M1", kind="module_program", module_ref="M1", body={"text": "Содержание"}),
        ],
        sections=[ContentBlock(ref="ANN-1", kind="annotation", body={"text": "Для учителей Ингушетии."})],
    )


def build_tk2_kit() -> KitV1:
    return KitV1(
        program=ProgramHeader(
            kind="dpp_pk",
            title="Искусственный интеллект в работе учителя",
            form="part_time",
            total_hours=36,
            document="удостоверение о повышении квалификации",
            final_attestation=FinalAttestation(form="зачёт по портфолио", hours=2),
            legal_basis=[LegalBasis(ref="LB-01", act="Приказ Минобрнауки России от 24.03.2025 № 266", status="verified")],
        ),
        profile=ProgramProfile(audience="учителя школ", entry_level="без навыков программирования"),
        framework=Framework(
            goal="Использовать ИИ в работе учителя безопасно",
            competencies=[_pk_competency()],
            modules=[
                Module(
                    ref="M1",
                    number=1,
                    title="ИИ для учителя",
                    topics=[
                        Topic(
                            ref="T1.1",
                            title="ИИ для планов уроков",
                            workload=Workload(lecture=9, practice=8, distance=8),
                            outcome_refs=["LO1.1"],
                        ),
                        Topic(
                            ref="T1.2",
                            title="Этика, риски и защита персональных данных учеников",
                            workload=Workload(lecture=9, practice=8, distance=8),
                            outcome_refs=["LO1.2"],
                        ),
                    ],
                )
            ],
            final_attestation=FinalAttestation(form="зачёт по портфолио", hours=2),
            calendar=Calendar(weeks=6, days=18, days_per_week=3, max_hours_per_day=4, sessions=[]),
        ),
        content=_pk_content(["T1.1", "T1.2"]),
    )


def build_tk3_kit() -> KitV1:
    mods = [
        ("M1", "Основы Python для аналитика", "T1.1", "Введение в Python"),
        ("M2", "Pandas и визуализация", "T2.1", "Pandas и визуализация данных"),
        ("M3", "SQL для выгрузки данных", "T3.1", "SQL для банковских выгрузок"),
        ("M4", "Основы статистики", "T4.1", "Статистика оттока клиентов банка и задолженности"),
    ]
    topics: list[Topic] = []
    modules: list[Module] = []
    hour_pairs = [(18, 0), (18, 0), (17, 0), (17, 0)]
    for idx, ((mref, mtitle, tref, ttitle), (lec, prac)) in enumerate(zip(mods, hour_pairs, strict=True), start=1):
        topic = Topic(
            ref=tref,
            title=ttitle,
            workload=Workload(lecture=lec, practice=prac),
            outcome_refs=["LO1.1"],
        )
        modules.append(Module(ref=mref, number=idx, title=mtitle, topics=[topic]))
    return KitV1(
        program=ProgramHeader(
            kind="dpp_pk",
            title="Анализ данных на Python",
            form="part_time",
            total_hours=72,
            document="удостоверение о повышении квалификации",
            final_attestation=FinalAttestation(form="защита проекта", hours=2),
            legal_basis=[LegalBasis(ref="LB-01", act="Приказ Минобрнауки России от 24.03.2025 № 266", status="verified")],
        ),
        profile=ProgramProfile(audience="сотрудники банков", entry_level="опыт работы в Excel"),
        framework=Framework(
            goal="Анализ банковских данных на Python",
            competencies=[
                Competency(
                    ref="C1",
                    title="Анализ данных",
                    prof_standard=ProfStandardRef(code="06.015", title="Специалист по информационным системам"),
                    labor_functions=[LaborFunctionRef(code="C/14.6", title="Работа с данными")],
                    outcomes=[Outcome(ref="LO1.1", type="skill", text="Анализирует отток клиентов банка")],
                )
            ],
            modules=modules,
            final_attestation=FinalAttestation(form="защита проекта на обезличенных банковских данных", hours=2),
            calendar=Calendar(weeks=4, days=20, days_per_week=5, max_hours_per_day=4, sessions=[]),
        ),
        content=_pk_content(["T1.1", "T2.1"]),
    )


def build_tk4_kit() -> KitV1:
    base = build_tk3_kit()
    return base.model_copy(
        update={
            "program": base.program.model_copy(
                update={"title": "Кибербезопасность для студентов колледжа"}
            ),
            "framework": base.framework.model_copy(
                update={
                    "modules": [
                        base.framework.modules[0].model_copy(
                            update={
                                "topics": [
                                    base.framework.modules[0].topics[0].model_copy(
                                        update={"title": "Основы информационной безопасности"}
                                    ),
                                    *base.framework.modules[0].topics[1:],
                                ]
                            }
                        ),
                        *base.framework.modules[1:],
                    ]
                }
            ),
        }
    )


def build_tk5_kit() -> KitV1:
    section_titles = [
        ("M1", "Linux и сети"),
        ("M2", "Контейнеризация"),
        ("M3", "CI/CD"),
        ("M4", "Мониторинг"),
        ("M5", "Инфраструктура как код"),
    ]
    hours_per = [50, 50, 52, 52, 50]
    modules: list[Module] = []
    assessments: list[Assessment] = []
    for idx, ((mref, title), hrs) in enumerate(zip(section_titles, hours_per, strict=True), start=1):
        tref = f"T{idx}.1"
        modules.append(
            Module(
                ref=mref,
                number=idx,
                title=title,
                topics=[
                    Topic(
                        ref=tref,
                        title=title,
                        workload=Workload(self_study=hrs),
                        outcome_refs=["LO1.1"],
                    )
                ],
            )
        )
        assessments.append(
            Assessment(
                ref=f"IV-{idx}",
                kind="interview_question",
                topic_ref=tref,
                stem=f"Вопросы собеседования по разделу {title}",
                outcome_refs=["LO1.1"],
            )
        )
    return KitV1(
        program=ProgramHeader(
            kind="dpp_pk",
            title="DevOps-инженер от Linux до CI/CD",
            form="internship",
            total_hours=256,
            document="удостоверение о повышении квалификации",
            final_attestation=FinalAttestation(form="защита отчёта о стажировке", hours=2),
            legal_basis=[LegalBasis(ref="LB-01", act="Приказ Минобрнауки России от 24.03.2025 № 266", status="verified")],
        ),
        profile=ProgramProfile(audience="стажёры ИТ-компаний", entry_level="базовый Linux"),
        framework=Framework(
            goal="Подготовка DevOps-инженера",
            competencies=[
                Competency(
                    ref="C1",
                    title="Администрирование и DevOps",
                    prof_standard=ProfStandardRef(code="06.015", title="Специалист по информационным системам"),
                    labor_functions=[LaborFunctionRef(code="C/14.6", title="Сопровождение ИС")],
                    outcomes=[Outcome(ref="LO1.1", type="skill", text="Настраивает CI/CD и мониторинг")],
                )
            ],
            modules=modules,
            final_attestation=FinalAttestation(form="защита отчёта о стажировке", hours=2),
            calendar=Calendar(weeks=9, days=64, days_per_week=5, max_hours_per_day=4, sessions=[]),
        ),
        content=Content(
            assessments=assessments,
            module_programs=[
                ContentBlock(ref=f"MP-{m.ref}", kind="module_program", module_ref=m.ref, body={"text": m.title})
                for m in modules
            ],
            sections=[ContentBlock(ref="ANN-1", kind="annotation", body={"text": "Стажировка DevOps."})],
            sources=[Source(ref="SRC-01", section="internet", citation="Документация Linux", status="verified")],
        ),
    )


BUILDERS: dict[str, Callable[[], KitV1]] = {
    "tk1": build_tk1_kit,
    "tk2": build_tk2_kit,
    "tk3": build_tk3_kit,
    "tk4": build_tk4_kit,
    "tk5": build_tk5_kit,
}
