"""Property-тесты солвера часов (Hypothesis), Д4 §11 «Property-based солвера».

Для случайных объёмов 16–500 ч, 1–20 модулей, 1–8 тем в модуле, случайных весов,
«практичности» и ограничений: если solve вернул план (не бросил HoursInfeasible),
обязаны выполняться инварианты V-HRS-01/04/05/08, кратность занятия, отсутствие
отрицательных часов и полный детерминизм повторного вызова. Ожидаемые
HoursInfeasible (несовместимые ограничения) ошибкой не считаются — их тексты
проверяются в tests/unit/test_hours.py.
"""

from __future__ import annotations

import math

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from karkas.domain.hours import (
    ROW_KEYS,
    Constraints,
    HoursInfeasible,
    ModuleIn,
    Plan,
    TopicIn,
    solve,
)

_UNITS = [1, 2, 3, 4]
_SHARES = [0.0, 0.3, 0.5, 0.6, 0.7]
_SELF_STUDY_SHARES = [0.0, 0.15, 0.2, 0.3, 0.5]
_DISTANCE_SHARES = [0.0, 0.1, 0.3, 0.5]

_FLOAT_PARAMS = {"allow_nan": False, "allow_infinity": False}


@st.composite
def programs(draw: st.DrawFn) -> tuple[list[ModuleIn], Constraints]:
    """Случайная программа: модули, темы, веса и ограничения (примеры S07–S08)."""
    total = draw(st.integers(min_value=16, max_value=500))
    final_att = draw(st.integers(min_value=0, max_value=min(8, total - 1)))
    unit = draw(st.sampled_from(_UNITS))
    self_study_only = draw(st.booleans())
    min_practice_share = 0.0 if self_study_only else draw(st.sampled_from(_SHARES))
    self_study_share = 0.0 if self_study_only else draw(st.sampled_from(_SELF_STUDY_SHARES))
    distance_share = 0.0 if self_study_only else draw(st.sampled_from(_DISTANCE_SHARES))
    n_modules = draw(st.integers(min_value=1, max_value=20))
    modules: list[ModuleIn] = []
    for i in range(1, n_modules + 1):
        n_topics = draw(st.integers(min_value=1, max_value=8))
        topics = [
            TopicIn(
                ref=f"T{i}.{j}",
                weight=draw(st.floats(min_value=0.0, max_value=5.0, **_FLOAT_PARAMS)),
                practicality=draw(st.floats(min_value=0.0, max_value=1.0, **_FLOAT_PARAMS)),
                has_lab=draw(st.booleans()),
            )
            for j in range(1, n_topics + 1)
        ]
        modules.append(
            ModuleIn(
                ref=f"M{i}",
                weight=draw(st.floats(min_value=0.0, max_value=5.0, **_FLOAT_PARAMS)),
                topics=topics,
            )
        )
    c = Constraints(
        total=total,
        final_att=final_att,
        unit=unit,
        self_study_only=self_study_only,
        min_practice_share=min_practice_share,
        self_study_share=self_study_share,
        distance_share=distance_share,
    )
    return modules, c


def act_totals(plan: Plan) -> dict[str, int]:
    """Итоги по видам работ по всему плану."""
    return {a: sum(r[a] for r in plan.rows.values()) for a in ROW_KEYS}


@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(programs())
def test_solver_invariants_on_random_inputs(program: tuple[list[ModuleIn], Constraints]) -> None:
    """Инварианты солвера на случайных входах и полный детерминизм."""
    modules, c = program
    try:
        plan = solve(modules, c)
    except HoursInfeasible:
        return  # несовместимые ограничения — ожидаемо, тексты проверяются юнит-тестами

    # V-HRS-01: Σ строк + ИА = запрошенный объём
    totals = act_totals(plan)
    assert sum(totals.values()) + c.final_att == c.total

    # Строки: полный набор ключей, неотрицательные часы, ровно темы входа
    assert set(plan.rows) == {t.ref for m in modules for t in m.topics}
    for row in plan.rows.values():
        assert set(row) == set(ROW_KEYS)
        assert all(hours >= 0 for hours in row.values())

    # V-HRS-08: часы каждой темы кратны длительности занятия
    assert all(sum(row.values()) % c.unit == 0 for row in plan.rows.values())

    # V-HRS-04: стажировка — без контактной работы (ЛК = ПР = ЛБ = 0)
    if c.self_study_only:
        assert totals["lecture"] == totals["practice"] == totals["lab"] == 0

    # V-HRS-05: минимальная доля практики из запроса
    if c.min_practice_share:
        required = math.ceil(c.min_practice_share * c.total)
        assert totals["practice"] + totals["lab"] >= required

    # V-HRS-09: дистанционные часы равны доле контактной работы и не больше лекций
    if c.distance_share:
        contact = totals["lecture"] + totals["practice"] + totals["lab"]
        expected = round(c.distance_share * contact)
        assert sum(plan.distance.values()) <= expected
        assert all(plan.distance.get(ref, 0) <= row["lecture"] for ref, row in plan.rows.items())

    # Доказательство собрано и не содержит нарушений
    assert plan.proof and all(ok for _, ok, _ in plan.proof)

    # Детерминизм: повторный вызов даёт идентичный результат
    again = solve(modules, c)
    assert again.rows == plan.rows
    assert again.distance == plan.distance
    assert again.module_of == plan.module_of
    assert again.proof == plan.proof
