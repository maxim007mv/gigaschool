#!/usr/bin/env python3
"""Бенчмарк токенов и времени конвейера (фикстурный запрос, без живого LLM).

Пример:
  .venv/bin/python scripts/benchmark_pipeline.py --json
  .venv/bin/python scripts/benchmark_pipeline.py --markdown
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from karkas.eval.pipeline_timing import measure_both
from karkas.eval.token_benchmark import (
    compare_compact_savings,
    markdown_table,
    measure_pipeline_tokens,
    per_skill_table,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Бенчмарк токенов/времени КАРКАС")
    parser.add_argument("--json", action="store_true", help="Вывести JSON")
    parser.add_argument("--markdown", action="store_true", help="Вывести Markdown для README")
    parser.add_argument("--out", type=Path, help="Сохранить JSON в файл")
    args = parser.parse_args()

    reports = [measure_pipeline_tokens(h) for h in (16, 72)]
    savings_16 = compare_compact_savings(16)
    savings_72 = compare_compact_savings(72)
    timings = asyncio.run(measure_both())

    payload = {
        "token_estimates": {
            str(r.total_hours): {
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_tokens": r.total_tokens,
                "cost_rub": str(r.cost_rub),
                "per_skill": [
                    {
                        "code": row.code,
                        "calls": row.calls,
                        "prompt_tokens": row.prompt_tokens,
                        "completion_tokens": row.completion_tokens,
                    }
                    for row in r.rows
                    if row.llm
                ],
            }
            for r in reports
        },
        "compact_json_savings": {"16h": savings_16, "72h": savings_72},
        "timings_fake_gateway_sec": timings,
        "notes": [
            "Токены — оценка по render_prompt + типовому completion; live — llm.usage в логах и llm_call.",
            "Время — FakeGateway, concurrency=2; live SLO: каркас ≤180 с, комплект 72 ч ≤1200 с.",
            "S13 по умолчанию на все темы (all_slides=True).",
        ],
    }

    if args.out:
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json or (not args.markdown and not args.out):
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.markdown:
        print("## Метрики защиты (бенчмарк, фикстурный запрос)\n")
        print(markdown_table(reports))
        print()
        print(per_skill_table(reports[0]))
        print()
        print(per_skill_table(reports[1]))
        print("\n### Экономия compact JSON в промптах\n")
        print(
            f"- 16 ч: −{savings_16['prompt_tokens_saved']} prompt-токенов "
            f"({savings_16['before']['cost_rub']} → {savings_16['after']['cost_rub']} ₽)"
        )
        print(
            f"- 72 ч: −{savings_72['prompt_tokens_saved']} prompt-токенов "
            f"({savings_72['before']['cost_rub']} → {savings_72['after']['cost_rub']} ₽)"
        )
        print("\n### Время (FakeGateway, concurrency=2)\n")
        print(json.dumps(timings, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
