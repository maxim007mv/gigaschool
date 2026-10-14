"""S14 · Тестовые вопросы с ключами и привязкой к РО (Д4 §5.6)."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S14_test_questions"
METADATA = SkillSpec(code="S14", name="Тестовые вопросы", dir=DIR, model_class="bulk", depends_on=("S11",))

QTYPES: tuple[str, ...] = ("single", "multiple", "truefalse", "short", "matching", "order", "open")
CHOICE_TYPES = ("single", "multiple")


class OptionOut(BaseModel):
    id: str = ""
    text: str = ""


class AnswerKeyOut(BaseModel):
    correct: list[str] = Field(default_factory=list)
    explanation: str | None = None


class QuestionOut(BaseModel):
    ref: str = ""
    topic_ref: str | None = None
    module_ref: str | None = None
    stem: str = ""
    qtype: Literal["single", "multiple", "truefalse", "short", "matching", "order", "open", ""] = "single"
    options: list[OptionOut] = Field(default_factory=list)
    answer_key: AnswerKeyOut | None = None
    outcome_refs: list[str] = Field(default_factory=list)
    difficulty: int | None = None


class QuestionsOut(BaseModel):
    questions: list[QuestionOut] = Field(default_factory=list)


def normalize_questions(
    items: list[QuestionOut],
    known_outcomes: set[str],
    known_topics: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Постпроверка: ключ, РО, варианты — иначе вопрос отбрасывается в dropped."""
    questions: list[dict[str, Any]] = []
    dropped: list[str] = []
    for index, question in enumerate(items, start=1):
        ref = question.ref.strip() or f"Q-{index:03d}"
        stem = question.stem.strip()
        if not stem:
            dropped.append(f"{ref}: пустая формулировка")
            continue
        refs = [ref_name for ref_name in question.outcome_refs if not known_outcomes or ref_name in known_outcomes]
        if not refs:
            dropped.append(f"{ref}: нет привязки к РО (V-COV-04)")
            continue
        topic_ref = question.topic_ref.strip() if isinstance(question.topic_ref, str) else None
        if topic_ref and known_topics and topic_ref not in known_topics:
            topic_ref = None
        qtype = question.qtype if question.qtype in QTYPES else "single"
        options: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for option in question.options:
            option_id, text = option.id.strip(), option.text.strip()
            if not option_id or not text or option_id in seen_ids:
                continue
            seen_ids.add(option_id)
            options.append({"id": option_id, "text": text})
        key = question.answer_key
        if key is None or not [item.strip() for item in key.correct if item.strip()]:
            dropped.append(f"{ref}: нет ключа ответа (V-COV-04)")
            continue
        correct = [item.strip() for item in key.correct if item.strip()]
        if qtype in CHOICE_TYPES:
            if len(options) < 2:
                dropped.append(f"{ref}: меньше двух вариантов ответа")
                continue
            correct = [item for item in correct if item in seen_ids]
            if not correct:
                dropped.append(f"{ref}: правильный вариант не найден среди options")
                continue
        difficulty = question.difficulty if isinstance(question.difficulty, int) and 1 <= question.difficulty <= 5 else None
        questions.append(
            {
                "ref": ref,
                "kind": "test_question",
                "topic_ref": topic_ref,
                "module_ref": question.module_ref.strip() if isinstance(question.module_ref, str) else None,
                "stem": stem,
                "qtype": qtype,
                "options": options,
                "answer_key": {"correct": correct, "explanation": (key.explanation or "").strip() or None},
                "outcome_refs": refs,
                "difficulty": difficulty,
            }
        )
    return questions, dropped


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Сгенерировать тестовые вопросы; вопросы без ключа/РО отбрасываются."""
    outcomes = inputs.get("outcomes") or []
    known_outcomes = {str(item.get("ref")) for item in outcomes if isinstance(item, dict) and item.get("ref")}
    topics = inputs.get("topics") or (inputs.get("module") or {}).get("topics") or []
    known_topics = {str(item.get("ref")) for item in topics if isinstance(item, dict) and item.get("ref")}
    count = inputs.get("count")
    payload = cast(
        QuestionsOut,
        await complete_structured(
            ctx,
            METADATA,
            QuestionsOut,
            instruction=str(inputs.get("instruction") or ""),
            outcomes_json=to_json(outcomes),
            topics_json=to_json(topics),
            profile_json=to_json(inputs.get("profile") or {}),
            count=count if isinstance(count, int) and count > 0 else max(3, len(known_outcomes) * 2),
        ),
    )
    questions, dropped = normalize_questions(payload.questions, known_outcomes, known_topics)
    if not questions:
        raise ValueError("S14: после постпроверки не осталось валидных вопросов (нет ключа/РО)")
    return {"questions": questions, "dropped": dropped, "count": len(questions)}
