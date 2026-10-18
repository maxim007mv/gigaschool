"""ТК4-2: объём в часах, а не «примерно месяц» без числа."""

from __future__ import annotations

from karkas.domain.intake_slots import parse_total_hours, validate_clarification_answer


def test_parse_rejects_month_without_number() -> None:
    assert parse_total_hours("примерно месяц") is None
    assert parse_total_hours("месяц") is None


def test_parse_accepts_hours_in_text() -> None:
    assert parse_total_hours("72 часа") == 72
    assert parse_total_hours("около 36") == 36
    assert parse_total_hours("с 2024 года, 72 ч") == 72


def test_validate_total_hours_message() -> None:
    assert validate_clarification_answer("total_hours", "примерно месяц") is not None
    assert validate_clarification_answer("total_hours", "72") is None
