#!/usr/bin/env python3
"""Прогон эталонных чек-листов по JSON в data/eval/ (открытые ТК-1…ТК-5 хаба).

Пример:
  .venv/bin/python scripts/run_eval.py
  .venv/bin/python scripts/run_eval.py data/eval/tk5.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from karkas.domain.kit import KitV1
from karkas.eval.checklists import format_report, run_checklist
from karkas.eval.official_cases import OFFICIAL_CASES

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "eval"


def _load_case(path: Path) -> tuple[str, KitV1, dict | None]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "kit" in raw:
        meta = raw.get("meta") or {}
        case_key = str(meta.get("case_id") or path.stem).lower()
        kit = KitV1.model_validate(raw["kit"])
        return case_key, kit, meta
    case_key = path.stem.lower()
    kit = KitV1.model_validate(raw)
    return case_key, kit, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eval чек-листы КАРКАС (ТК-1…ТК-5)")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Пути к JSON; по умолчанию — все data/eval/tk*.json",
    )
    parser.add_argument(
        "--case",
        help="Ключ кейса (tk1…tk5); по умолчанию — из meta.case_id или имя файла",
    )
    args = parser.parse_args(argv)

    paths: list[Path]
    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        if not DEFAULT_DIR.is_dir():
            print(f"Каталог {DEFAULT_DIR} не найден.", file=sys.stderr)
            return 2
        paths = sorted(DEFAULT_DIR.glob("tk*.json"))
        if not paths:
            print(
                f"Нет tk*.json в {DEFAULT_DIR}. Запустите: .venv/bin/python scripts/export_eval_cases.py",
                file=sys.stderr,
            )
            return 2

    exit_code = 0
    for path in paths:
        case_key, kit, meta = _load_case(path)
        case_key = (args.case or case_key).lower()
        official = OFFICIAL_CASES.get(case_key)
        results = run_checklist(kit, case_key)
        print(f"=== {path.name} ({case_key}) ===")
        if meta:
            print(f"Запрос: {meta.get('title', '')}")
            checklist = meta.get("checklist") or []
            if checklist:
                print(f"Эталонный чек-лист хаба: {len(checklist)} пунктов (см. meta.checklist)")
        elif official:
            print(f"Запрос: {official.title} ({len(official.checklist)} пунктов в official_cases)")
        print(format_report(results))
        if any(not r.passed for r in results):
            exit_code = 1
        print()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
