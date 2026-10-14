"""S08 · Солвер часов: детерминированное распределение (Д4 §5.4)."""

from __future__ import annotations

from typing import Any

from karkas.agent.skills._base import (
    SkillContext,
    SkillSpec,
    hours_constraints,
    hours_modules,
    plan_to_dict,
)
from karkas.domain.hours import rebalance, solve

DIR = "S08_hours_solver"
METADATA = SkillSpec(code="S08", name="Солвер часов", dir=DIR, depends_on=("S07",))


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Распределить часы по сетке: solve или rebalance (при закреплённых ячейках)."""
    s07 = inputs.get("S07") if isinstance(inputs.get("S07"), dict) else {}
    raw_modules = inputs.get("modules") or s07.get("modules") or []
    modules = hours_modules(raw_modules)
    constraints_raw = dict(inputs.get("constraints") or {})
    constraints = hours_constraints(constraints_raw)
    locked = inputs.get("locked_cells")
    plan = rebalance(modules, constraints, locked) if locked else solve(modules, constraints)
    result = plan_to_dict(plan)
    result["constraints"] = {
        "total": constraints.total,
        "final_att": constraints.final_att,
        "unit": constraints.unit,
        "self_study_only": constraints.self_study_only,
        "min_practice_share": constraints.min_practice_share,
        "self_study_share": constraints.self_study_share,
        "distance_share": constraints.distance_share,
    }
    return result
