"""S23 · Адаптация программы под аудиторию или объём (Д4 §5.11)."""

from __future__ import annotations

import re
from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import (
    SkillContext,
    SkillSpec,
    complete_structured,
    hours_constraints,
    hours_modules,
    plan_to_dict,
    to_json,
)
from karkas.domain.hours import rebalance, solve

DIR = "S23_adapt"
METADATA = SkillSpec(code="S23", name="Адаптация программы", dir=DIR, model_class="bulk", depends_on=("S08",))

OUTCOME_RE = re.compile(r"^LO\d{1,2}\.\d{1,2}$")
OUTCOME_TYPES: tuple[str, ...] = ("knowledge", "skill", "experience")


class AdaptedOutcomeOut(BaseModel):
    ref: str = ""
    type: str = "knowledge"
    text: str = ""


class AdaptedOut(BaseModel):
    outcomes: list[AdaptedOutcomeOut] = Field(default_factory=list)
    notes: str = ""


def normalize_outcomes(items: list[AdaptedOutcomeOut]) -> list[dict[str, str]]:
    """Чистка переформулированных РО: ref, тип, непустой текст."""
    outcomes: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        text = item.text.strip()
        if not text:
            continue
        ref = item.ref.strip() if OUTCOME_RE.match(item.ref.strip()) else f"LO1.{index}"
        outcome_type = item.type if item.type in OUTCOME_TYPES else "knowledge"
        outcomes.append({"ref": ref, "type": outcome_type, "text": text})
    return outcomes


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Пересчитать часы солвером и (при смене аудитории) переформулировать РО."""
    modules_raw = inputs.get("modules") or (inputs.get("S07") if isinstance(inputs.get("S07"), dict) else {}).get("modules") or []
    if not modules_raw:
        raise ValueError("S23: нет структуры модулей для пересчёта")
    new_constraints = inputs.get("new_constraints") or inputs.get("constraints")
    if not isinstance(new_constraints, dict) or not new_constraints:
        raise ValueError("S23: не заданы новые ограничения (new_constraints)")
    modules = hours_modules(modules_raw)
    constraints = hours_constraints(new_constraints)
    locked = inputs.get("locked_cells")
    plan = rebalance(modules, constraints, locked) if locked else solve(modules, constraints)
    child = {"total_hours": constraints.total, **plan_to_dict(plan)}

    audience = str(inputs.get("new_audience") or "").strip()
    outcomes: list[dict[str, str]] = []
    notes = ""
    if audience:
        payload = cast(
            AdaptedOut,
            await complete_structured(
                ctx,
                METADATA,
                AdaptedOut,
                new_audience=audience,
                total_hours=constraints.total,
                outcomes_json=to_json(inputs.get("outcomes") or []),
            ),
        )
        outcomes = normalize_outcomes(payload.outcomes)
        notes = payload.notes.strip()
    return {
        "child": child,
        "outcomes": outcomes,
        "assumptions": [
            "веса модулей и «практичность» тем сохранены при смене объёма (Д4 §5.11)",
            "каркас программы-потомка повторно проходит Human Gate",
        ],
        "notes": notes,
    }
