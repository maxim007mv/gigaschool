"""Срез РО по теме для контентных промптов (S12/S13) — экономия токенов."""

from __future__ import annotations

from karkas.agent.pipeline import _topic_outcomes

OUTCOMES = [
    {"ref": "LO1.1", "type": "knowledge", "text": "Знает переменные"},
    {"ref": "LO1.2", "type": "skill", "text": "Пишет условия"},
    {"ref": "LO1.3", "type": "skill", "text": "Делает проект"},
]


def test_topic_gets_only_its_outcomes() -> None:
    result = _topic_outcomes(OUTCOMES, ["LO1.2"])
    assert [o["ref"] for o in result] == ["LO1.2"]


def test_topic_keeps_outcomes_in_original_order() -> None:
    result = _topic_outcomes(OUTCOMES, ["LO1.3", "LO1.1"])
    assert [o["ref"] for o in result] == ["LO1.1", "LO1.3"]


def test_topic_without_refs_falls_back_to_full_list() -> None:
    assert _topic_outcomes(OUTCOMES, []) == OUTCOMES


def test_unknown_refs_fall_back_to_full_list() -> None:
    assert _topic_outcomes(OUTCOMES, ["LO9.9"]) == OUTCOMES


def test_fallback_returns_copy_not_shared_list() -> None:
    result = _topic_outcomes(OUTCOMES, [])
    assert result == OUTCOMES and result is not OUTCOMES
