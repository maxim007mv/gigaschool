"""Чек-листы на минимальном эталонном KitV1 (без LLM и БД)."""

from __future__ import annotations

from karkas.eval.checklists import run_common_checklist
from tests.unit.test_validation_suite import build_clean_kit


def test_common_checklist_on_clean_kit() -> None:
    kit = build_clean_kit()
    results = run_common_checklist(kit)
    assert results, "ожидается хотя бы один пункт чек-листа"
    failed = [r for r in results if not r.passed]
    assert not failed, "; ".join(f"{r.item_id}: {r.detail}" for r in failed)
