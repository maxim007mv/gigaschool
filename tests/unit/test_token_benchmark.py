"""Бенчмарк токенов: фикстурный запрос 16/72 ч."""

from __future__ import annotations

from karkas.eval.token_benchmark import (
    compare_compact_savings,
    measure_pipeline_tokens,
)


def test_measure_pipeline_tokens_positive() -> None:
    report = measure_pipeline_tokens(16)
    assert report.total_tokens > 0
    assert report.prompt_tokens > report.completion_tokens
    assert float(report.cost_rub) > 0


def test_compact_json_reduces_prompt_tokens() -> None:
    savings = compare_compact_savings(72)
    assert savings["prompt_tokens_saved"] >= 0
    assert savings["after"]["prompt_tokens"] <= savings["before"]["prompt_tokens"]
