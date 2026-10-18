"""Прогон чек-листов по JSON-комплектам из data/eval/ (если каталог есть)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from karkas.domain.kit import KitV1
from karkas.eval.checklists import format_report, run_checklist

DATA_EVAL = Path(__file__).resolve().parents[2] / "data" / "eval"


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
        failed = [r for r in results if not r.passed]
        assert not failed, f"{path.name}:\n" + format_report(results)
