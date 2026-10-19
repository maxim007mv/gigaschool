"""V-CNT-*: качество слайдов, тестов и заданий."""

from __future__ import annotations

from karkas.domain.kit import (
    AnswerKey,
    Assessment,
    AssessmentOption,
    Content,
    ContentBlock,
    KitV1,
)
from karkas.domain.validators import ValidationContext, run_validation
from tests.conftest import build_minimal_kit


def _kit_with_bad_slide() -> KitV1:
    kit = build_minimal_kit()
    kit.content = Content(
        slides=[
            ContentBlock(
                ref="SL-T1.1",
                kind="slides",
                topic_ref="T1.1",
                body={
                    "slides": [
                        {"title": "OK", "bullets": ["одна мысль"], "speaker_notes": "говорим про вводную"},
                        {"title": "TBD", "bullets": ["a", "b", "c", "d", "e", "f", "g"]},
                    ]
                },
            )
        ]
    )
    return kit


def test_cnt_flags_placeholder_and_missing_notes() -> None:
    report = run_validation(ValidationContext(kit=_kit_with_bad_slide(), stage="kit"))
    codes = {i.rule_code for i in report.issues}
    assert "V-CNT-01" in codes
    assert any(i.fix_hint and i.fix_hint.get("endpoint") == "kit:regenerate" for i in report.issues)


def test_cnt_accepts_single_character_numeric_options() -> None:
    """Варианты «9», «A», «B» — валидные ответы, а не пустые строки."""
    kit = build_minimal_kit()
    kit.content.assessments = [
        Assessment(
            ref="Q-1",
            kind="test_question",
            topic_ref="T1.1",
            stem="Что выведет этот код?",
            qtype="single",
            options=[
                AssessmentOption(id="a", text="9"),
                AssessmentOption(id="b", text="10"),
            ],
            answer_key=AnswerKey(correct=["a"]),
            outcome_refs=["LO1.1"],
        )
    ]
    report = run_validation(ValidationContext(kit=kit, stage="kit"))
    assert not any(i.rule_code == "V-CNT-02" for i in report.issues)


def test_cnt_test_distractor_quality() -> None:
    kit = build_minimal_kit()
    kit.content.assessments = [
        Assessment(
            ref="Q-1",
            kind="test_question",
            topic_ref="T1.1",
            stem="Короткий?",
            qtype="single",
            options=[
                AssessmentOption(id="a", text="Короткий?"),
                AssessmentOption(id="b", text="другой"),
            ],
            answer_key=AnswerKey(correct=["b"]),
            outcome_refs=["LO1.1"],
        )
    ]
    report = run_validation(ValidationContext(kit=kit, stage="kit"))
    assert any(i.rule_code == "V-CNT-02" for i in report.issues)
