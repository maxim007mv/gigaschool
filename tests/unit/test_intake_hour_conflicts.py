"""Противоречивые объёмы в брифе — предупреждение методисту, не копирование."""

from __future__ import annotations

from karkas.domain.intake_slots import detect_hour_total_conflicts


def test_tk5_allows_254_plus_2_equals_256() -> None:
    text = "256 часов: 254 ч самостоятельной работы и 2 ч итоговой аттестации"
    assert detect_hour_total_conflicts(text) == []


def test_conflicting_totals_flagged() -> None:
    text = "Программа на 256 часов по образцу 248 ч"
    msgs = detect_hour_total_conflicts(text)
    assert len(msgs) == 1
    assert "256" in msgs[0] and "248" in msgs[0]
