"""Тесты правил группы «Покрытие», «Логика» и «Дубли» (V-COV-01..04, V-SEQ-01, V-DUP-01).

Для каждого правила — минимум один кейс «нарушение → issue» и «норма → нет issue».
"""

from __future__ import annotations

from typing import Any

from karkas.domain.kit import (
    AnswerKey,
    Assessment,
    Competency,
    Content,
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
from karkas.settings import settings


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


def _question(ref: str, outcomes: list[str], *, stem: str | None = None) -> Assessment:
    return Assessment(
        ref=ref,
        kind="test_question",
        topic_ref="T1.1",
        stem=stem or f"Вопрос {ref}: выберите верный вариант",
        qtype="single",
        answer_key=AnswerKey(correct=["a"], explanation="Потому что так верно"),
        outcome_refs=outcomes,
    )


def build_kit(
    *,
    outcomes: list[Outcome] | None = None,
    modules: list[Module] | None = None,
    assessments: list[Assessment] | None = None,
    competencies: list[Competency] | None = None,
) -> KitV1:
    """Каркас с полным покрытием: 2 темы, 3 РО (З/У/Н), по 2 вопроса на РО."""
    if outcomes is None:
        outcomes = [
            Outcome(ref="LO1.1", type="knowledge", text="Знает синтаксис"),
            Outcome(ref="LO1.2", type="skill", text="Умеет писать циклы"),
            Outcome(ref="LO1.3", type="experience", text="Есть опыт решения задач"),
        ]
    if competencies is None:
        competencies = [Competency(ref="C1", title="Основы программирования", outcomes=outcomes)]
    if modules is None:
        modules = [
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[topic("T1.1", ["LO1.1"]), topic("T1.2", ["LO1.2", "LO1.3"], complexity=2, lecture=2)],
            )
        ]
    if assessments is None:
        assessments = [
            _question("Q-001", ["LO1.1"]),
            _question("Q-002", ["LO1.1"]),
            _question("Q-003", ["LO1.2"]),
            _question("Q-004", ["LO1.2"]),
            _question("Q-005", ["LO1.3"]),
            _question("Q-006", ["LO1.3"]),
        ]
    header = ProgramHeader(
        kind="dop",
        title="Первые шаги в Python",
        form="full_time",
        total_hours=16,
        final_attestation=FinalAttestation(form="защита проекта", hours=2),
    )
    return KitV1(
        program=header,
        profile=ProgramProfile(entry_level="базовый", constraints=ProgramConstraints()),
        framework=Framework(
            goal="Освоить основы",
            competencies=competencies,
            modules=modules,
            final_attestation=FinalAttestation(form="защита проекта", hours=2),
        ),
        content=Content(assessments=assessments),
    )


def issues_of(kit: KitV1, code: str, **ctx_kwargs: Any) -> list:
    report = run_validation(ValidationContext(kit=kit, **ctx_kwargs))
    return [i for i in report.issues if i.rule_code == code]


# ---------------------------------------------------------------------------
# V-COV-01: каждый РО раскрыт хотя бы в одной теме
# ---------------------------------------------------------------------------


def test_cov_01_ok():
    assert issues_of(build_kit(), "V-COV-01") == []


def test_cov_01_uncovered_outcome_is_error():
    outcomes = [
        Outcome(ref="LO1.1", type="knowledge", text="Знает синтаксис"),
        Outcome(ref="LO1.2", type="skill", text="Умеет писать циклы"),
        Outcome(ref="LO1.9", type="skill", text="Нигде не раскрыт"),
    ]
    kit = build_kit(outcomes=outcomes)
    issues = issues_of(kit, "V-COV-01")
    assert [i.entity_ref for i in issues] == ["LO1.9"]
    assert issues[0].severity == "error"


def test_cov_01_skipped_without_outcomes():
    kit = build_kit(competencies=[Competency(ref="C1", title="Пустая", outcomes=[])])
    report = run_validation(ValidationContext(kit=kit))
    assert "V-COV-01" in report.summary["skipped"]
    assert "V-COV-02" in report.summary["skipped"]


# ---------------------------------------------------------------------------
# V-COV-02: каждый РО проверяется ≥ 2 оценочными средствами
# ---------------------------------------------------------------------------


def test_cov_02_ok():
    assert issues_of(build_kit(), "V-COV-02") == []


def test_cov_02_single_assessment_is_error():
    assessments = [
        _question("Q-001", ["LO1.1"]),
        _question("Q-002", ["LO1.1"]),
        _question("Q-003", ["LO1.2"]),
        _question("Q-004", ["LO1.2"]),
        _question("Q-005", ["LO1.3"]),  # у LO1.3 только одно средство
    ]
    kit = build_kit(assessments=assessments)
    issues = issues_of(kit, "V-COV-02")
    assert [i.entity_ref for i in issues] == ["LO1.3"]
    assert issues[0].severity == "error"
    assert str(settings.min_assessments_per_outcome) in issues[0].message


def test_cov_02_threshold_from_settings():
    assessments = [
        _question("Q-001", ["LO1.1"]),
        _question("Q-002", ["LO1.2"]),
        _question("Q-003", ["LO1.3"]),
    ]
    kit = build_kit(assessments=assessments)
    report = run_validation(ValidationContext(kit=kit))
    assert report.summary["coverage"]["min_assessments"] == settings.min_assessments_per_outcome
    assert len([i for i in report.issues if i.rule_code == "V-COV-02"]) == 3


# ---------------------------------------------------------------------------
# V-COV-03: у компетенции есть З/У/Н
# ---------------------------------------------------------------------------


def test_cov_03_ok():
    assert issues_of(build_kit(), "V-COV-03") == []


def test_cov_03_missing_experience_is_warning():
    outcomes = [
        Outcome(ref="LO1.1", type="knowledge", text="Знает"),
        Outcome(ref="LO1.2", type="skill", text="Умеет"),
    ]
    kit = build_kit(outcomes=outcomes)
    issues = issues_of(kit, "V-COV-03")
    assert len(issues) == 1 and issues[0].severity == "warning"
    assert "практический опыт" in issues[0].message


# ---------------------------------------------------------------------------
# V-COV-04: привязки РО у тем и оценочных средств
# ---------------------------------------------------------------------------


def test_cov_04_topic_without_outcomes_is_error():
    kit = build_kit(
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[topic("T1.1", []), topic("T1.2", ["LO1.2", "LO1.3"])],
            )
        ]
    )
    issues = issues_of(kit, "V-COV-04")
    assert any(i.entity_ref == "T1.1" and i.severity == "error" for i in issues)


def test_cov_04_unknown_outcome_in_topic_is_error():
    kit = build_kit(
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[topic("T1.1", ["LO9.9"]), topic("T1.2", ["LO1.2", "LO1.3"])],
            )
        ]
    )
    issues = issues_of(kit, "V-COV-04")
    assert any("LO9.9" in i.message for i in issues)


def test_cov_04_unknown_outcome_in_assessment_is_error():
    assessments = build_kit().content.assessments
    assessments[0] = _question("Q-001", ["LO9.9"])
    kit = build_kit(assessments=assessments)
    issues = issues_of(kit, "V-COV-04")
    assert any(i.entity_ref == "Q-001" and "LO9.9" in i.message for i in issues)


def test_cov_04_assessment_without_outcomes_is_error():
    assessments = build_kit().content.assessments
    broken = Assessment.model_construct(
        ref="Q-001",
        kind="test_question",
        topic_ref="T1.1",
        stem="Вопрос без привязки",
        qtype="single",
        answer_key=AnswerKey(correct=["a"]),
        outcome_refs=[],
    )
    assessments[0] = broken
    kit = build_kit(assessments=assessments)
    issues = issues_of(kit, "V-COV-04")
    assert any(i.entity_ref == "Q-001" and "не привязано" in i.message for i in issues)


def test_cov_04_ok():
    assert issues_of(build_kit(), "V-COV-04") == []


# ---------------------------------------------------------------------------
# V-SEQ-01: сложность не убывает в порядке программы
# ---------------------------------------------------------------------------


def test_seq_01_ok():
    kit = build_kit(
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[
                    topic("T1.1", ["LO1.1"], complexity=1),
                    topic("T1.2", ["LO1.1"], complexity=2),
                    topic("T1.3", ["LO1.2", "LO1.3"], complexity=2),
                ],
            )
        ]
    )
    assert issues_of(kit, "V-SEQ-01") == []


def test_seq_01_complex_topic_before_base_is_error():
    kit = build_kit(
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[
                    topic("T1.1", ["LO1.1"], complexity=3),
                    topic("T1.2", ["LO1.2", "LO1.3"], complexity=1),
                ],
            )
        ]
    )
    issues = issues_of(kit, "V-SEQ-01")
    assert [i.entity_ref for i in issues] == ["T1.2"]
    assert issues[0].severity == "error"


# ---------------------------------------------------------------------------
# V-DUP-01: дубли по хэшу и по эмбеддингам
# ---------------------------------------------------------------------------


def test_dup_01_same_stem_is_warning():
    assessments = build_kit().content.assessments
    assessments.append(_question("Q-007", ["LO1.1"], stem="Что такое цикл в Python?"))
    assessments.append(_question("Q-008", ["LO1.1"], stem="  что ТАКОЕ   цикл в python?  "))
    kit = build_kit(assessments=assessments)
    issues = issues_of(kit, "V-DUP-01")
    assert len(issues) == 1
    assert issues[0].entity_ref == "Q-008" and issues[0].severity == "warning"


def test_dup_01_distinct_stems_ok():
    assert issues_of(build_kit(), "V-DUP-01") == []


def test_dup_01_embeddings_close_is_warning():
    kit = build_kit()
    embeddings = {
        "Q-001": [1.0, 0.0],
        "Q-002": [0.99, 0.05],  # косинус ≈ 0.999 ≥ settings.dup_cosine
        "Q-003": [0.0, 1.0],
    }
    issues = issues_of(kit, "V-DUP-01", embeddings=embeddings)
    assert len(issues) == 1
    assert {issues[0].entity_ref} <= {"Q-001", "Q-002"}
    assert "cosine" not in issues[0].message  # сообщение по-русски: «косинус»
    assert "косинус" in issues[0].message


def test_dup_01_embeddings_orthogonal_ok():
    kit = build_kit()
    embeddings = {"Q-001": [1.0, 0.0], "Q-002": [0.0, 1.0]}
    assert issues_of(kit, "V-DUP-01", embeddings=embeddings) == []


def test_dup_01_embeddings_threshold_from_settings():
    kit = build_kit()
    report = run_validation(ValidationContext(kit=kit, embeddings={"Q-001": [1.0, 0.0]}))
    assert report.summary["duplicates"]["cosine_threshold"] == settings.dup_cosine
