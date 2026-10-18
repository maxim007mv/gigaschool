#!/usr/bin/env python3
"""Прогон эталонных чек-листов по JSON в data/eval/ (открытые ТК-1…ТК-5 хаба).

Пример:
  .venv/bin/python scripts/run_eval.py
  .venv/bin/python scripts/run_eval.py --kit /tmp/kit.json --case tk1
  .venv/bin/python scripts/run_eval.py --live --case tk1 --api http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import karkas.infra.exporters.bootstrap  # noqa: F401 — V-ACR в run_checklist
from karkas.domain.kit import KitV1
from karkas.eval.checklists import format_report, run_checklist
from karkas.eval.official_cases import OFFICIAL_CASES

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "eval"
DEFAULT_LIVE_OUT = ROOT / "data" / "eval" / "reports"


def _load_kit_file(path: Path) -> KitV1:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "kit" in raw:
        return KitV1.model_validate(raw["kit"])
    return KitV1.model_validate(raw)


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


def _score_kit(case_key: str, kit: KitV1, meta: dict | None, label: str) -> int:
    official = OFFICIAL_CASES.get(case_key)
    results = run_checklist(kit, case_key)
    print(f"=== {label} ({case_key}) ===")
    if meta:
        print(f"Запрос: {meta.get('title', '')}")
    elif official:
        print(f"Запрос: {official.title}")
    print(format_report(results))
    print()
    return 0 if all(r.passed for r in results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eval чек-листы КАРКАС (ТК-1…ТК-5)")
    parser.add_argument("paths", nargs="*", help="Пути к JSON (tk*.json или kit)")
    parser.add_argument("--case", help="Ключ кейса tk1…tk5")
    parser.add_argument("--kit", type=Path, help="Произвольный KitV1 JSON (с --case)")
    parser.add_argument("--live", action="store_true", help="Сквозной прогон через API (нужен KARKAS_EVAL_API_KEY)")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="Базовый URL API для --live")
    parser.add_argument(
        "--live-out",
        type=Path,
        default=DEFAULT_LIVE_OUT,
        help="Каталог отчётов live-прогона",
    )
    parser.add_argument("--live-timeout", type=float, default=1200.0, help="Таймаут HTTP, с")
    args = parser.parse_args(argv)

    if args.live:
        if not args.case:
            print("Для --live укажите --case tk1…tk5", file=sys.stderr)
            return 2
        from karkas.eval.live_run import run_live_case

        try:
            report = run_live_case(
                args.case.lower(),
                base_url=args.api,
                timeout_s=args.live_timeout,
                out_dir=args.live_out,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Live прогон не удался: {exc}", file=sys.stderr)
            return 1
        print(report.to_markdown())
        return 0 if report.status == "completed" and not report.checklist_failed else 1

    if args.kit:
        if not args.case:
            print("Для --kit укажите --case tk1…tk5", file=sys.stderr)
            return 2
        if not args.kit.is_file():
            print(f"Файл не найден: {args.kit}", file=sys.stderr)
            return 2
        kit = _load_kit_file(args.kit)
        return _score_kit(args.case.lower(), kit, None, args.kit.name)

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
        code = _score_kit(case_key, kit, meta, path.name)
        exit_code = max(exit_code, code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
