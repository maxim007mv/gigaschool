"""Извлечение слотов из брифа ТК-1."""

from __future__ import annotations

from karkas.domain.brief_extract import extract_program_title, extract_unit_hours, slots_from_brief
from karkas.eval.official_cases import OFFICIAL_CASES


def test_tk1_brief_slots() -> None:
    brief = OFFICIAL_CASES["tk1"].request_text
    assert extract_program_title(brief) == "Первые шаги в Python"
    assert extract_unit_hours(brief) == 2
    slots = slots_from_brief(brief)
    assert slots.get("total_hours") == "16"
    assert "общеразвива" in slots.get("kind", "").lower() or "ДОП" in slots.get("kind", "")
