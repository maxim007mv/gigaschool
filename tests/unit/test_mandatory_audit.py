"""Пункты «Обязательно» из кейса — артефакты в репозитории."""

from __future__ import annotations

from karkas.eval.mandatory_audit import audit_mandatory


def test_mandatory_evidence_present() -> None:
    rows = audit_mandatory()
    gaps = [item.id for item, ok, _ in rows if not ok]
    assert not gaps, f"нет артефактов: {gaps}"
