"""Юнит-тесты календарного графика (karkas/domain/calendar.py), Д4 §5.5, Д5 §6.

Планы берутся из солвера на параметрах тест-кейсов (точные числа таблицы 4.4);
режимы занятий повторяют чек-листы: ТК-1 — 8 занятий по 2 ч за 4 недели,
ТК-2 — 9 занятий за 3 недели, ТК-5 — 64 дня по ≤ 4 ч (≈ 2 месяца).
"""

from __future__ import annotations

import copy

import pytest

from karkas.domain.calendar import build_calendar, calendar
from karkas.domain.hours import (
    Constraints,
    HoursInfeasible,
    ModuleIn,
    Plan,
    TopicIn,
    solve,
)


# --- Помощники ---------------------------------------------------------------


def topic(ref: str, weight: float = 1.0, practicality: float = 0.5, has_lab: bool = False) -> TopicIn:
    return TopicIn(ref=ref, weight=weight, practicality=practicality, has_lab=has_lab)


def row(
    lecture: int = 0,
    practice: int = 0,
    lab: int = 0,
    self_study: int = 0,
    current_control: int = 0,
) -> dict[str, int]:
    """Строка плана с полным набором ключей."""
    return {
        "lecture": lecture,
        "practice": practice,
        "lab": lab,
        "self_study": self_study,
        "current_control": current_control,
    }


def case_tk1_plan() -> tuple[Plan, Constraints]:
    """ТК-1: 16 ч = 7 занятий по 2 ч + ИА 2 ч."""
    modules = [
        ModuleIn("M1", 4.0, [topic("T1.1"), topic("T1.2"), topic("T1.3"), topic("T1.4")]),
        ModuleIn(
            "M2",
            3.0,
            [topic("T2.1", practicality=0.9), topic("T2.2", practicality=0.9), topic("T2.3")],
        ),
    ]
    c = Constraints(total=16, final_att=2, unit=2, min_practice_share=0.5)
    return solve(modules, c), c


def case_tk2_plan() -> tuple[Plan, Constraints]:
    """ТК-2: 36 ч, ДОТ 8 ч."""
    modules = [
        ModuleIn("M1", 6.0, [topic("T1.1", 3, 0.9), topic("T1.2", 2, 0.9), topic("T1.3", 1, 0.5)]),
        ModuleIn(
            "M2",
            11.0,
            [
                topic("T2.1", 3, 0.9),
                topic("T2.2", 3, 0.9),
                topic("T2.3", 3, 0.9),
                topic("T2.4", 1, 0.5),
                topic("T2.5", 1, 0.5),
            ],
        ),
        ModuleIn("M3", 6.0, [topic("T3.1", 3, 0.9), topic("T3.2", 2, 0.9), topic("T3.3", 1, 0.5)]),
    ]
    c = Constraints(
        total=36,
        final_att=2,
        unit=1,
        min_practice_share=0.5,
        self_study_share=0.2,
        distance_share=0.3,
    )
    return solve(modules, c), c


def case_tk5_plan() -> tuple[Plan, Constraints]:
    """ТК-5: 256 ч = 254 ч СРС + ИА 2 ч (стажировка)."""
    topic_counts = [8, 6, 8, 9, 5, 7]
    weights = [39.0, 27.0, 39.0, 46.0, 27.0, 33.0]
    modules = [
        ModuleIn(f"M{i + 1}", weights[i], [topic(f"T{i + 1}.{j + 1}") for j in range(topic_counts[i])])
        for i in range(6)
    ]
    c = Constraints(total=256, final_att=2, unit=1, self_study_only=True)
    return solve(modules, c), c


def hours_per_day(sessions: list[tuple[int, int, str, int]]) -> dict[int, int]:
    """Сумма часов по каждому учебному дню."""
    result: dict[int, int] = {}
    for _, day, _, hours in sessions:
        result[day] = result.get(day, 0) + hours
    return result


def days_count(sessions: list[tuple[int, int, str, int]]) -> int:
    return max((s[1] for s in sessions), default=0)


def weeks_count(sessions: list[tuple[int, int, str, int]]) -> int:
    return max((s[0] for s in sessions), default=0)


def ia_sessions(sessions: list[tuple[int, int, str, int]]) -> list[tuple[int, int, str, int]]:
    return [s for s in sessions if s[2] == "ИА"]


# --- Тест-кейсы --------------------------------------------------------------


class TestTestCases:
    def test_tk1_eight_days_four_weeks(self) -> None:
        plan, c = case_tk1_plan()
        sessions = calendar(plan, c, max_per_day=2, days_per_week=2)
        assert sessions == [
            (1, 1, "T1.1", 2),
            (1, 2, "T1.2", 2),
            (2, 3, "T1.3", 2),
            (2, 4, "T1.4", 2),
            (3, 5, "T2.1", 2),
            (3, 6, "T2.2", 2),
            (4, 7, "T2.3", 2),
            (4, 8, "ИА", 2),
        ]
        assert days_count(sessions) == 8
        assert weeks_count(sessions) == 4
        assert max(hours_per_day(sessions).values()) <= 2
        assert sum(h for *_, h in sessions) == 16

    def test_tk2_nine_days_three_weeks(self) -> None:
        plan, c = case_tk2_plan()
        sessions = calendar(plan, c, max_per_day=4, days_per_week=3)
        assert days_count(sessions) == 9
        assert weeks_count(sessions) == 3
        assert sum(h for *_, h in sessions) == 36

    def test_tk5_sixty_four_days_ten_weeks(self) -> None:
        plan, c = case_tk5_plan()
        sessions = calendar(plan, c, max_per_day=4, days_per_week=7)
        days = days_count(sessions)
        assert days == 64
        assert 50 <= days <= 70  # чек-лист ТК5-4: ≈ 2 месяца
        assert weeks_count(sessions) == 10
        assert sum(h for *_, h in sessions) == 256
        per_day = hours_per_day(sessions)
        assert max(per_day.values()) <= 4
        assert all(per_day[d] == 4 for d in range(1, days + 1))  # ровно 4 ч каждый день
        assert ia_sessions(sessions) == [(10, 64, "ИА", 2)]

    def test_solver_plan_and_calendar_agree_on_total(self) -> None:
        for build, max_per_day, days_per_week in (
            (case_tk1_plan, 2, 2),
            (case_tk2_plan, 4, 3),
            (case_tk5_plan, 4, 7),
        ):
            plan, c = build()
            sessions = calendar(plan, c, max_per_day, days_per_week)
            assert sum(h for *_, h in sessions) == c.total
            assert max(hours_per_day(sessions).values()) <= max_per_day


# --- Итоговая аттестация -----------------------------------------------------


class TestFinalAttestation:
    def test_ia_is_not_split(self) -> None:
        plan = Plan(rows={"T1.1": row(lecture=3)})
        sessions = calendar(plan, Constraints(total=5, final_att=2), max_per_day=4)
        assert ia_sessions(sessions) == [(1, 2, "ИА", 2)]

    def test_ia_moves_to_next_day_if_no_room(self) -> None:
        # тема занимает 3 ч при норме 4 ч: в остатке дня только 1 ч — ИА переносится
        plan = Plan(rows={"T1.1": row(lecture=3)})
        sessions = calendar(plan, Constraints(total=5, final_att=2), max_per_day=4)
        assert sessions == [(1, 1, "T1.1", 3), (1, 2, "ИА", 2)]
        assert hours_per_day(sessions)[2] == 2

    def test_ia_uses_remainder_of_day_when_it_fits(self) -> None:
        plan = Plan(rows={"T1.1": row(lecture=2)})
        sessions = calendar(plan, Constraints(total=4, final_att=2), max_per_day=4)
        assert sessions == [(1, 1, "T1.1", 2), (1, 1, "ИА", 2)]
        assert hours_per_day(sessions) == {1: 4}

    def test_ia_larger_than_max_per_day_is_a_single_block(self) -> None:
        # задокументированное допущение: ИА не дробится и при final_att > max_per_day
        plan = Plan(rows={"T1.1": row(lecture=1)})
        sessions = calendar(plan, Constraints(total=4, final_att=3), max_per_day=2)
        assert sessions == [(1, 1, "T1.1", 1), (1, 2, "ИА", 3)]
        assert ia_sessions(sessions) == [(1, 2, "ИА", 3)]

    def test_ia_larger_than_max_per_day_starts_on_fresh_day(self) -> None:
        sessions = calendar(Plan(), Constraints(total=3, final_att=3), max_per_day=2)
        assert sessions == [(1, 1, "ИА", 3)]

    def test_ia_on_empty_plan(self) -> None:
        assert calendar(Plan(), Constraints(total=2, final_att=2), max_per_day=2) == [
            (1, 1, "ИА", 2)
        ]


# --- Краевые случаи и инварианты ---------------------------------------------


class TestEdgeCases:
    def test_empty_plan_without_final_attestation(self) -> None:
        assert calendar(Plan(), Constraints(total=0, final_att=0), max_per_day=4) == []

    def test_zero_rows_are_skipped(self) -> None:
        plan = Plan(rows={"T1.1": row(), "T1.2": row(self_study=0)})
        assert calendar(plan, Constraints(total=0, final_att=0), max_per_day=4) == []

    def test_days_are_continuous_and_weeks_follow_formula(self) -> None:
        plan, c = case_tk5_plan()
        sessions = calendar(plan, c, max_per_day=4, days_per_week=7)
        days = sorted({s[1] for s in sessions})
        assert days == list(range(1, days_count(sessions) + 1))
        assert all(week == (day - 1) // 7 + 1 for week, day, _, _ in sessions)

    def test_topic_order_matches_plan_rows(self) -> None:
        plan, c = case_tk1_plan()
        sessions = calendar(plan, c, max_per_day=2, days_per_week=2)
        refs = [ref for _, _, ref, _ in sessions if ref != "ИА"]
        assert refs == list(plan.rows)

    def test_calendar_does_not_mutate_plan(self) -> None:
        plan, c = case_tk2_plan()
        before = copy.deepcopy(plan)
        calendar(plan, c, max_per_day=4, days_per_week=3)
        assert plan.rows == before.rows
        assert plan.distance == before.distance
        assert plan.module_of == before.module_of
        assert plan.proof == before.proof

    def test_max_per_day_must_be_positive(self) -> None:
        plan, c = case_tk1_plan()
        with pytest.raises(HoursInfeasible, match="не меньше 1 ч"):
            calendar(plan, c, max_per_day=0)

    def test_days_per_week_must_be_positive(self) -> None:
        plan, c = case_tk1_plan()
        with pytest.raises(HoursInfeasible, match="дней в неделю"):
            calendar(plan, c, max_per_day=2, days_per_week=0)

    def test_build_calendar_alias(self) -> None:
        plan, c = case_tk1_plan()
        assert build_calendar(plan, c, max_per_day=2, days_per_week=2) == calendar(
            plan, c, max_per_day=2, days_per_week=2
        )
