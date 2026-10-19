"""S09 · Календарный график: раскладка часов по дням (Д4 §5.5)."""

from __future__ import annotations

from typing import Any

from karkas.agent.skills._base import SkillContext, SkillSpec, hours_constraints
from karkas.domain.calendar import calendar
from karkas.domain.hours import Plan

DIR = "S09_calendar"
METADATA = SkillSpec(code="S09", name="Календарный график", dir=DIR, depends_on=("S08",))

_ACTIVITIES: tuple[str, ...] = ("lecture", "practice", "lab", "self_study", "current_control")
_FINAL_REF = "ИА"


def plan_from_inputs(inputs: dict[str, Any]) -> Plan:
    """Собрать Plan из выхода S08 (или плоских rows/distance/module_of)."""
    s08 = inputs.get("S08") if isinstance(inputs.get("S08"), dict) else {}
    return Plan(
        rows=dict(inputs.get("rows") or s08.get("rows") or {}),
        distance=dict(inputs.get("distance") or s08.get("distance") or {}),
        module_of=dict(inputs.get("module_of") or s08.get("module_of") or {}),
    )


def dominant_activity(row: dict[str, Any]) -> str:
    """Вид работ темы с наибольшим числом часов (детерминированный порядок перебора)."""
    best, best_value = "lecture", -1
    for activity in _ACTIVITIES:
        value = int(row.get(activity, 0) or 0)
        if value > best_value:
            best, best_value = activity, value
    return best if best_value > 0 else "self_study"


def _session(seq: int, entry: tuple[int, int, str, int], plan: Plan) -> dict[str, Any]:
    week, day, ref, hours = entry
    if ref == _FINAL_REF or ref not in plan.rows:
        return {
            "seq": seq,
            "week": int(week),
            "day": int(day),
            "topic_ref": None,
            "activity": "final_attestation",
            "mode": "in_person",
            "hours": int(hours),
        }
    mode = "distance" if int(plan.distance.get(ref, 0) or 0) > 0 else "in_person"
    return {
        "seq": seq,
        "week": int(week),
        "day": int(day),
        "topic_ref": ref,
        "activity": dominant_activity(plan.rows[ref]),
        "mode": mode,
        "hours": int(hours),
    }


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Разложить часы по дням и неделям (ИА одним занятием)."""
    plan = plan_from_inputs(inputs)
    if not plan.rows:
        raise ValueError("S09: нет сетки часов — сначала выполните S08")
    raw_constraints = dict(inputs.get("constraints") or {})
    content_total = sum(sum(int(v) for v in row.values()) for row in plan.rows.values())
    if "total" not in raw_constraints and "total_hours" not in raw_constraints:
        raw_constraints["total"] = content_total + int(raw_constraints.get("final_att", 2) or 2)
    constraints = hours_constraints(raw_constraints)
    max_per_day = int(inputs.get("max_hours_per_day") or raw_constraints.get("max_hours_per_day") or 8)
    days_per_week = int(inputs.get("days_per_week") or raw_constraints.get("days_per_week") or 5)
    raw_sessions = calendar(plan, constraints, max_per_day, days_per_week)
    sessions = [_session(seq, entry, plan) for seq, entry in enumerate(raw_sessions, start=1)]
    brief = str(inputs.get("brief") or "")
    from karkas.domain.tk3_structure import tk3_min_calendar_weeks

    weeks = max((session["week"] for session in sessions), default=0)
    weeks = tk3_min_calendar_weeks(brief, int(constraints.total), weeks)
    return {
        "weeks": weeks,
        "days": max((session["day"] for session in sessions), default=0),
        "days_per_week": days_per_week,
        "max_hours_per_day": max_per_day,
        "sessions": sessions,
    }
