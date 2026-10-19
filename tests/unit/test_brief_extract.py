"""Извлечение слотов из брифа ТК-1."""

from __future__ import annotations

from karkas.domain.brief_extract import (
    extract_final_attestation,
    extract_program_title,
    extract_unit_hours,
    slots_from_brief,
)
from karkas.eval.official_cases import OFFICIAL_CASES


def test_tk1_brief_slots() -> None:
    brief = OFFICIAL_CASES["tk1"].request_text
    assert extract_program_title(brief) == "Первые шаги в Python"
    assert extract_unit_hours(brief) == 2
    slots = slots_from_brief(brief)
    assert slots.get("total_hours") == "16"
    assert "общеразвива" in slots.get("kind", "").lower() or "ДОП" in slots.get("kind", "")


def test_final_attestation_from_official_briefs() -> None:
    assert extract_final_attestation(OFFICIAL_CASES["tk1"].request_text) == "Проект/защита"
    assert extract_final_attestation(OFFICIAL_CASES["tk2"].request_text) == "Зачёт по портфолио"
    assert extract_final_attestation(OFFICIAL_CASES["tk3"].request_text) == "Проект/защита"
    # ТК-4 — неполный запрос: форма ИА появляется только в ответах методиста.
    assert extract_final_attestation(OFFICIAL_CASES["tk4"].request_text) is None
    assert extract_final_attestation(OFFICIAL_CASES["tk5"].request_text) == "Проект/защита"
