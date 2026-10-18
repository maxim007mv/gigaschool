"""Детерминированные каркасы для property/eval-тестов объёмов 16–500 ч.

LLM в проде предлагает темы (S07); часы распределяет только солвер (S08).
Здесь — синтетические модули/темы с фиксированным seed для проверки инвариантов.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Literal

from karkas.domain.calendar import calendar
from karkas.domain.hours import ROW_KEYS, Constraints, HoursInfeasible, ModuleIn, Plan, TopicIn, solve

ProgramKind = Literal["dop", "dpp_pk"]
EVAL_VOLUMES: tuple[int, ...] = (16, 24, 36, 72, 144, 256, 500)


@dataclass(frozen=True, slots=True)
class SkeletonSpec:
    total: int
    kind: ProgramKind
    seed: int = 0
    internship: bool = False
    max_hours_per_day: int = 8


def _module_count(total: int) -> int:
    if total <= 24:
        return 2
    if total <= 72:
        return 3
    if total <= 144:
        return 4
    if total <= 256:
        return 6
    return 8


def build_skeleton_modules(spec: SkeletonSpec) -> list[ModuleIn]:
    """Синтетическая структура модулей/тем (детерминированно по seed и объёму)."""
    rng = random.Random(spec.seed + spec.total * 17 + (1 if spec.kind == "dpp_pk" else 0))
    n_mod = _module_count(spec.total)
    modules: list[ModuleIn] = []
    for mi in range(1, n_mod + 1):
        n_topics = 2 + (spec.total // 72) + (mi % 2)
        n_topics = min(8, max(1, n_topics))
        topics: list[TopicIn] = []
        for ti in range(1, n_topics + 1):
            topics.append(
                TopicIn(
                    ref=f"M{mi}.T{ti}",
                    weight=round(0.5 + rng.random() * 4.5, 4),
                    practicality=round(rng.random(), 4),
                    has_lab=not spec.internship and rng.random() > 0.55,
                )
            )
        modules.append(
            ModuleIn(
                ref=f"M{mi}",
                weight=round(0.5 + rng.random() * 4.5, 4),
                topics=topics,
            )
        )
    return modules


def skeleton_constraints(spec: SkeletonSpec) -> Constraints:
    """Ограничения солвера под шаблон ДОП / ДПП ПК (в т.ч. стажировка 256 ч)."""
    final_att = 2 if spec.total >= 16 else 0
    if spec.internship or (spec.kind == "dpp_pk" and spec.total == 256):
        return Constraints(
            total=spec.total,
            final_att=final_att,
            unit=1,
            self_study_only=True,
            min_practice_share=0.0,
            self_study_share=0.0,
            distance_share=0.0,
        )
    min_practice = 0.0
    if spec.kind == "dop" and spec.total >= 24:
        min_practice = 0.3
    return Constraints(
        total=spec.total,
        final_att=final_att,
        unit=1 if spec.total <= 144 else 2,
        self_study_only=False,
        min_practice_share=min_practice,
        self_study_share=0.15 if spec.kind == "dpp_pk" else 0.1,
        distance_share=0.0,
    )


def solve_skeleton(spec: SkeletonSpec) -> tuple[Plan, Constraints]:
    modules = build_skeleton_modules(spec)
    constraints = skeleton_constraints(spec)
    plan = solve(modules, constraints)
    return plan, constraints


def module_topic_totals(plan: Plan, modules: list[ModuleIn]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for module in modules:
        totals[module.ref] = sum(sum(plan.rows[t.ref].values()) for t in module.topics)
    return totals


def assert_skeleton_invariants(spec: SkeletonSpec, plan: Plan, constraints: Constraints) -> None:
    """Инварианты каркаса: строки, модули, ИА, календарь, стажировка."""
    modules = build_skeleton_modules(spec)
    totals = {a: sum(r[a] for r in plan.rows.values()) for a in ROW_KEYS}
    content = sum(totals.values())
    assert content + constraints.final_att == constraints.total
    assert set(plan.rows) == {t.ref for m in modules for t in m.topics}
    for row in plan.rows.values():
        assert set(row) == set(ROW_KEYS)
        assert all(h >= 0 for h in row.values())
        assert sum(row.values()) % constraints.unit == 0

    assert plan.proof and all(ok for _, ok, _ in plan.proof)
    mod_totals = module_topic_totals(plan, modules)
    for module in modules:
        assert mod_totals[module.ref] >= constraints.unit or len(module.topics) == 1

    if constraints.self_study_only:
        assert totals["lecture"] == totals["practice"] == totals["lab"] == 0
        assert totals["self_study"] + constraints.final_att == constraints.total

    if constraints.min_practice_share:
        required = math.ceil(constraints.min_practice_share * constraints.total)
        assert totals["practice"] + totals["lab"] >= required

    max_day = 4 if spec.internship or spec.max_hours_per_day <= 4 else spec.max_hours_per_day
    sessions = calendar(plan, constraints, max_day, days_per_week=5)
    day_hours: dict[int, int] = {}
    for _week, day, ref, hours in sessions:
        day_hours[day] = day_hours.get(day, 0) + hours
        if ref != "ИА":
            assert hours <= max_day
    for day, hours in day_hours.items():
        assert hours <= max_day or constraints.final_att > max_day

    ia_sessions = [h for _w, _d, ref, h in sessions if ref == "ИА"]
    assert sum(ia_sessions) == constraints.final_att

    again = solve(modules, constraints)
    assert again.rows == plan.rows


def solve_skeleton_safe(spec: SkeletonSpec) -> Plan | None:
    try:
        plan, _ = solve_skeleton(spec)
        return plan
    except HoursInfeasible:
        return None
