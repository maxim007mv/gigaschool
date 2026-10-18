"""Юнит-тесты солвера часов (karkas/domain/hours.py), Д4 §5.4, Д5 §6/таблица 4.4.

Пять кейсов воспроизводят ТОЧНЫЕ числа таблицы 4.4 «Выход солвера»: веса модулей
и тем заданы вручную как пример выхода навыка S07 (в продукте их предлагает LLM,
а распределение часов выполняет этот код).
"""

from __future__ import annotations

import pytest

from karkas.domain.hours import (
    ROW_KEYS,
    Constraints,
    HoursInfeasible,
    ModuleIn,
    Plan,
    TopicIn,
    largest_remainder,
    rebalance,
    solve,
)


# --- Помощники ---------------------------------------------------------------


def topic(ref: str, weight: float = 1.0, practicality: float = 0.5, has_lab: bool = False) -> TopicIn:
    """Собрать тему с именованными параметрами (короче в тестах)."""
    return TopicIn(ref=ref, weight=weight, practicality=practicality, has_lab=has_lab)


def act_totals(plan: Plan) -> dict[str, int]:
    """Итоги по видам работ по всему плану."""
    return {a: sum(r[a] for r in plan.rows.values()) for a in ROW_KEYS}


def module_totals(plan: Plan, modules: list[ModuleIn]) -> dict[str, int]:
    """Часы каждого модуля (сумма строк его тем)."""
    return {m.ref: sum(sum(plan.rows[t.ref].values()) for t in m.topics) for m in modules}


def check_success(plan: Plan, modules: list[ModuleIn], c: Constraints) -> None:
    """Общие проверки удачного решения: суммы, неотрицательность, доказательство."""
    assert all(ok for _, ok, _ in plan.proof), [row for row in plan.proof if not row[1]]
    assert set(plan.rows) == {t.ref for m in modules for t in m.topics}
    for row in plan.rows.values():
        assert set(row) == set(ROW_KEYS)
        assert all(hours >= 0 for hours in row.values())
    assert sum(act_totals(plan).values()) + c.final_att == c.total


def has_rule(plan: Plan, code: str) -> bool:
    """Есть ли в доказательстве правило с данным кодом (например, V-HRS-04)."""
    return any(rule.startswith(code) for rule, _, _ in plan.proof)


# --- Тест-кейсы (точные числа таблицы 4.4, Д5 §6) ----------------------------


def case_tk1() -> tuple[list[ModuleIn], Constraints]:
    """ТК-1 «Python 16 ч (ДОП)»: ЛК5/ПР9/ЛБ0/СРС0, ИА 2, M1:8 M2:6."""
    modules = [
        ModuleIn("M1", 4.0, [topic("T1.1"), topic("T1.2"), topic("T1.3"), topic("T1.4")]),
        ModuleIn(
            "M2",
            3.0,
            [topic("T2.1", practicality=0.9), topic("T2.2", practicality=0.9), topic("T2.3")],
        ),
    ]
    return modules, Constraints(total=16, final_att=2, unit=2, min_practice_share=0.5)


def case_tk2() -> tuple[list[ModuleIn], Constraints]:
    """ТК-2 «ИИ в работе учителя 36 ч»: ЛК9/ПР18/ЛБ0/СРС7, ДОТ 8, M1:9 M2:16 M3:9."""
    modules = [
        ModuleIn(
            "M1",
            6.0,
            [topic("T1.1", 3, 0.9), topic("T1.2", 2, 0.9), topic("T1.3", 1, 0.5)],
        ),
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
        ModuleIn(
            "M3",
            6.0,
            [topic("T3.1", 3, 0.9), topic("T3.2", 2, 0.9), topic("T3.3", 1, 0.5)],
        ),
    ]
    c = Constraints(
        total=36,
        final_att=2,
        unit=1,
        min_practice_share=0.5,
        self_study_share=0.2,
        distance_share=0.3,
    )
    return modules, c


def case_tk3() -> tuple[list[ModuleIn], Constraints]:
    """ТК-3 «Анализ данных 72 ч»: ЛК19/ПР35/ЛБ1/СРС13, M1:9 M2:18 M3:11 M4:11 M5:9 M6:10."""
    modules = [
        ModuleIn("M1", 7.0, [topic("T1.1", 3, 0.5), topic("T1.2", 4, 0.8)]),
        ModuleIn(
            "M2",
            14.0,
            [
                topic("T2.1", 3, 0.5),
                topic("T2.2", 3, 0.5),
                topic("T2.3", 4, 0.6),
                topic("T2.4", 4, 0.8),
            ],
        ),
        ModuleIn("M3", 8.0, [topic("T3.1", 3, 0.5), topic("T3.2", 4, 0.8), topic("T3.3", 1, 0.5)]),
        ModuleIn(
            "M4",
            8.0,
            [topic("T4.1", 3, 0.9, has_lab=True), topic("T4.2", 4, 0.8), topic("T4.3", 1, 0.5)],
        ),
        ModuleIn("M5", 6.0, [topic("T5.1", 4, 0.6), topic("T5.2", 1, 0.5), topic("T5.3", 1, 0.5)]),
        ModuleIn("M6", 7.0, [topic("T6.1", 3, 0.5), topic("T6.2", 3, 0.5), topic("T6.3", 1, 0.5)]),
    ]
    c = Constraints(total=72, final_att=4, unit=1, min_practice_share=0.5, self_study_share=0.2)
    return modules, c


def case_tk4() -> tuple[list[ModuleIn], Constraints]:
    """ТК-4 «Кибербезопасность 72 ч»: ЛК24/ПР40/ЛБ4/СРС0, M1:12 M2:13 M3:16 M4:16 M5:11."""
    modules = [
        ModuleIn("M1", 10.0, [topic("T1.1", 5, 0.9, has_lab=True), topic("T1.2", 5, 0.5)]),
        ModuleIn(
            "M2",
            10.0,
            [topic("T2.1", 4, 0.9), topic("T2.2", 4, 0.9), topic("T2.3", 2, 0.3)],
        ),
        ModuleIn(
            "M3",
            12.0,
            [
                topic("T3.1", 3, 0.9),
                topic("T3.2", 3, 0.9),
                topic("T3.3", 3, 0.5),
                topic("T3.4", 3, 0.5),
            ],
        ),
        ModuleIn("M4", 14.0, [topic("T4.1", 7, 0.7), topic("T4.2", 7, 0.3)]),
        ModuleIn("M5", 9.0, [topic("T5.1", 5, 0.9, has_lab=True), topic("T5.2", 4, 0.9)]),
    ]
    return modules, Constraints(total=72, final_att=4, unit=1, min_practice_share=0.5)


def case_tk5() -> tuple[list[ModuleIn], Constraints]:
    """ТК-5 «DevOps-стажировка 256 ч»: только СРС 254, M1:47 M2:33 M3:47 M4:55 M5:32 M6:40."""
    topic_counts = [8, 6, 8, 9, 5, 7]
    weights = [39.0, 27.0, 39.0, 46.0, 27.0, 33.0]
    modules = [
        ModuleIn(f"M{i + 1}", weights[i], [topic(f"T{i + 1}.{j + 1}") for j in range(topic_counts[i])])
        for i in range(6)
    ]
    return modules, Constraints(total=256, final_att=2, unit=1, self_study_only=True)


# --- largest_remainder -------------------------------------------------------


class TestLargestRemainder:
    def test_proportional_split_by_weights(self) -> None:
        assert largest_remainder(9, [1.0, 2.0], [0, 0]) == [3, 6]

    def test_mins_shift_free_hours(self) -> None:
        # свободных часов 10 − (2+1) = 7; квоты 5.25 и 1.75 → остаток уходит второму
        assert largest_remainder(10, [3.0, 1.0], [2, 1]) == [7, 3]

    def test_rest_distributed_in_index_order_on_equal_remainders(self) -> None:
        assert largest_remainder(7, [1.0, 1.0, 1.0], [0, 0, 0]) == [3, 2, 2]

    def test_total_equal_to_mins(self) -> None:
        assert largest_remainder(5, [1.0, 2.0], [3, 2]) == [3, 2]

    def test_scale_invariance_and_determinism(self) -> None:
        first = largest_remainder(10, [1.0, 1.0, 1.0], [0, 0, 0])
        assert first == [4, 3, 3]
        assert largest_remainder(10, [1.0, 1.0, 1.0], [0, 0, 0]) == first
        assert largest_remainder(10, [5.0, 5.0, 5.0], [0, 0, 0]) == first

    def test_zero_weights_split_evenly(self) -> None:
        assert largest_remainder(4, [0.0, 0.0], [0, 0]) == [2, 2]

    def test_mins_over_total_raises_with_message(self) -> None:
        with pytest.raises(HoursInfeasible) as exc:
            largest_remainder(5, [1.0, 1.0], [3, 3])
        assert str(exc.value) == "Минимальные часы (6) больше доступных (5)"

    def test_negative_mins_raise_value_error(self) -> None:
        with pytest.raises(ValueError):
            largest_remainder(5, [1.0], [-1])

    def test_negative_total_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="неотрицательным"):
            largest_remainder(-1, [1.0], [0])

    def test_length_mismatch_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            largest_remainder(5, [1.0, 1.0], [0])

    def test_non_integer_arguments_raise_value_error(self) -> None:
        with pytest.raises(ValueError, match="целым числом"):
            largest_remainder(5.0, [1.0], [0])  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="целыми числами"):
            largest_remainder(5, [1.0], [0.0])  # type: ignore[list-item]


# --- Пять тест-кейсов: точные числа таблицы 4.4 ------------------------------


class TestFiveCases:
    def test_tk1_python_16(self) -> None:
        modules, c = case_tk1()
        plan = solve(modules, c)
        check_success(plan, modules, c)
        assert act_totals(plan) == {
            "lecture": 5,
            "practice": 9,
            "lab": 0,
            "self_study": 0,
            "current_control": 0,
        }
        assert module_totals(plan, modules) == {"M1": 8, "M2": 6}
        assert all(sum(row.values()) == 2 for row in plan.rows.values())  # 7 занятий по 2 ч
        assert set(plan.distance.values()) == {0}  # без ДОТ
        assert has_rule(plan, "V-HRS-08")

    def test_tk2_ai_for_teacher_36(self) -> None:
        modules, c = case_tk2()
        plan = solve(modules, c)
        check_success(plan, modules, c)
        assert act_totals(plan) == {
            "lecture": 9,
            "practice": 18,
            "lab": 0,
            "self_study": 7,
            "current_control": 0,
        }
        assert module_totals(plan, modules) == {"M1": 9, "M2": 16, "M3": 9}
        assert sum(plan.distance.values()) == 8  # ДОТ
        assert has_rule(plan, "V-HRS-09")
        assert all(plan.distance[ref] <= row["lecture"] for ref, row in plan.rows.items())

    def test_tk3_data_analysis_72(self) -> None:
        modules, c = case_tk3()
        plan = solve(modules, c)
        check_success(plan, modules, c)
        assert act_totals(plan) == {
            "lecture": 19,
            "practice": 35,
            "lab": 1,
            "self_study": 13,
            "current_control": 0,
        }
        assert module_totals(plan, modules) == {
            "M1": 9,
            "M2": 18,
            "M3": 11,
            "M4": 11,
            "M5": 9,
            "M6": 10,
        }
        assert plan.rows["T4.1"]["lab"] == 1  # единственная лабораторная
        assert sum(plan.distance.values()) == 0

    def test_tk4_cybersecurity_72(self) -> None:
        modules, c = case_tk4()
        plan = solve(modules, c)
        check_success(plan, modules, c)
        assert act_totals(plan) == {
            "lecture": 24,
            "practice": 40,
            "lab": 4,
            "self_study": 0,
            "current_control": 0,
        }
        assert module_totals(plan, modules) == {"M1": 12, "M2": 13, "M3": 16, "M4": 16, "M5": 11}
        assert plan.rows["T1.1"]["lab"] == 2 and plan.rows["T5.1"]["lab"] == 2

    def test_tk5_devops_internship_256(self) -> None:
        modules, c = case_tk5()
        plan = solve(modules, c)
        check_success(plan, modules, c)
        totals = act_totals(plan)
        assert totals["self_study"] == 254
        assert totals["lecture"] == totals["practice"] == totals["lab"] == 0
        assert module_totals(plan, modules) == {
            "M1": 47,
            "M2": 33,
            "M3": 47,
            "M4": 55,
            "M5": 32,
            "M6": 40,
        }
        assert all(row["self_study"] == sum(row.values()) for row in plan.rows.values())
        assert has_rule(plan, "V-HRS-04")


# --- Ошибки ограничений: текст для методиста ---------------------------------


class TestInfeasible:
    def test_nine_topics_in_sixteen_hours(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic(f"T1.{i}") for i in range(1, 10)])]
        with pytest.raises(HoursInfeasible) as exc:
            solve(modules, Constraints(total=16, final_att=2, unit=2))
        assert str(exc.value) == "Тем (9) больше, чем занятий по 2 ч (7) — объедините темы"

    def test_content_not_multiple_of_unit(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1")])]
        with pytest.raises(HoursInfeasible) as exc:
            solve(modules, Constraints(total=16, final_att=3, unit=2))  # 13 ч
        assert str(exc.value) == "13 ч содержания не делится на кратность занятия 2 ч"

    def test_zero_content(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1")])]
        with pytest.raises(HoursInfeasible) as exc:
            solve(modules, Constraints(total=2, final_att=2))
        assert str(exc.value).startswith("0 ч содержания не делится на кратность занятия 1 ч")

    def test_practice_share_unreachable(self) -> None:
        # содержание 8 ч: даже перенеся в практику все лекции, 100 % от 10 ч не набрать
        modules = [ModuleIn("M1", 1.0, [topic("T1.1", practicality=0.5)])]
        with pytest.raises(HoursInfeasible) as exc:
            solve(modules, Constraints(total=10, final_att=2, min_practice_share=1.0))
        assert "Нельзя набрать требуемую долю практики" in str(exc.value)

    def test_distance_more_than_lectures(self) -> None:
        # контакт 10 ч, лекций всего 2 ч, а доля ДОТ требует 6 ч
        modules = [ModuleIn("M1", 1.0, [topic("T1.1", practicality=0.9)])]
        with pytest.raises(HoursInfeasible) as exc:
            solve(modules, Constraints(total=12, final_att=2, distance_share=0.6))
        assert "Доля дистанционных часов больше объёма лекций" in str(exc.value)

    def test_no_modules(self) -> None:
        with pytest.raises(HoursInfeasible, match="ни один модуль"):
            solve([], Constraints(total=16))

    def test_module_without_topics(self) -> None:
        with pytest.raises(HoursInfeasible, match="M1 без тем"):
            solve([ModuleIn("M1", 1.0, [])], Constraints(total=16))

    def test_duplicate_topic_ref(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1")]), ModuleIn("M2", 1.0, [topic("T1.1")])]
        with pytest.raises(HoursInfeasible, match="Повторяющийся ref темы: T1.1"):
            solve(modules, Constraints(total=16))

    def test_duplicate_module_ref(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1")]), ModuleIn("M1", 1.0, [topic("T2.1")])]
        with pytest.raises(HoursInfeasible, match="Повторяющийся ref модуля: M1"):
            solve(modules, Constraints(total=16))

    def test_bad_unit(self) -> None:
        with pytest.raises(HoursInfeasible, match="Кратность занятия 0 ч"):
            solve([ModuleIn("M1", 1.0, [topic("T1.1")])], Constraints(total=16, unit=0))

    def test_total_out_of_range(self) -> None:
        modules = [
            ModuleIn("M1", 1.0, [topic(f"T1.{i}") for i in range(1, 3)]),
        ]
        with pytest.raises(HoursInfeasible, match="вне диапазона 1…2000 ч"):
            solve(modules, Constraints(total=0, final_att=0))
        with pytest.raises(HoursInfeasible, match="вне диапазона 1…2000 ч"):
            solve(modules, Constraints(total=2001))

    def test_negative_final_att(self) -> None:
        with pytest.raises(HoursInfeasible, match="не может быть отрицательной"):
            solve([ModuleIn("M1", 1.0, [topic("T1.1")])], Constraints(total=16, final_att=-1))

    def test_practicality_out_of_range(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1", practicality=1.5)])]
        with pytest.raises(HoursInfeasible, match="«Практичность» темы T1.1"):
            solve(modules, Constraints(total=16))

    def test_share_out_of_range(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1")])]
        with pytest.raises(HoursInfeasible, match="вне диапазона 0…1"):
            solve(modules, Constraints(total=16, min_practice_share=1.5))

    def test_negative_weight(self) -> None:
        modules = [ModuleIn("M1", -1.0, [topic("T1.1")])]
        with pytest.raises(HoursInfeasible, match="Вес модуля M1 отрицательный"):
            solve(modules, Constraints(total=16))

    def test_negative_topic_weight(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1", weight=-0.5)])]
        with pytest.raises(HoursInfeasible, match="Вес темы T1.1 отрицательный"):
            solve(modules, Constraints(total=16))

    def test_nan_practicality(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1", practicality=float("nan"))])]
        with pytest.raises(HoursInfeasible, match="Некорректное значение"):
            solve(modules, Constraints(total=16))

    def test_nan_share(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1")])]
        with pytest.raises(HoursInfeasible, match="Некорректное значение"):
            solve(modules, Constraints(total=16, min_practice_share=float("nan")))

    def test_split_topic_share_is_clamped(self) -> None:
        # страховка шага 3: доля практики ограничена 0.1…0.9 даже вне диапазона 0…1
        # (валидация такого входа не пропускает, но helper обязан оставаться безопасным)
        from karkas.domain.hours import _split_topic  # noqa: PLC0415 — приватный helper, покрываем страховку

        c = Constraints(total=10, final_att=0)
        assert _split_topic(10, TopicIn("T1.1", practicality=-1.0), c)["practice"] == 1  # min 0.1
        assert _split_topic(10, TopicIn("T1.1", practicality=2.0), c)["practice"] == 9  # max 0.9

    def test_cell_hours_limit(self) -> None:
        modules = [ModuleIn("M1", 1.0, [topic("T1.1")])]
        with pytest.raises(HoursInfeasible, match="превышают лимит 500 ч"):
            solve(modules, Constraints(total=1000, final_att=0))


# --- rebalance: закреплённые ячейки ------------------------------------------


class TestRebalance:
    def test_without_locks_matches_solve(self) -> None:
        modules, c = case_tk3()
        expected = solve(modules, c)
        assert rebalance(modules, c).rows == expected.rows
        assert rebalance(modules, c, {}).proof == expected.proof
        assert rebalance(modules, c, None).rows == expected.rows

    def test_locked_cell_preserved_and_compensated(self) -> None:
        # T1.1 (6 ч): lecture 1 / practice 3 / lab 2 → закрепляем practice 5,
        # разница уходит в lecture (1→0) и lab (2→1), итог темы не меняется
        modules, c = case_tk4()
        plan = rebalance(modules, c, {"T1.1": {"practice": 5}})
        assert plan.rows["T1.1"] == {
            "lecture": 0,
            "practice": 5,
            "lab": 1,
            "self_study": 0,
            "current_control": 0,
        }
        assert all(ok for _, ok, _ in plan.proof)
        assert sum(act_totals(plan).values()) + c.final_att == c.total
        assert module_totals(plan, modules) == {"M1": 12, "M2": 13, "M3": 16, "M4": 16, "M5": 11}

    def test_locked_lecture_moves_hours_to_practice(self) -> None:
        modules, c = case_tk4()
        plan = rebalance(modules, c, {"T1.1": {"lecture": 0}})
        row = plan.rows["T1.1"]
        assert row["lecture"] == 0
        assert row["practice"] == 4  # первый незакреплённый вид в порядке компенсации
        assert sum(row.values()) == 6

    def test_locked_lab_falls_through_to_practice(self) -> None:
        modules, c = case_tk4()
        plan = rebalance(modules, c, {"T1.1": {"lab": 0}})
        assert plan.rows["T1.1"] == {
            "lecture": 1,
            "practice": 5,
            "lab": 0,
            "self_study": 0,
            "current_control": 0,
        }

    def test_locked_self_study_is_compensated_by_practice(self) -> None:
        modules, c = case_tk4()
        plan = rebalance(modules, c, {"T1.1": {"self_study": 1}})
        assert plan.rows["T1.1"] == {
            "lecture": 1,
            "practice": 2,
            "lab": 2,
            "self_study": 1,
            "current_control": 0,
        }
        assert has_rule(plan, "V-HRS-06")

    def test_uncompensable_locks_raise(self) -> None:
        modules, c = case_tk4()
        with pytest.raises(HoursInfeasible, match="нельзя скомпенсировать"):
            rebalance(modules, c, {"T1.1": {"practice": 2, "lecture": 5}})

    def test_self_study_only_lock_raises(self) -> None:
        modules, c = case_tk5()
        with pytest.raises(HoursInfeasible, match="нельзя скомпенсировать"):
            rebalance(modules, c, {"T1.1": {"lecture": 1}})

    def test_lock_breaking_practice_share_raises_on_proof(self) -> None:
        # в ТК-3 ПР+ЛБ ровно 36 ч = требуемые 50 %; снижение практики ломает V-HRS-05
        modules, c = case_tk3()
        with pytest.raises(HoursInfeasible, match="V-HRS-05"):
            rebalance(modules, c, {"T1.1": {"practice": 1}})

    def test_lab_compensates_when_practice_and_lecture_locked(self) -> None:
        modules, c = case_tk3()
        plan = rebalance(modules, c, {"T1.1": {"practice": 1, "lecture": 1}})
        assert plan.rows["T1.1"] == {
            "lecture": 1,
            "practice": 1,
            "lab": 1,
            "self_study": 1,
            "current_control": 0,
        }
        assert act_totals(plan)["lab"] == 2  # 1 базовый + 1 компенсационный

    def test_distance_recomputed_after_lock(self) -> None:
        modules, c = case_tk2()
        plan = rebalance(modules, c, {"T1.1": {"lecture": 0}})
        assert plan.rows["T1.1"]["lecture"] == 0
        assert plan.distance["T1.1"] == 0  # лекций нет — дистанционных часов тоже
        assert sum(plan.distance.values()) == 8
        assert all(ok for _, ok, _ in plan.proof)

    def test_lock_making_distance_infeasible_raises(self) -> None:
        modules, c = case_tk2()
        with pytest.raises(HoursInfeasible, match="Доля дистанционных часов"):
            rebalance(modules, c, {"T2.1": {"lecture": 0}, "T2.2": {"lecture": 0}})

    def test_unknown_ref_raises(self) -> None:
        modules, c = case_tk4()
        with pytest.raises(HoursInfeasible, match="несуществующую тему T9.9"):
            rebalance(modules, c, {"T9.9": {"practice": 1}})

    def test_compensation_beyond_cell_limit_raises(self) -> None:
        # 600-часовой теме закрепляем нули в practice/lecture — вся разница уходит
        # в lab и упирается в лимит ячейки 500 ч
        modules = [ModuleIn("M1", 1.0, [topic("T1.1")])]
        c = Constraints(total=600, final_att=0)
        with pytest.raises(HoursInfeasible, match="превышают лимит 500 ч"):
            rebalance(modules, c, {"T1.1": {"practice": 0, "lecture": 0}})

    def test_unknown_activity_raises(self) -> None:
        modules, c = case_tk4()
        with pytest.raises(HoursInfeasible, match="Неизвестный вид работ"):
            rebalance(modules, c, {"T1.1": {"lectures": 1}})

    @pytest.mark.parametrize("value", [-1, 501, 1.5, True])
    def test_bad_locked_value_raises(self, value: object) -> None:
        modules, c = case_tk4()
        with pytest.raises(HoursInfeasible):
            rebalance(modules, c, {"T1.1": {"practice": value}})  # type: ignore[dict-item]

    def test_rebalance_is_deterministic(self) -> None:
        modules, c = case_tk4()
        locks = {"T1.1": {"practice": 5}, "T3.1": {"lecture": 0}}
        first = rebalance(modules, c, locks)
        second = rebalance(modules, c, locks)
        assert first.rows == second.rows
        assert first.proof == second.proof
        assert first.rows["T1.1"]["practice"] == 5
        assert first.rows["T3.1"]["lecture"] == 0
