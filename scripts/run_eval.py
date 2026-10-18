#!/usr/bin/env python3
"""Прогон эталонных чек-листов по JSON в data/eval/ (Д4 §11).

Пример:
  .venv/bin/python scripts/run_eval.py
  .venv/bin/python scripts/run_eval.py data/eval/tk5.json tk5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from karkas.domain.kit import KitV1
from karkas.eval.checklists import format_report, run_checklist

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "eval"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eval чек-листы КАРКАС")
    parser.add_argument(
        "paths",
        nargs="*",
        help="Пути к kit JSON; по умолчанию — все data/eval/tk*.json",
    )
    parser.add_argument(
        "--case",
        help="Ключ кейса (tk1…tk5); по умолчанию — имя файла без расширения",
    )
    args = parser.parse_args(argv)

    paths: list[Path]
    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        if not DEFAULT_DIR.is_dir():
            print(f"Каталог {DEFAULT_DIR} не найден. Создайте data/eval/ и положите tk*.json.", file=sys.stderr)
            return 2
        paths = sorted(DEFAULT_DIR.glob("tk*.json"))
        if not paths:
            print(f"Нет файлов tk*.json в {DEFAULT_DIR}", file=sys.stderr)
            return 2

    exit_code = 0
    for path in paths:
        case_key = (args.case or path.stem).lower()
        kit = KitV1.model_validate(json.loads(path.read_text(encoding="utf-8")))
        results = run_checklist(kit, case_key)
        print(f"=== {path.name} ({case_key}) ===")
        print(format_report(results))
        if any(not r.passed for r in results):
            exit_code = 1
        print()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
