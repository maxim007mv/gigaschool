"""Фиксированная матрица объёмов 16–500 ч × ДОП/ДПП ПК: сходимость часов и календарь."""

from __future__ import annotations

import pytest

from karkas.domain.framework_skeleton import (
    EVAL_VOLUMES,
    SkeletonSpec,
    assert_skeleton_invariants,
    solve_skeleton,
)


@pytest.mark.parametrize("total", EVAL_VOLUMES)
@pytest.mark.parametrize("kind", ("dop", "dpp_pk"))
def test_skeleton_hour_convergence(total: int, kind: str) -> None:
    internship = kind == "dpp_pk" and total == 256
    spec = SkeletonSpec(
        total=total,
        kind=kind,
        seed=42,
        internship=internship,
        max_hours_per_day=4 if internship else 8,
    )
    plan, constraints = solve_skeleton(spec)
    assert_skeleton_invariants(spec, plan, constraints)


def test_tk5_internship_zero_contact() -> None:
    spec = SkeletonSpec(total=256, kind="dpp_pk", seed=7, internship=True, max_hours_per_day=4)
    plan, constraints = solve_skeleton(spec)
    totals = {k: sum(r[k] for r in plan.rows.values()) for k in ("lecture", "practice", "lab", "self_study")}
    assert totals["lecture"] == totals["practice"] == totals["lab"] == 0
    assert totals["self_study"] + constraints.final_att == 256
