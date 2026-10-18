#!/usr/bin/env python3
"""Записать data/eval/tk1.json … tk5.json из karkas.eval.reference_kits."""

from __future__ import annotations

import json
from pathlib import Path

from karkas.eval.official_cases import OFFICIAL_CASES
from karkas.eval.reference_kits import BUILDERS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "eval"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for case_id, builder in BUILDERS.items():
        case = OFFICIAL_CASES[case_id]
        kit = builder()
        payload = {
            "meta": {
                "case_id": case.case_id,
                "title": case.title,
                "request_text": case.request_text,
                "checklist": [{"item_id": i.item_id, "text": i.text} for i in case.checklist],
                "source": "data/eval/test_cases_official.txt",
            },
            "kit": kit.model_dump(mode="json"),
        }
        path = OUT / f"{case_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("wrote", path)


if __name__ == "__main__":
    main()
