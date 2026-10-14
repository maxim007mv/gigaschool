"""Тесты ремонта доли практики в солвере (закрывают слепую зону из ревью тестов).

Мутационная проверка показала: смена порядка доноров ремонта не ловилась ни одним
тестом, а property-тест мог «проглотить» деградацию через `except HoursInfeasible`.
Здесь зафиксирован точный детерминированный результат и то, что при выполнимых
ограничениях ремонт выполняется, а не падает.
"""

from __future__ import annotations

import pytest

from karkas.domain.hours import Constraints, HoursInfeasible, ModuleIn, TopicIn, solve


def test_repair_donor_order_is_deterministic() -> None:
    """Ремонт доли практики: донор — самая «практичная» тема с лекциями.

    Программа 4 ч (unit=1): две темы по 2 ч, практичность 0.4 и 0.1.
    Исходно: A(ЛК1/ПР1), B(ЛК1/ПР1), Σ практики 2; минимум 75% (3 ч) →
    ремонт переносит ровно 1 лекционный час, и это час темы A (0.4 > 0.1).
    Если порядок доноров поменять, тест падает (проверено мутацией A2 в ревью).
    """
    modules = [
        ModuleIn(
            ref="M1",
            weight=1.0,
            topics=[
                TopicIn(ref="T1.1", weight=1.0, practicality=0.4),
                TopicIn(ref="T1.2", weight=1.0, practicality=0.1),
            ],
        )
    ]
    constraints = Constraints(total=4, final_att=0, unit=1, min_practice_share=0.75)
    plan = solve(modules, constraints)

    assert plan.rows["T1.1"] == {"lecture": 0, "practice": 2, "lab": 0, "self_study": 0, "current_control": 0}
    assert plan.rows["T1.2"] == {"lecture": 1, "practice": 1, "lab": 0, "self_study": 0, "current_control": 0}
    practice = plan.rows["T1.1"]["practice"] + plan.rows["T1.2"]["practice"]
    assert practice >= 3  # V-HRS-05: 75% от 4 ч
    assert all(ok for _, ok, _ in plan.proof), plan.proof


def test_repair_never_silently_skips_feasible_cases() -> None:
    """При выполнимых ограничениях ремонт выполняется, а не бросает HoursInfeasible."""
    for total in range(8, 41, 4):
        modules = [
            ModuleIn(
                ref="M1",
                weight=1.0,
                topics=[
                    TopicIn(ref="T1.1", weight=1.0, practicality=0.2),
                    TopicIn(ref="T1.2", weight=1.0, practicality=0.5),
                    TopicIn(ref="T1.3", weight=1.0, practicality=0.8),
                ],
            )
        ]
        constraints = Constraints(total=total, final_att=2, unit=1, min_practice_share=0.5)
        try:
            plan = solve(modules, constraints)
        except HoursInfeasible as exc:  # допустимо только с понятной причиной
            raise AssertionError(f"total={total}: неожиданная HoursInfeasible: {exc}") from exc

        practice_and_lab = sum(
            row["practice"] + row["lab"] for row in plan.rows.values()
        )
        need = -(-50 * total // 100)  # ceil(0.5 * total)
        assert practice_and_lab >= need, f"total={total}: практики {practice_and_lab} < {need}"
        assert sum(sum(row.values()) for row in plan.rows.values()) + 2 == total
