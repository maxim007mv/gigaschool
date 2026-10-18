"""karkas.domain.calendar — календарный учебный график (Д4 §5.5).

Раскладывает часы тем по учебным дням с ограничением «не более max_per_day часов
в день» (max_per_day не превышается ни одним занятием). Итоговая аттестация
(ref «ИА») НЕ дробится: если её нельзя уместить в остаток текущего дня, занятие
переносится на следующий день и выводится одним блоком.

Допущение (явно задокументировано): если final_att больше max_per_day, ИА
выводится одним блоком на отдельном дне — правило «не дробить ИА» важнее нормы
дня, а методист видит аттестацию целиком. Во всех остальных случаях сумма часов
любого дня не превышает max_per_day.

Нумерация: дни — непрерывно с 1; недели — (день − 1) // days_per_week + 1.
"""

from __future__ import annotations

from karkas.domain.hours import IA_REF, Constraints, HoursInfeasible, Plan

__all__ = ["build_calendar", "calendar"]


def _week_of(day: int, days_per_week: int) -> int:
    """Номер недели для дня (нумерация с 1)."""
    return (day - 1) // days_per_week + 1


def calendar(
    plan: Plan,
    c: Constraints,
    max_per_day: int,
    days_per_week: int = 5,
) -> list[tuple[int, int, str, int]]:
    """Раскладка часов по дням: (неделя, день, T-ref|ИА, часы).

    Темы идут в порядке строк плана, ИА — последней. Занятие (строка вывода)
    не превышает max_per_day часов; ИА не дробится и при необходимости переносится
    на следующий день (см. допущение о final_att > max_per_day в docstring модуля).
    """
    if max_per_day < 1:
        raise HoursInfeasible(f"Ограничение «не более {max_per_day} ч в день» должно быть не меньше 1 ч")
    if days_per_week < 1:
        raise HoursInfeasible(f"Число учебных дней в неделю ({days_per_week}) должно быть не меньше 1")

    sessions: list[tuple[int, int, str, int]] = []
    day = 1
    left = max_per_day
    queue: list[tuple[str, int]] = [
        (ref, sum(row.values())) for ref, row in plan.rows.items() if sum(row.values()) > 0
    ]
    if c.final_att > 0:
        queue.append((IA_REF, c.final_att))

    for ref, hours in queue:
        if ref == IA_REF and hours > max_per_day:
            # Допущение: ИА не дробится — отдельный блок, даже если он больше нормы дня.
            if left != max_per_day:
                day += 1
            sessions.append((_week_of(day, days_per_week), day, ref, hours))
            day += 1
            left = max_per_day
            continue
        while hours > 0:
            if ref == IA_REF and left < hours and left != max_per_day:
                day += 1  # ИА не дробится: переносим занятие на следующий день
                left = max_per_day
            take = min(hours, left)
            sessions.append((_week_of(day, days_per_week), day, ref, take))
            hours -= take
            left -= take
            if left == 0:
                day += 1
                left = max_per_day
    return sessions


def build_calendar(
    plan: Plan,
    c: Constraints,
    max_per_day: int,
    days_per_week: int = 5,
) -> list[tuple[int, int, str, int]]:
    """Алиас calendar() для читаемости вызовов."""
    return calendar(plan, c, max_per_day, days_per_week)
