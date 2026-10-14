"""karkas.domain.hours — детерминированный солвер академических часов (Д4 §5.4).

LLM предлагает только ВЕСА модулей/тем, «практичность» темы (0…1) и признак
лабораторной работы; распределение целых часов и все проверки выполняет этот
код. Результат воспроизводим: одинаковый вход → одинаковый выход.

Порядок solve():
    1. разбиение объёма содержания (total − final_att) по модулям методом
       наибольших остатков; нижняя граница модуля — 1 занятие на каждую его тему;
    2. разбиение часов модуля по темам (нижняя граница — 1 занятие на тему),
       в единицах кратности занятия (unit);
    3. разбиение часов темы по видам работ: СРС — по self_study_share, ЛБ —
       четверть контактной части для тем с has_lab, ПР — по «практичности»,
       остаток — лекции; для self_study_only весь объём темы — СРС;
    4. детерминированный ремонт минимальной доли практики: часы переносятся из
       лекций тем-доноров (по убыванию практичности, затем по ref);
    5. распределение дистанционных часов по лекциям тем с наименьшей
       практичностью (сортировка по практичности, затем по ref);
    6. _prove — доказательство инвариантов V-HRS-01/02/03/04/05/06/07/08
       (и V-HRS-09 при distance_share > 0); при нарушении — HoursInfeasible
       с текстом, понятным методисту.

Слои: domain — чистые функции без БД, HTTP и LLM. Модуль ничего не печатает.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "ACTS",
    "COMPENSATION_ORDER",
    "IA_REF",
    "ROW_KEYS",
    "Constraints",
    "HoursInfeasible",
    "ModuleIn",
    "Plan",
    "TopicIn",
    "largest_remainder",
    "rebalance",
    "solve",
]

# --- Константы алгоритма (без «магических чисел» в коде) ---------------------

ACTS: tuple[str, ...] = ("lecture", "practice", "lab", "self_study")
"""Виды работ эталонного контракта (без текущего контроля)."""

ROW_KEYS: tuple[str, ...] = ("lecture", "practice", "lab", "self_study", "current_control")
"""Полный набор ключей строки плана; нулевые виды работ хранятся явно."""

COMPENSATION_ORDER: tuple[str, ...] = ("practice", "lecture", "lab")
"""Порядок компенсации разницы при пересчёте с закреплёнными ячейками."""

IA_REF: str = "ИА"
"""Псевдо-ref итоговой аттестации в календарном графике."""

PR_SHARE_MIN: float = 0.10
"""Нижняя граница доли практики в контактной части темы."""

PR_SHARE_MAX: float = 0.90
"""Верхняя граница доли практики в контактной части темы."""

PR_SHARE_BASE: float = 0.25
"""Базовая доля практики при practicality = 0."""

PR_SHARE_SPAN: float = 0.60
"""Прирост доли практики на единицу practicality (0…1)."""

LAB_CONTACT_SHARE: float = 0.25
"""Доля контактной части темы, отдаваемая лабораторной работе при has_lab."""

MAX_TOTAL_HOURS: int = 2000
"""Верхняя граница объёма программы, ч (Д4 §10)."""

MAX_CELL_HOURS: int = 500
"""Верхняя граница часов одной ячейки (вид работ одной темы), ч."""


# --- Контракт (имена заморожены; их используют другие модули) ---------------


class HoursInfeasible(ValueError):
    """Ограничения несовместимы; message — объяснение для методиста."""


@dataclass
class TopicIn:
    """Вход темы: вес (доля в модуле), «практичность» и признак лабораторной."""

    ref: str
    weight: float = 1.0
    practicality: float = 0.5
    has_lab: bool = False


@dataclass
class ModuleIn:
    """Вход модуля: вес (доля в программе) и список тем."""

    ref: str
    weight: float
    topics: list[TopicIn] = field(default_factory=list)


@dataclass
class Constraints:
    """Ограничения программы, влияющие на распределение часов."""

    total: int
    final_att: int = 2
    unit: int = 1
    self_study_only: bool = False
    min_practice_share: float = 0.0
    self_study_share: float = 0.0
    distance_share: float = 0.0


@dataclass
class Plan:
    """Результат солвера: строки часов, ДОТ, привязка к модулям, доказательство."""

    rows: dict[str, dict[str, int]] = field(default_factory=dict)
    distance: dict[str, int] = field(default_factory=dict)
    module_of: dict[str, str] = field(default_factory=dict)
    proof: list[tuple[str, bool, str]] = field(default_factory=list)


# --- Внутренние помощники ----------------------------------------------------


def _check_finite(name: str, value: float) -> None:
    """Отклонить NaN/бесконечность во входных числах (методисту нужен внятный текст)."""
    if not math.isfinite(value):
        raise HoursInfeasible(f"Некорректное значение «{name}»: {value}")


def _row(
    *,
    lecture: int = 0,
    practice: int = 0,
    lab: int = 0,
    self_study: int = 0,
    current_control: int = 0,
) -> dict[str, int]:
    """Строка плана с полным набором ключей ROW_KEYS."""
    return {
        "lecture": lecture,
        "practice": practice,
        "lab": lab,
        "self_study": self_study,
        "current_control": current_control,
    }


def _validate_input(modules: list[ModuleIn], c: Constraints) -> None:
    """Проверить вход до распределения; ошибки — HoursInfeasible с текстом для методиста."""
    if c.unit < 1:
        raise HoursInfeasible(f"Кратность занятия {c.unit} ч должна быть не меньше 1 ч")
    if not (1 <= c.total <= MAX_TOTAL_HOURS):
        raise HoursInfeasible(f"Объём программы {c.total} ч вне диапазона 1…{MAX_TOTAL_HOURS} ч")
    if c.final_att < 0:
        raise HoursInfeasible(f"Итоговая аттестация {c.final_att} ч не может быть отрицательной")
    for name in ("min_practice_share", "self_study_share", "distance_share"):
        value = getattr(c, name)
        _check_finite(name, value)
        if not 0.0 <= value <= 1.0:
            raise HoursInfeasible(f"Доля «{name}» = {value} вне диапазона 0…1")
    if not modules:
        raise HoursInfeasible("Не передан ни один модуль — нечего распределять")
    seen_modules: set[str] = set()
    seen_topics: set[str] = set()
    for m in modules:
        if m.ref in seen_modules:
            raise HoursInfeasible(f"Повторяющийся ref модуля: {m.ref}")
        seen_modules.add(m.ref)
        _check_finite(f"вес модуля {m.ref}", m.weight)
        if m.weight < 0:
            raise HoursInfeasible(f"Вес модуля {m.ref} отрицательный: {m.weight}")
        if not m.topics:
            raise HoursInfeasible(f"Модуль {m.ref} без тем — добавьте хотя бы одну тему")
        for t in m.topics:
            if t.ref in seen_topics:
                raise HoursInfeasible(f"Повторяющийся ref темы: {t.ref}")
            seen_topics.add(t.ref)
            _check_finite(f"вес темы {t.ref}", t.weight)
            if t.weight < 0:
                raise HoursInfeasible(f"Вес темы {t.ref} отрицательный: {t.weight}")
            _check_finite(f"практичность темы {t.ref}", t.practicality)
            if not 0.0 <= t.practicality <= 1.0:
                raise HoursInfeasible(
                    f"«Практичность» темы {t.ref} = {t.practicality} вне диапазона 0…1"
                )


def _allocate_hours(modules: list[ModuleIn], c: Constraints) -> tuple[dict[str, int], dict[str, int]]:
    """Шаги 1–2: часы модулей и тем (в единицах кратности занятия).

    Возвращает (часы модулей, часы тем). Предполагает, что вход уже прошёл
    _validate_input и проверки содержания в solve(); вызов из _prove безопасен.
    """
    content = c.total - c.final_att
    units = content // c.unit
    m_units = largest_remainder(units, [m.weight for m in modules], [len(m.topics) for m in modules])
    module_hours: dict[str, int] = {}
    topic_hours: dict[str, int] = {}
    for m, mu in zip(modules, m_units):
        t_units = largest_remainder(mu, [t.weight for t in m.topics], [1] * len(m.topics))
        total_m = 0
        for t, tu in zip(m.topics, t_units):
            hours = tu * c.unit
            topic_hours[t.ref] = hours
            total_m += hours
        module_hours[m.ref] = total_m
    return module_hours, topic_hours


def _split_topic(hours: int, topic: TopicIn, c: Constraints) -> dict[str, int]:
    """Шаг 3: разбить часы темы по видам работ."""
    if c.self_study_only:
        return _row(self_study=hours)
    srs = round(hours * c.self_study_share)
    contact = hours - srs
    lab = round(contact * LAB_CONTACT_SHARE) if topic.has_lab else 0
    share = min(PR_SHARE_MAX, max(PR_SHARE_MIN, PR_SHARE_BASE + PR_SHARE_SPAN * topic.practicality))
    practice = round((contact - lab) * share)
    lecture = contact - lab - practice
    return _row(lecture=lecture, practice=practice, lab=lab, self_study=srs)


def _repair_practice_share(plan: Plan, modules: list[ModuleIn], c: Constraints) -> None:
    """Шаг 4: довести долю ПР+ЛБ до min_practice_share, перенося часы из лекций.

    Доноры перебираются детерминированно: по убыванию «практичности», затем по ref;
    из темы-донора переносится по одному часу, пока требование не выполнено.
    """
    need = math.ceil(c.min_practice_share * c.total) - sum(
        r["practice"] + r["lab"] for r in plan.rows.values()
    )
    donors = sorted((t for m in modules for t in m.topics), key=lambda t: (-t.practicality, t.ref))
    while need > 0:
        donor = next((t for t in donors if plan.rows[t.ref]["lecture"] > 0), None)
        if donor is None:
            raise HoursInfeasible(
                "Нельзя набрать требуемую долю практики: лекционных часов для переноса не осталось"
            )
        plan.rows[donor.ref]["lecture"] -= 1
        plan.rows[donor.ref]["practice"] += 1
        need -= 1


def _distribute_distance(plan: Plan, modules: list[ModuleIn], c: Constraints) -> None:
    """Шаг 5: дистанционные часы берутся из лекций наименее практичных тем."""
    contact = sum(r["lecture"] + r["practice"] + r["lab"] for r in plan.rows.values())
    need = round(c.distance_share * contact)
    plan.distance.clear()
    for t in sorted((t for m in modules for t in m.topics), key=lambda t: (t.practicality, t.ref)):
        take = min(need, plan.rows[t.ref]["lecture"])
        plan.distance[t.ref] = take
        need -= take
    if need > 0:
        raise HoursInfeasible(
            "Доля дистанционных часов больше объёма лекций; уточните, какие практики идут дистанционно"
        )


def _check_cell_limits(rows: dict[str, dict[str, int]]) -> None:
    """Лимит часов одной ячейки (вид работ одной темы) — MAX_CELL_HOURS."""
    for ref, row in rows.items():
        for activity, hours in row.items():
            if hours > MAX_CELL_HOURS:
                raise HoursInfeasible(
                    f"Часы ячейки {ref}.{activity} = {hours} ч превышают лимит {MAX_CELL_HOURS} ч — "
                    "разделите объём темы или добавьте темы"
                )


def _apply_locks(
    plan: Plan,
    modules: list[ModuleIn],
    c: Constraints,
    locked_cells: dict[str, dict[str, int]],
) -> None:
    """Наложить закреплённые значения и скомпенсировать разницу внутри темы.

    Закреплённые ячейки не меняются. Разница «итог строки после закрепления −
    плановый итог темы» компенсируется незакреплёнными видами работ той же темы
    в порядке practice → lecture → lab. Если компенсировать нельзя — HoursInfeasible
    (часы не могут стать отрицательными: уменьшение ограничено доступным запасом).
    """
    known = {t.ref for m in modules for t in m.topics}
    expected_hours = _allocate_hours(modules, c)[1]
    for ref, cells in locked_cells.items():
        if ref not in known:
            raise HoursInfeasible(f"Закрепление ссылается на несуществующую тему {ref}")
        row = plan.rows[ref]
        for activity, hours in cells.items():
            if activity not in ROW_KEYS:
                raise HoursInfeasible(f"Неизвестный вид работ «{activity}» в закреплении темы {ref}")
            if isinstance(hours, bool) or not isinstance(hours, int):
                raise HoursInfeasible(
                    f"Часы закрепления темы {ref} ({activity}) должны быть целым числом, получено {hours!r}"
                )
            if not 0 <= hours <= MAX_CELL_HOURS:
                raise HoursInfeasible(
                    f"Закреплённые часы темы {ref} ({activity}) = {hours} вне диапазона 0…{MAX_CELL_HOURS}"
                )
            row[activity] = hours
        delta = sum(row.values()) - expected_hours[ref]
        if delta:
            for activity in COMPENSATION_ORDER:
                if activity in cells:
                    continue  # закреплённые ячейки не трогаем
                if delta > 0:
                    move = min(delta, row[activity])
                    row[activity] -= move
                    delta -= move
                else:
                    row[activity] += -delta
                    delta = 0
                if delta == 0:
                    break
            if delta:
                raise HoursInfeasible(
                    f"Закреплённые часы темы {ref} нельзя скомпенсировать видами работ "
                    f"{'/'.join(COMPENSATION_ORDER)}: незакреплённого запаса не хватает"
                )
    for ref, row in plan.rows.items():
        for activity, hours in row.items():
            if hours < 0:
                raise HoursInfeasible(f"Отрицательные часы темы {ref} ({activity}): {hours}")
    _check_cell_limits(plan.rows)


def _prove(plan: Plan, modules: list[ModuleIn], c: Constraints) -> None:
    """Собрать доказательство инвариантов V-HRS и упасть на первом нарушении.

    Проверяются: V-HRS-01 (Σ строк + ИА = объём), V-HRS-02 (часы у каждой темы),
    V-HRS-03 (часы у каждого модуля), V-HRS-04 (стажировка — только СРС),
    V-HRS-05 (минимальная доля практики), V-HRS-06 (Σ видов работ = итог строки),
    V-HRS-07 (Σ тем = часы модуля), V-HRS-08 (кратность занятия),
    V-HRS-09 (дистанционные часы отделены и не превышают лекции).
    """
    rows = plan.rows
    module_hours, topic_hours = _allocate_hours(modules, c)
    totals = {a: sum(r.get(a, 0) for r in rows.values()) for a in ROW_KEYS}
    rows_total = sum(totals.values())
    grand = rows_total + c.final_att

    plan.proof.clear()
    p = plan.proof.append

    p(
        (
            "V-HRS-01 Σ строк + ИА = объём",
            grand == c.total,
            f"{rows_total} + {c.final_att} = {grand} (запрошено {c.total})",
        )
    )

    missing = sorted(set(topic_hours) - set(rows))
    empty_rows = sorted(ref for ref, r in rows.items() if sum(r.values()) <= 0)
    p(
        (
            "V-HRS-02 у каждой темы есть часы",
            not missing and not empty_rows,
            f"проблемные темы: {(missing + empty_rows) or 'нет'}",
        )
    )

    empty_modules = sorted(
        m.ref for m in modules if sum(sum(rows[t.ref].values()) for t in m.topics) <= 0
    )
    p(("V-HRS-03 у каждого модуля есть часы", not empty_modules, f"без часов: {empty_modules or 'нет'}"))

    if c.self_study_only:
        contact = totals["lecture"] + totals["practice"] + totals["lab"]
        p(
            (
                "V-HRS-04 ЛК/ПР/ЛБ = 0 (стажировка)",
                contact == 0,
                f"ЛК {totals['lecture']}, ПР {totals['practice']}, "
                f"ЛБ {totals['lab']}, СРС {totals['self_study']}",
            )
        )

    if c.min_practice_share:
        required = math.ceil(c.min_practice_share * c.total)
        actual = totals["practice"] + totals["lab"]
        p(
            (
                "V-HRS-05 доля практики",
                actual >= required,
                f"ПР+ЛБ {actual} ч при требуемых {required} ч (доля {c.min_practice_share:.0%})",
            )
        )

    row_mismatch = sorted(ref for ref, r in rows.items() if sum(r.values()) != topic_hours.get(ref))
    p(
        (
            "V-HRS-06 Σ видов работ = «Всего» по строке",
            not row_mismatch,
            f"расхождения: {row_mismatch or 'нет'}",
        )
    )

    module_mismatch = [
        f"{m.ref}: {sum(sum(rows[t.ref].values()) for t in m.topics)} ≠ {module_hours[m.ref]}"
        for m in modules
        if sum(sum(rows[t.ref].values()) for t in m.topics) != module_hours[m.ref]
    ]
    p(("V-HRS-07 Σ тем = часы модуля", not module_mismatch, f"расхождения: {module_mismatch or 'нет'}"))

    bad_unit = sorted(ref for ref, r in rows.items() if sum(r.values()) % c.unit)
    p(
        (
            "V-HRS-08 часы темы кратны занятию",
            not bad_unit,
            f"не кратны {c.unit} ч: {bad_unit or 'нет'}",
        )
    )

    if c.distance_share:
        dist_total = sum(plan.distance.values())
        expected_dist = round(c.distance_share * (totals["lecture"] + totals["practice"] + totals["lab"]))
        excess = sorted(ref for ref, d in plan.distance.items() if d > rows[ref]["lecture"])
        p(
            (
                "V-HRS-09 дистанционные часы ≤ лекций",
                dist_total == expected_dist and not excess,
                f"ДОТ {dist_total} ч (план {expected_dist} ч)"
                + (f", больше лекций у {excess}" if excess else ""),
            )
        )

    for rule, ok, message in plan.proof:
        if not ok:
            raise HoursInfeasible(f"{rule}: {message}")


# --- Публичный интерфейс -----------------------------------------------------


def largest_remainder(total: int, weights: list[float], mins: list[int]) -> list[int]:
    """Целочисленное распределение total пропорционально weights с нижними границами.

    Метод наибольших остатков (Гамильтона): сначала каждому участнику отдаётся
    его минимум mins, затем свободные часы делятся пропорционально весам, а
    остаток раздаётся по убыванию дробной части квоты; при равных остатках — по
    индексу (стабильная сортировка), поэтому результат полностью детерминирован.
    Нулевые/отрицательные веса не получают квоту; при нулевой сумме весов
    свободные часы делятся поровну.
    """
    if len(weights) != len(mins):
        raise ValueError(f"Длины weights ({len(weights)}) и mins ({len(mins)}) не совпадают")
    if isinstance(total, bool) or not isinstance(total, int):
        raise ValueError(f"total должен быть целым числом, получено {total!r}")
    if any(isinstance(m, bool) or not isinstance(m, int) for m in mins):
        raise ValueError(f"Нижние границы должны быть целыми числами: {mins}")
    if total < 0:
        raise ValueError(f"total должен быть неотрицательным, получено {total}")
    if any(m < 0 for m in mins):
        raise ValueError(f"Нижние границы не могут быть отрицательными: {mins}")
    if sum(mins) > total:
        raise HoursInfeasible(f"Минимальные часы ({sum(mins)}) больше доступных ({total})")
    free = total - sum(mins)
    clean = [w if math.isfinite(w) and w > 0 else 0.0 for w in weights]
    try:
        weight_sum = math.fsum(clean)
    except OverflowError as exc:
        raise HoursInfeasible("Веса тем/модулей слишком велики — проверьте входные данные") from exc
    if weight_sum <= 0:
        clean = [1.0] * len(clean)
        weight_sum = float(len(clean))
    quotas = [free * w / weight_sum for w in clean]
    if any(not math.isfinite(q) for q in quotas):
        raise HoursInfeasible("Не удалось распределить часы: веса дают нечисловые квоты")
    base = [math.floor(q) for q in quotas]
    rest = free - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-(quotas[i] - base[i]), i))
    for i in order[:rest]:
        base[i] += 1
    return [b + m for b, m in zip(base, mins)]


def solve(modules: list[ModuleIn], c: Constraints) -> Plan:
    """Распределить часы по модулям, темам и видам работ и доказать инварианты.

    Возвращает Plan: rows[ref] содержит все ключи ROW_KEYS («lecture», «practice»,
    «lab», «self_study», «current_control»), distance — дистанционные часы тем,
    module_of — привязку тем к модулям, proof — список (правило, ок, пояснение).
    При несовместимых ограничениях бросает HoursInfeasible с объяснением для
    методиста.
    """
    _validate_input(modules, c)
    content = c.total - c.final_att
    if content <= 0:
        raise HoursInfeasible(
            f"{content} ч содержания не делится на кратность занятия {c.unit} ч: "
            f"итоговая аттестация {c.final_att} ч при объёме {c.total} ч"
        )
    if content % c.unit:
        raise HoursInfeasible(f"{content} ч содержания не делится на кратность занятия {c.unit} ч")
    units = content // c.unit
    n_topics = sum(len(m.topics) for m in modules)
    if n_topics > units:
        raise HoursInfeasible(
            f"Тем ({n_topics}) больше, чем занятий по {c.unit} ч ({units}) — объедините темы"
        )

    _, topic_hours = _allocate_hours(modules, c)
    plan = Plan()
    for m in modules:
        for t in m.topics:
            plan.module_of[t.ref] = m.ref
            plan.rows[t.ref] = _split_topic(topic_hours[t.ref], t, c)

    _repair_practice_share(plan, modules, c)
    _check_cell_limits(plan.rows)
    _distribute_distance(plan, modules, c)
    _prove(plan, modules, c)
    return plan


def rebalance(
    modules: list[ModuleIn],
    c: Constraints,
    locked_cells: dict[str, dict[str, int]] | None = None,
) -> Plan:
    """Пересчитать план часов, закрепив заданные ячейки.

    Порядок: solve обычным путём → наложить закреплённые значения → скомпенсировать
    разницу в незакреплённых видах работ той же темы (practice → lecture → lab) →
    пересчитать дистанционные часы → доказать инварианты заново. Закреплённые
    значения не меняются и участвуют в доказательствах (V-HRS-05/06/09 видят
    фактические часы строки). При невозможности компенсации или нарушении
    инвариантов бросает HoursInfeasible.

    Ожидаемое применение: методист закрепляет часы видов работ, суммарные часы
    тем и модулей при этом сохраняются.
    """
    plan = solve(modules, c)
    if locked_cells:
        _apply_locks(plan, modules, c, locked_cells)
        _distribute_distance(plan, modules, c)
        _prove(plan, modules, c)
    return plan
