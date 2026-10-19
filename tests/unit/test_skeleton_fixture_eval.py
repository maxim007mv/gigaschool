"""run_eval: skeleton fixture помечает content-dependent пункты как N/A."""

from __future__ import annotations

from karkas.eval.checklists import run_checklist
from karkas.eval.reference_kits import build_tk3_kit


def test_skeleton_fixture_marks_tk3_content_items_na() -> None:
    kit = build_tk3_kit()
    strict = {r.item_id: r.passed for r in run_checklist(kit, "tk3", skeleton_fixture=False)}
    relaxed = {r.item_id: r.passed for r in run_checklist(kit, "tk3", skeleton_fixture=True)}
    assert strict.get("TK3-7") is False
    assert relaxed.get("TK3-7") is True
