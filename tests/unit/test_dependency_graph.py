"""Тесты графа влияния точечных правок (Д4 §5.9).

Дословный пример §6.5: правка темы T2.3 затрагивает
[T2.3, LP-T2.3, SL-T2.3, Q-018, Q-019, Q-020, ST-T2.3-1, MP-M2];
unchanged начинается с ["hours", "competencies"].
"""

from __future__ import annotations

import pytest

from karkas.domain.dependency_graph import closure, unchanged
from karkas.domain.kit import (
    AnswerKey,
    Assessment,
    Competency,
    Content,
    ContentBlock,
    Criterion,
    FinalAttestation,
    Framework,
    KitV1,
    Module,
    Outcome,
    ProgramHeader,
    Source,
    Topic,
    Workload,
)


def topic(ref: str, outcome: str, complexity: int = 1) -> Topic:
    return Topic(
        ref=ref,
        title=f"Тема {ref}",
        workload=Workload(lecture=2, practice=2),
        outcome_refs=[outcome],
        complexity=complexity,
    )


def build_kit() -> KitV1:
    """Комплект из примера: 6 модулей, у M2 — тема T2.3 со всем окружением."""
    header = ProgramHeader(
        kind="dpp_pk",
        title="Анализ данных на Python",
        form="part_time",
        total_hours=72,
        final_attestation=FinalAttestation(form="защита проекта", hours=4),
        document="удостоверение о повышении квалификации",
    )
    framework = Framework(
        goal="Цель",
        competencies=[
            Competency(
                ref="C1",
                title="Анализ данных",
                outcomes=[
                    Outcome(ref="LO2.1", type="knowledge", text="Знает методы"),
                    Outcome(ref="LO2.2", type="skill", text="Умеет обрабатывать данные"),
                ],
            )
        ],
        modules=[
            Module(ref="M1", number=1, title="Введение", topics=[topic("T1.1", "LO2.1")]),
            Module(
                ref="M2",
                number=2,
                title="Обработка данных в pandas",
                topics=[topic("T2.1", "LO2.1"), topic("T2.2", "LO2.1"), topic("T2.3", "LO2.2", complexity=2)],
            ),
            Module(ref="M3", number=3, title="Визуализация", topics=[topic("T3.1", "LO2.2", complexity=2)]),
            Module(ref="M4", number=4, title="Отчёты", topics=[topic("T4.1", "LO2.2", complexity=2)]),
            Module(ref="M5", number=5, title="Проект", topics=[topic("T5.1", "LO2.2", complexity=3)]),
            Module(ref="M6", number=6, title="Защита", topics=[topic("T6.1", "LO2.2", complexity=3)]),
        ],
        final_attestation=FinalAttestation(form="защита проекта", hours=4),
    )
    content = Content(
        module_programs=[ContentBlock(ref="MP-M2", kind="module_program", module_ref="M2")],
        lecture_plans=[ContentBlock(ref="LP-T2.3", kind="lecture_plan", topic_ref="T2.3")],
        slides=[ContentBlock(ref="SL-T2.3", kind="slides", topic_ref="T2.3")],
        assessments=[
            Assessment(
                ref="Q-018",
                kind="test_question",
                topic_ref="T2.3",
                stem="Как сгруппировать данные?",
                qtype="single",
                answer_key=AnswerKey(correct=["a"]),
                outcome_refs=["LO2.2"],
            ),
            Assessment(
                ref="Q-019",
                kind="test_question",
                topic_ref="T2.3",
                stem="Как объединить таблицы?",
                qtype="single",
                answer_key=AnswerKey(correct=["a"]),
                outcome_refs=["LO2.2"],
            ),
            Assessment(
                ref="Q-020",
                kind="test_question",
                topic_ref="T2.3",
                stem="Как посчитать сводку?",
                qtype="single",
                answer_key=AnswerKey(correct=["a"]),
                outcome_refs=["LO2.2"],
            ),
            Assessment(
                ref="ST-T2.3-1",
                kind="seminar_task",
                topic_ref="T2.3",
                stem="Постройте отчёт по выгрузке",
                rubric=[Criterion(criterion="Полнота", max_points=5)],
                outcome_refs=["LO2.2"],
            ),
        ],
    )
    return KitV1(program=header, framework=framework, content=content)


# ---------------------------------------------------------------------------
# Дословный пример Д4 §6.5: правка темы T2.3
# ---------------------------------------------------------------------------


def test_closure_topic_23_matches_spec_example():
    assert closure(build_kit(), "T2.3") == [
        "T2.3",
        "LP-T2.3",
        "SL-T2.3",
        "Q-018",
        "Q-019",
        "Q-020",
        "ST-T2.3-1",
        "MP-M2",
    ]


def test_unchanged_topic_23_starts_with_hours_competencies_and_modules():
    kit = build_kit()
    result = unchanged(kit, "T2.3")
    assert result == [
        "hours",
        "competencies",
        "C1",
        "LO2.1",
        "LO2.2",
        "M1",
        "M2",
        "M3",
        "M4",
        "M5",
        "M6",
        "T1.1",
        "T2.1",
        "T2.2",
        "T3.1",
        "T4.1",
        "T5.1",
        "T6.1",
    ]


def test_closure_topic_without_slides_still_lists_planned_artifacts():
    kit = build_kit()
    kit.content.lecture_plans = []
    kit.content.slides = []
    result = closure(kit, "T2.3")
    assert result[:3] == ["T2.3", "LP-T2.3", "SL-T2.3"]


# ---------------------------------------------------------------------------
# Результат обучения
# ---------------------------------------------------------------------------


def test_closure_outcome():
    result = closure(build_kit(), "LO2.2")
    assert result == ["LO2.2", "T2.3", "T3.1", "T4.1", "T5.1", "T6.1", "Q-018", "Q-019", "Q-020", "ST-T2.3-1"]


def test_unchanged_outcome_drops_its_topics_and_assessments():
    result = unchanged(build_kit(), "LO2.2")
    assert result[:2] == ["hours", "competencies"]
    assert "LO2.2" not in result
    assert "T2.3" not in result and "Q-018" not in result
    assert "T2.1" in result and "LO2.1" in result


# ---------------------------------------------------------------------------
# Оценочное средство
# ---------------------------------------------------------------------------


def test_closure_assessment_is_itself():
    assert closure(build_kit(), "Q-018") == ["Q-018"]
    assert closure(build_kit(), "ST-T2.3-1") == ["ST-T2.3-1"]


def test_unchanged_assessment_keeps_others():
    result = unchanged(build_kit(), "Q-018")
    assert "Q-018" not in result
    assert "Q-019" in result and "T2.3" in result


# ---------------------------------------------------------------------------
# Модуль
# ---------------------------------------------------------------------------


def test_closure_module_keeps_topic_order():
    assert closure(build_kit(), "M2") == ["MP-M2", "T2.1", "T2.2", "T2.3"]


def test_unchanged_module_keeps_other_modules():
    result = unchanged(build_kit(), "M2")
    assert "M1" in result and "M3" in result
    assert "T2.3" not in result and "MP-M2" not in result


# ---------------------------------------------------------------------------
# Блоки содержания и ошибки
# ---------------------------------------------------------------------------


def test_closure_slides_block_is_itself():
    assert closure(build_kit(), "SL-T2.3") == ["SL-T2.3"]


def test_unknown_ref_raises_value_error():
    with pytest.raises(ValueError, match="Неизвестный элемент"):
        closure(build_kit(), "XX-99")
    with pytest.raises(ValueError):
        unchanged(build_kit(), "XX-99")


def test_competency_ref_raises_explained_error():
    with pytest.raises(ValueError, match="каркас"):
        closure(build_kit(), "C1")


# ---------------------------------------------------------------------------
# Источники темы (Source.topic_refs; поле добавляет мейн-агент в kit.py)
# ---------------------------------------------------------------------------


def test_closure_topic_includes_its_sources():
    if not hasattr(Source, "model_fields") or "topic_refs" not in Source.model_fields:
        pytest.skip("Source.topic_refs появится в kit.py позже (поле мейн-агента)")
    kit = build_kit()
    kit.content.sources = [
        Source(ref="SRC-10", section="main", citation="Книга про pandas", topic_refs=["T2.3"]),
        Source(ref="SRC-11", section="additional", citation="Статья", topic_refs=["T2.1"]),
    ]
    result = closure(kit, "T2.3")
    assert result[-2:] == ["MP-M2", "SRC-10"]
    assert "SRC-11" not in result
    assert "SRC-10" not in unchanged(kit, "T2.3")
