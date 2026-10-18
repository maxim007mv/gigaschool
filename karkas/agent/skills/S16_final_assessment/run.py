"""S16 · Оценочные средства итоговой аттестации (Д4 §5.6)."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S16_final_assessment"
METADATA = SkillSpec(code="S16", name="Итоговая аттестация", dir=DIR, model_class="bulk", depends_on=("S10",))

KINDS: tuple[str, ...] = ("interview_question", "final_project", "exam_task")
KINDS_REQUIRING_RUBRIC: tuple[str, ...] = ("final_project", "exam_task")
DEFAULT_LEVELS: list[str] = ["выполнено", "не выполнено"]


class CriterionOut(BaseModel):
    criterion: str = ""
    max_points: float = 0.0
    levels: list[str] = Field(default_factory=list)


class ItemOut(BaseModel):
    ref: str = ""
    kind: Literal["interview_question", "final_project", "exam_task", ""] = "interview_question"
    stem: str = ""
    rubric: list[CriterionOut] = Field(default_factory=list)
    outcome_refs: list[str] = Field(default_factory=list)


class FinalOut(BaseModel):
    items: list[ItemOut] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    form: str = ""
    notes: str = ""


def normalize_items(items: list[ItemOut], known_outcomes: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Постпроверка: rubric для проектов/экзаменов, РО для всех, refs FA-n."""
    normalized: list[dict[str, Any]] = []
    dropped: list[str] = []
    for index, item in enumerate(items, start=1):
        ref = item.ref.strip() or f"FA-{index}"
        stem = item.stem.strip()
        kind = item.kind if item.kind in KINDS else "interview_question"
        if not stem:
            dropped.append(f"{ref}: пустая формулировка")
            continue
        refs = [name for name in item.outcome_refs if not known_outcomes or name in known_outcomes]
        if not refs:
            dropped.append(f"{ref}: нет привязки к РО (V-COV-04)")
            continue
        rubric: list[dict[str, Any]] = []
        for criterion in item.rubric:
            text = criterion.criterion.strip()
            if not text:
                continue
            rubric.append(
                {
                    "criterion": text,
                    "max_points": float(criterion.max_points) if criterion.max_points > 0 else 1.0,
                    "levels": [level.strip() for level in criterion.levels if level.strip()] or list(DEFAULT_LEVELS),
                }
            )
        if kind in KINDS_REQUIRING_RUBRIC and not rubric:
            dropped.append(f"{ref}: {kind} без критериев оценки (rubric обязателен)")
            continue
        normalized.append({"ref": ref, "kind": kind, "stem": stem, "rubric": rubric, "outcome_refs": refs})
    return normalized, dropped


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Собрать средства ИА и текущего контроля с критериями и привязкой к РО."""
    outcomes = inputs.get("outcomes") or []
    known_outcomes = {str(item.get("ref")) for item in outcomes if isinstance(item, dict) and item.get("ref")}
    payload = cast(
        FinalOut,
        await complete_structured(
            ctx,
            METADATA,
            FinalOut,
            form=str(inputs.get("form") or "не задана"),
            kind=str(inputs.get("kind") or "dpp_pk"),
            outcomes_json=to_json(outcomes),
            profile_json=to_json(inputs.get("profile") or {}),
        ),
    )
    items, dropped = normalize_items(payload.items, known_outcomes)
    if not items:
        raise ValueError("S16: после постпроверки не осталось валидных оценочных средств")
    return {
        "items": items,
        "requirements": [text.strip() for text in payload.requirements if text.strip()],
        "form": payload.form.strip() or str(inputs.get("form") or ""),
        "notes": payload.notes.strip(),
        "dropped": dropped,
    }
