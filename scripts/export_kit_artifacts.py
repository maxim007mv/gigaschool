#!/usr/bin/env python3
"""Экспорт артефактов KitV1 в каталог примера (после live-прогона).

Пример:
  .venv/bin/python scripts/export_kit_artifacts.py \
      --kit data/eval/reports/tk1_live_kit.json \
      --metrics data/eval/reports/tk1_live_report.json \
      --out examples/tk1 --prefix tk1

Пишет program_*.docx, presentation_*.pptx, tests_*.gift.txt,
tests_*.moodle.xml, kit_*.json, report_*.docx и metrics.json.
Содержимое .docx/.pptx берётся только из KitV1 (его пишет GigaChat);
скрипт лишь синхронизирует usage из live-отчёта.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

import karkas.infra.exporters.bootstrap  # noqa: F401 — регистрация V-ACR
from karkas.domain.kit import KitV1, Usage
from karkas.domain.kit_fixup import apply_kit_fixup
from karkas.domain.validators import ValidationContext, run_validation
from karkas.eval.checklists import run_checklist
from karkas.eval.official_cases import OFFICIAL_CASES
from karkas.infra.exporters import (
    export_docx_program,
    export_docx_report,
    export_gift,
    export_moodle_xml,
    export_pptx_slides,
)


def _load_kit(path: Path) -> KitV1:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return KitV1.model_validate(raw["kit"] if isinstance(raw, dict) and "kit" in raw else raw)


def _apply_metrics(kit: KitV1, metrics: dict) -> KitV1:
    usage = metrics.get("usage") or {}
    timings = metrics.get("timings_s") or {}
    calls = int(usage.get("calls") or 0)
    tokens = int(usage.get("tokens") or 0)
    cost = Decimal(str(usage.get("cost_rub") or "0"))
    duration = float(timings.get("wall_s") or timings.get("total_s") or 0.0)
    if calls or tokens or cost or duration:
        kit = kit.model_copy(update={"usage": Usage(calls=calls, tokens=tokens, cost_rub=cost, duration_s=duration)})
    return kit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Экспорт файлов примера из KitV1")
    parser.add_argument("--kit", type=Path, required=True, help="KitV1 JSON (или {kit: …})")
    parser.add_argument("--metrics", type=Path, help="JSON live-отчёта (usage/timings/checklist)")
    parser.add_argument("--out", type=Path, required=True, help="Каталог примера (examples/tk1)")
    parser.add_argument("--prefix", required=True, help="Префикс имён файлов (tk1)")
    parser.add_argument("--case", help="Кейс tk1…tk5: применить kit_fixup с брифом кейса")
    args = parser.parse_args(argv)

    if not args.kit.is_file():
        print(f"Файл не найден: {args.kit}")
        return 2
    kit = _load_kit(args.kit)
    case_key = args.case.lower() if args.case else None
    if case_key:
        official = OFFICIAL_CASES.get(case_key)
        if official is None:
            print(f"Неизвестный кейс: {args.case}")
            return 2
        kit = apply_kit_fixup(kit, brief=official.request_text)
    metrics: dict = {}
    if args.metrics and args.metrics.is_file():
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        kit = _apply_metrics(kit, metrics)
    if metrics and case_key:
        # Метрики должны соответствовать финальным артефактам, а не промежуточному
        # прогону: пересчитываем полный официальный чек-лист и V-*.
        results = run_checklist(kit, case_key)
        report = run_validation(ValidationContext(kit=kit, stage="kit"))
        errors = [issue for issue in report.issues if issue.severity == "error"]
        metrics["checklist_passed"] = sum(1 for result in results if result.passed)
        metrics["checklist_total"] = len(results)
        metrics["checklist_failed"] = [f"{result.item_id}: {result.detail}" for result in results if not result.passed]
        metrics["validation_ok"] = not errors
        metrics["validation_errors"] = len(errors)
        metrics["validation_warnings"] = sum(1 for issue in report.issues if issue.severity == "warning")
        metrics["validation_messages"] = [f"{issue.rule_code}: {issue.message}" for issue in errors]

    args.out.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix
    (args.out / f"program_{prefix}.docx").write_bytes(export_docx_program(kit))
    (args.out / f"presentation_{prefix}.pptx").write_bytes(export_pptx_slides(kit))
    (args.out / f"tests_{prefix}.gift.txt").write_text(export_gift(kit), encoding="utf-8")
    (args.out / f"tests_{prefix}.moodle.xml").write_text(export_moodle_xml(kit), encoding="utf-8")
    (args.out / f"kit_{prefix}.json").write_text(
        json.dumps(kit.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.out / f"report_{prefix}.docx").write_bytes(export_docx_report(kit))
    if metrics:
        (args.out / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"Экспортировано в {args.out}: program, presentation, tests, kit, report, metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
