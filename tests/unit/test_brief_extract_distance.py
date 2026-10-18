"""Доля ДОТ из брифа — только при явном упоминании дистанционных технологий."""

from __future__ import annotations

from karkas.domain.brief_extract import extract_distance_share_pct


def test_part_time_without_dot_returns_none() -> None:
    brief = (
        "Нужна программа повышения квалификации на 72 часа «Анализ данных на Python». "
        "Формат очно-заочный, срок 4 недели."
    )
    assert extract_distance_share_pct(brief, "Очно-заочно") is None


def test_part_time_with_dot_returns_share() -> None:
    brief = "36 часов, очно-заочно с применением дистанционных технологий."
    assert extract_distance_share_pct(brief) == 30.0
