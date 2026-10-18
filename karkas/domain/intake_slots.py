"""Разбор ответов на слоты уточнений (Д4 §5.2, ТК4-2)."""

from __future__ import annotations

import re

from karkas.settings import settings

_DURATION_ONLY = re.compile(
    r"^(примерно\s+)?(месяц|недел|квартал|год|полгода)\b",
    re.IGNORECASE,
)


def parse_total_hours(value: str | None) -> int | None:
    """Извлечь объём в часах; «примерно месяц» без числа — None (ТК4-2)."""
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    if _DURATION_ONLY.search(text) and not re.search(r"\d", text):
        return None
    hours_adjacent = re.search(r"(\d{1,4})\s*ч", text, re.IGNORECASE)
    if hours_adjacent:
        return max(1, min(settings.total_hours_max, int(hours_adjacent.group(1))))
    nums = [int(n) for n in re.findall(r"\d{1,4}", text.replace(" ", ""))]
    # Кейс: 16–500 ч; год вроде 2024 не считаем объёмом программы.
    plausible = [n for n in nums if 16 <= n <= min(500, settings.total_hours_max)]
    if plausible:
        return plausible[-1]
    if len(nums) == 1 and nums[0] <= settings.total_hours_max:
        return nums[0]
    return None


_HOUR_CLAIM = re.compile(
    r"(?P<n>\d{1,3})\s*(?:ч(?:ас(?:а|ов)?)?\.?|акад(?:емических)?\s*ч)",
    re.IGNORECASE,
)


def detect_hour_total_conflicts(text: str | None) -> list[str]:
    """Найти противоречивые объёмы в запросе (ТК-5: 256 vs 248 в образце)."""
    if not text or not str(text).strip():
        return []
    body = str(text)
    hour_values: list[int] = []
    for match in _HOUR_CLAIM.finditer(body):
        hour_values.append(int(match.group("n")))
    if not hour_values:
        nums = [
            int(n) for n in re.findall(r"\b(\d{2,3})\b", body) if 16 <= int(n) <= min(500, settings.total_hours_max)
        ]
        hour_values.extend(nums)
    unique_all = sorted(set(hour_values))
    program_totals = [v for v in unique_all if 16 <= v <= min(500, settings.total_hours_max)]
    if len(program_totals) <= 1:
        return []
    top = max(program_totals)
    components = [v for v in unique_all if v != top]
    if components and top == sum(components):
        return []
    unique = program_totals
    return [
        "В запросе указаны разные объёмы программы ("
        + ", ".join(f"{h} ч" for h in unique)
        + ") — уточните у заказчика; в каркас не копируем противоречие."
    ]


def validate_clarification_answer(slot: str, value: str) -> str | None:
    """Сообщение об ошибке по-русски или None, если ответ допустим."""
    if slot == "total_hours" and parse_total_hours(value) is None:
        return "Укажите объём программы в академических часах числом (например, 72), а не только срок «месяц»."
    if slot == "kind" and len(value.strip()) < 3:
        return "Уточните тип программы: дополнительная общеразвивающая или повышение квалификации."
    return None
