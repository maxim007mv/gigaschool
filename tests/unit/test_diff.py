"""Тесты сравнения снимков KitV1 (экран «Версии»)."""

from __future__ import annotations

from karkas.domain.diff import diff_snapshots


def _snapshot(title: str = "Тема", hours: int = 2) -> dict:
    return {
        "framework": {
            "competencies": [{"ref": "C1", "title": "Компетенция"}],
            "modules": [
                {
                    "ref": "M1",
                    "number": 1,
                    "title": "Модуль",
                    "topics": [{"ref": "T1.1", "title": title, "workload": {"lecture": hours}}],
                }
            ],
        },
        "content": {
            "assessments": [{"ref": "Q-001", "stem": "Вопрос?"}],
            "sources": [],
        },
    }


def test_no_changes() -> None:
    assert diff_snapshots(_snapshot(), _snapshot()) == {"changed": [], "added": [], "removed": []}


def test_changed_topic() -> None:
    # Модуль содержит тему, поэтому меняются оба элемента — это ожидаемо.
    result = diff_snapshots(_snapshot(), _snapshot(title="Другая тема"))
    assert result["changed"] == ["M1", "T1.1"]
    assert result["added"] == [] and result["removed"] == []


def test_added_and_removed() -> None:
    left = _snapshot()
    right = _snapshot()
    right["content"]["assessments"] = []
    right["content"]["sources"] = [{"ref": "SRC-01", "citation": "Книга"}]
    result = diff_snapshots(left, right)
    assert result["added"] == ["SRC-01"]
    assert result["removed"] == ["Q-001"]
