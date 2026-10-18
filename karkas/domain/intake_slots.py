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


def validate_clarification_answer(slot: str, value: str) -> str | None:
    """Сообщение об ошибке по-русски или None, если ответ допустим."""
    if slot == "total_hours":
        if parse_total_hours(value) is None:
            return "Укажите объём программы в академических часах числом (например, 72), а не только срок «месяц»."
    if slot == "kind" and len(value.strip()) < 3:
        return "Уточните тип программы: дополнительная общеразвивающая или повышение квалификации."
    return None
