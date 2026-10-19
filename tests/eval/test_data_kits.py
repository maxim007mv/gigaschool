"""Прогон чек-листов по JSON-комплектам из data/eval/ (минимальные фикстуры).

Минимальные фикстуры намеренно неполные: они проверяют структуру и арифметику,
но не содержат слайдов, семинарских заданий и части содержательных артефактов.
Ожидаемые провалы зафиксированы ниже, чтобы новые проверки не «зеленели» молча.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from karkas.domain.kit import KitV1
from karkas.eval.checklists import format_report, run_checklist
from karkas.eval.official_cases import OFFICIAL_CASES

DATA_EVAL = Path(__file__).resolve().parents[2] / "data" / "eval"

EXPECTED_FAILS: dict[str, set[str]] = {
    "tk1": {"TK1-6", "TK1-7", "TK1-8"},
    "tk2": {"TK2-6"},
    "tk3": {"TK3-2", "TK3-4", "TK3-6", "TK3-7", "TK3-8", "TK3-9"},
    "tk4": {"TK4-1", "TK4-2", "TK4-3", "TK4-4", "TK4-6", "TK4-8", "TK4-9", "TK4-10"},
    "tk5": {"TK5-7"},
}


def _discover_cases() -> list[tuple[str, Path]]:
    if not DATA_EVAL.is_dir():
        return []
    return [(p.stem.lower(), p) for p in sorted(DATA_EVAL.glob("tk*.json"))]


def test_eval_kits_from_data_dir() -> None:
    cases = _discover_cases()
    if not cases:
        pytest.skip("нет data/eval/tk*.json — положите комплекты из личного кабинета хакатона")
    for case_key, path in cases:
        raw = json.loads(path.read_text(encoding="utf-8"))
        kit_payload = raw["kit"] if isinstance(raw, dict) and "kit" in raw else raw
        kit = KitV1.model_validate(kit_payload)
        results = run_checklist(kit, case_key)
        official = OFFICIAL_CASES[case_key]
        prefix = f"TK{case_key[-1]}-"
        case_results = [r for r in results if r.item_id.startswith(prefix)]
        assert [r.item_id for r in case_results] == [item.item_id for item in official.checklist]
        failed = {r.item_id for r in results if not r.passed}
        assert failed == EXPECTED_FAILS[case_key], f"{path.name}:\n" + format_report(results)
        assert all("требует ручной проверки" not in r.detail for r in results), format_report(results)
