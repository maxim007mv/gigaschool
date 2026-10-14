"""S03 · Уточняющие вопросы по незаполненным слотам (Д4 §5.2)."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S03_clarifying_questions"
METADATA = SkillSpec(
    code="S03",
    name="Уточняющие вопросы",
    dir=DIR,
    model_class="bulk",
    depends_on=("S01", "S02"),
)

REQUIRED_SLOTS: tuple[str, ...] = (
    "kind",
    "total_hours",
    "audience",
    "entry_level",
    "form",
    "final_attestation",
)

DEFAULT_QUESTIONS: dict[str, tuple[str, list[str], str]] = {
    "kind": (
        "Какой это тип программы: повышение квалификации или общеразвивающая?",
        ["Повышение квалификации (ДПП ПК)", "Общеразвивающая (ДОП)"],
        "От вида программы зависят обязательные разделы и выдаваемый документ.",
    ),
    "total_hours": (
        "Сколько всего академических часов?",
        ["16", "36", "72", "144", "256"],
        "Объём задаёт число занятий и глубину тем.",
    ),
    "audience": (
        "Кто будет учиться?",
        [],
        "От аудитории зависят формулировки, примеры и сложность.",
    ),
    "entry_level": (
        "Что слушатели уже умеют?",
        [],
        "Входной уровень определяет стартовую сложность материалов.",
    ),
    "form": (
        "Как будут проходить занятия?",
        ["Очно", "Очно-заочно", "Дистанционно", "Стажировка"],
        "Форма обучения влияет на часы ДОТ и СРС.",
    ),
    "final_attestation": (
        "Как проверить результат в конце обучения?",
        ["Тест", "Собеседование", "Проект/защита", "Экзамен"],
        "Итоговая аттестация входит в объём часов программы.",
    ),
}


class AssumptionOut(BaseModel):
    text: str
    slot: str | None = None
    accepted_value: str | None = None
    source: str = "agent"


class QuestionOut(BaseModel):
    slot: str = ""
    question: str = ""
    why: str = ""
    options: list[str] = Field(default_factory=list)
    required: bool = True


class QuestionsOut(BaseModel):
    questions: list[QuestionOut] = Field(default_factory=list)
    assumptions: list[AssumptionOut] = Field(default_factory=list)


def normalize(payload: QuestionsOut, missing: list[str], max_questions: int) -> dict[str, Any]:
    """Обрезать до лимита, добить обязательные слоты шаблонами, записать допущения."""
    allowed = [slot for slot in missing if slot in REQUIRED_SLOTS] or list(REQUIRED_SLOTS)
    questions: list[dict[str, Any]] = []
    seen: set[str] = set()
    assumptions = [item.model_dump(mode="json") for item in payload.assumptions if item.text.strip()]
    for item in payload.questions:
        slot = item.slot.strip()
        text = item.question.strip()
        if slot not in allowed or slot in seen or not text:
            continue
        seen.add(slot)
        questions.append(
            {
                "slot": slot,
                "question": text,
                "why": item.why.strip(),
                "options": [option.strip() for option in item.options[:6] if option.strip()],
                "required": slot in REQUIRED_SLOTS,
            }
        )
    for slot in allowed:
        if slot in seen or slot not in DEFAULT_QUESTIONS:
            continue
        text, options, why = DEFAULT_QUESTIONS[slot]
        questions.append(
            {"slot": slot, "question": text, "why": why, "options": options, "required": slot in REQUIRED_SLOTS}
        )
        seen.add(slot)
    if len(questions) > max_questions:
        for dropped in questions[max_questions:]:
            assumptions.append(
                {
                    "text": f"Слот {dropped['slot']} уточняется отдельно или принимается по умолчанию",
                    "slot": dropped["slot"],
                    "accepted_value": None,
                    "source": "agent",
                }
            )
        questions = questions[:max_questions]
    return {"questions": questions, "assumptions": assumptions}


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Собрать ≤ 5 вопросов по незаполненным слотам (или пустой список)."""
    s01 = inputs.get("S01") if isinstance(inputs.get("S01"), dict) else {}
    s02 = inputs.get("S02") if isinstance(inputs.get("S02"), dict) else {}
    missing = [
        str(slot)
        for slot in (inputs.get("missing_slots") or s01.get("missing_slots") or [])
        if str(slot).strip()
    ]
    if s02.get("kind"):
        missing = [slot for slot in missing if slot != "kind"]
    if not missing:
        return {"questions": [], "assumptions": []}
    payload = cast(
        QuestionsOut,
        await complete_structured(
            ctx,
            METADATA,
            QuestionsOut,
            missing_slots_json=to_json(missing),
            profile_json=to_json(inputs.get("profile") or s01.get("profile") or {}),
            max_questions=ctx.settings.max_questions,
        ),
    )
    return normalize(payload, missing, ctx.settings.max_questions)
