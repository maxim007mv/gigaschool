"""Полнота официальных чек-листов ТК-1…ТК-5 и результат на эталонных примерах."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from karkas.domain.kit import KitV1
from karkas.eval.checklists import format_report, run_checklist
from karkas.eval.official_cases import OFFICIAL_CASES, OFFICIAL_TXT
from karkas.eval.reference_kits import BUILDERS

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = {
    "tk1": ROOT / "examples" / "tk1" / "kit_tk1.json",
    "tk2": ROOT / "examples" / "tk2" / "kit_tk2.json",
}
EXAMPLE_FAILS: dict[str, set[str]] = {
    # Примеры после kit_fixup проходят полные официальные чек-листы.
    "tk1": set(),
    "tk2": set(),
}


def _official_items_from_file() -> dict[str, list[str]]:
    raw = OFFICIAL_TXT.read_text(encoding="utf-8")
    chunks = re.split(r"(?m)^Запрос\s+(\d+)\.\s+", raw)
    parsed: dict[str, list[str]] = {}
    for index in range(1, len(chunks), 2):
        case_id = f"tk{chunks[index]}"
        block = chunks[index + 1]
        match = re.search(r"Эталонный чек-лист\s*\n(.*?)(?=\nЗапрос\s+\d+\.|\Z)", block, flags=re.DOTALL)
        if match:
            parsed[case_id] = [line.strip() for line in match.group(1).splitlines() if line.strip()]
    return parsed


def test_official_cases_match_file() -> None:
    parsed = _official_items_from_file()
    assert set(parsed) == set(OFFICIAL_CASES)
    for case_id, texts in parsed.items():
        case = OFFICIAL_CASES[case_id]
        assert len(case.checklist) == len(texts), case_id
        assert [item.text for item in case.checklist] == texts, case_id
        prefix = f"TK{case_id[-1]}-"
        expected_ids = [f"{prefix}{number}" for number in range(1, len(texts) + 1)]
        assert [item.item_id for item in case.checklist] == expected_ids, case_id


def test_all_cases_have_every_official_item() -> None:
    for case_id, builder in BUILDERS.items():
        kit = builder()
        results = run_checklist(kit, case_id)
        prefix = f"TK{case_id[-1]}-"
        case_results = [result for result in results if result.item_id.startswith(prefix)]
        expected_ids = [item.item_id for item in OFFICIAL_CASES[case_id].checklist]
        assert [result.item_id for result in case_results] == expected_ids, case_id
        assert len(results) == 3 + len(expected_ids), case_id


@pytest.mark.parametrize("case_id", sorted(EXAMPLES))
def test_reference_examples_checklist(case_id: str) -> None:
    path = EXAMPLES[case_id]
    if not path.is_file():
        pytest.skip(f"нет {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    kit = KitV1.model_validate(raw["kit"] if isinstance(raw, dict) and "kit" in raw else raw)
    results = run_checklist(kit, case_id)
    prefix = f"TK{case_id[-1]}-"
    case_results = [result for result in results if result.item_id.startswith(prefix)]
    assert [result.item_id for result in case_results] == [item.item_id for item in OFFICIAL_CASES[case_id].checklist]
    failed = {result.item_id for result in results if not result.passed}
    assert failed == EXAMPLE_FAILS[case_id], f"{path.name}:\n" + format_report(results)
    assert all("требует ручной проверки" not in result.detail for result in results), format_report(results)
