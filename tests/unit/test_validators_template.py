"""Тесты правил шаблона (V-TPL-01..03).

Для каждого правила — минимум один кейс «нарушение → issue» и «норма → нет issue».
Разделы шаблонов читаются из karkas/domain/templates/{dpp_pk,dop}.yaml; на
стадии каркаса разделы, требующие содержания, откладываются (S10 ≠ S19).
"""

from __future__ import annotations

from karkas.domain.kit import (
    AnswerKey,
    Assessment,
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
    Placeholders,
    ProfStandardRef,
    ProgramConstraints,
    ProgramHeader,
    ProgramProfile,
    SignaturePlaceholder,
    Source,
    TeacherPlaceholder,
    Topic,
    Workload,
)
from karkas.domain.validators import ValidationContext, run_validation


def topic(
    ref: str,
    outcomes: list[str],
    *,
    complexity: int = 1,
    lecture: int = 4,
    practice: int = 4,
) -> Topic:
    return Topic(
        ref=ref,
        title=f"Тема {ref}",
        workload=Workload(lecture=lecture, practice=practice),
        outcome_refs=outcomes,
        complexity=complexity,
    )


def _question(ref: str, outcomes: list[str]) -> Assessment:
    return Assessment(
        ref=ref,
        kind="test_question",
        topic_ref="T1.1",
        stem=f"Вопрос {ref}: выберите верный вариант ответа",
        qtype="single",
        answer_key=AnswerKey(correct=["a"], explanation="Пояснение"),
        outcome_refs=outcomes,
    )


def final_project() -> Assessment:
    return Assessment(
        ref="FP-01",
        kind="final_project",
        module_ref="M1",
        stem="Итоговый проект: соберите приложение по заданию",
        rubric=[Criterion(criterion="Работоспособность", max_points=5, levels=["зачтено", "не зачтено"])],
        outcome_refs=["LO1.3"],
    )


def assessment_set() -> list[Assessment]:
    return [
        _question("Q-001", ["LO1.1"]),
        _question("Q-002", ["LO1.1"]),
        _question("Q-003", ["LO1.2"]),
        _question("Q-004", ["LO1.2"]),
        _question("Q-005", ["LO1.3"]),
        _question("Q-006", ["LO1.3"]),
        final_project(),
    ]


def career_calendar() -> Calendar:
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


def content_blocks(kind: str) -> dict[str, list[ContentBlock]]:
    annotation = [
        ContentBlock(ref="ANN-1", kind="annotation", body={"text": "Программа знакомит с основами."})
    ]
    module_programs = [
        ContentBlock(
            ref="MP-M1", kind="module_program", module_ref="M1", body={"hours": 14, "text": "Содержание"}
        )
    ]
    codes = ["3.1", "3.2", "3.3", "3.4"] if kind == "dpp_pk" else ["3.2", "3.3"]
    sections = annotation + [
        ContentBlock(ref=f"SEC-{code}", kind="template_section", body={"text": f"Раздел {code}"})
        for code in codes
    ]
    return {"module_programs": module_programs, "sections": sections}


def sources_set() -> list[Source]:
    return [
        Source(
            ref="SRC-01",
            section="main",
            citation="Иванов И.И. Основы программирования. — М.: Наука, 2024",
            status="verified",
            evidence={"isbn_checked": True},
        ),
    ]


def build_full_kit(kind: str = "dop") -> KitV1:
    """Полный комплект, в котором все обязательные разделы шаблона заполнены."""
    is_dpp = kind == "dpp_pk"
    competency = Competency(
        ref="C1",
        title="Основы программирования",
        prof_standard=ProfStandardRef(code="06.015") if is_dpp else None,
        labor_functions=[LaborFunctionRef(code="C/14.6")] if is_dpp else [],
        outcomes=[
            Outcome(ref="LO1.1", type="knowledge", text="Знает синтаксис"),
            Outcome(ref="LO1.2", type="skill", text="Умеет писать циклы"),
            Outcome(ref="LO1.3", type="experience", text="Есть опыт решения задач"),
        ],
    )
    header = ProgramHeader(
        kind=kind,
        title="Образовательная программа",
        form="internship" if is_dpp else "full_time",
        total_hours=16,
        final_attestation=FinalAttestation(form="защита проекта", hours=2),
        document="удостоверение о повышении квалификации" if is_dpp else "сертификат участника",
        legal_basis=(
            [LegalBasis(ref="LB-01", act="Приказ Минобрнауки России от 24.03.2025 № 266")]
            if is_dpp
            else []
        ),
    )
    framework = Framework(
        goal="Научить основам программирования",
        tasks=["Освоить синтаксис", "Написать проект"],
        competencies=[competency],
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[topic("T1.1", ["LO1.1"]), topic("T1.2", ["LO1.2", "LO1.3"], complexity=2, lecture=2)],
            )
        ],
        final_attestation=FinalAttestation(form="защита проекта", hours=2),
        calendar=career_calendar(),
    )
    return KitV1(
        program=header,
        profile=ProgramProfile(entry_level="базовый", constraints=ProgramConstraints()),
        framework=framework,
        content=Content(
            assessments=assessment_set(),
            sources=sources_set(),
            **content_blocks(kind),
        ),
    )


def build_framework_kit() -> KitV1:
    """Каркас без содержания (S10): разделы содержания откладываются."""
    full = build_full_kit("dpp_pk")
    return KitV1(
        program=full.program,
        profile=full.profile,
        framework=full.framework,
        content=Content(),  # ещё ничего не сгенерировано
    )


def issues_of(kit: KitV1, code: str, **ctx_kwargs: object) -> list:
    report = run_validation(ValidationContext(kit=kit, **ctx_kwargs))
    return [i for i in report.issues if i.rule_code == code]


# ---------------------------------------------------------------------------
# V-TPL-01: обязательные разделы заполнены
# ---------------------------------------------------------------------------


def test_tpl_01_dop_full_kit_ok():
    assert issues_of(build_full_kit("dop"), "V-TPL-01") == []


def test_tpl_01_dpp_full_kit_ok():
    assert issues_of(build_full_kit("dpp_pk"), "V-TPL-01") == []


def test_tpl_01_missing_annotation_is_error():
    kit = build_full_kit("dop")
    kit.content.sections = [b for b in kit.content.sections if b.kind != "annotation"]
    issues = issues_of(kit, "V-TPL-01")
    assert [i.entity_ref for i in issues] == ["1.1"]
    assert issues[0].severity == "error"


def test_tpl_01_missing_module_program_is_error():
    kit = build_full_kit("dop")
    kit.content.module_programs = []
    issues = issues_of(kit, "V-TPL-01")
    assert any(i.entity_ref == "2.4" for i in issues)


def test_tpl_01_summary_counts():
    report = run_validation(ValidationContext(kit=build_full_kit("dop")))
    template = report.summary["template"]
    assert template["filled"] == template["sections_total"]
    assert template["empty"] == []


def test_tpl_01_framework_stage_defers_content_sections():
    report = run_validation(ValidationContext(kit=build_framework_kit()))
    assert report.summary["stage"] == "framework"
    assert "V-TPL-01" not in [i.rule_code for i in report.issues]
    deferred = report.summary["template"]["deferred"]
    assert "1.1" in deferred and "2.4" in deferred and "p1" in deferred
    assert "V-COV-02" in report.summary["skipped"]


# ---------------------------------------------------------------------------
# V-TPL-02: правила вида программы
# ---------------------------------------------------------------------------


def test_tpl_02_dop_with_prof_standard_is_error():
    kit = build_full_kit("dop")
    kit.framework.competencies[0].prof_standard = ProfStandardRef(code="06.015")
    issues = issues_of(kit, "V-TPL-02")
    assert issues and issues[0].severity == "error" and issues[0].entity_ref == "C1"


def test_tpl_02_dop_without_prof_standards_ok():
    assert issues_of(build_full_kit("dop"), "V-TPL-02") == []


def test_tpl_02_dpp_without_ustav_is_error():
    kit = build_full_kit("dpp_pk")
    kit.program.document = "диплом о профессиональной переподготовке"
    issues = issues_of(kit, "V-TPL-02")
    assert len(issues) == 1 and "удостоверение" in issues[0].message


def test_tpl_02_dpp_with_ustav_ok():
    assert issues_of(build_full_kit("dpp_pk"), "V-TPL-02") == []


def test_tpl_02_internship_allowed_with_ustav():
    kit = build_full_kit("dpp_pk")
    assert kit.program.form == "internship"
    assert issues_of(kit, "V-TPL-02") == []


# ---------------------------------------------------------------------------
# V-TPL-03: поля-заполнители пусты
# ---------------------------------------------------------------------------


def test_tpl_03_clean_placeholders_ok():
    assert issues_of(build_full_kit("dop"), "V-TPL-03") == []


def test_tpl_03_order_number_is_error():
    kit = build_full_kit("dop")
    kit = kit.model_copy(update={"placeholders": Placeholders.model_construct(order_number="123-ОД")})
    issues = issues_of(kit, "V-TPL-03")
    assert len(issues) == 1 and issues[0].severity == "error"
    assert issues[0].entity_ref == "placeholders"


def test_tpl_03_filled_teacher_is_error():
    kit = build_full_kit("dop")
    placeholders = Placeholders.model_construct(
        teachers=[TeacherPlaceholder.model_construct(name="Иванов И.И.")]
    )
    kit = kit.model_copy(update={"placeholders": placeholders})
    assert issues_of(kit, "V-TPL-03")


def test_tpl_03_filled_signature_is_error():
    kit = build_full_kit("dop")
    placeholders = Placeholders.model_construct(
        signatures=[SignaturePlaceholder.model_construct(name="Петров П.П.", position="директор")]
    )
    kit = kit.model_copy(update={"placeholders": placeholders})
    assert issues_of(kit, "V-TPL-03")
