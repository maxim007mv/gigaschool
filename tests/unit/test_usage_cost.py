"""Учёт вызовов LLM: bool на Postgres и тариф по умолчанию."""

from __future__ import annotations

from decimal import Decimal

from karkas.agent.pipeline import _estimate_cost_rub


def test_estimate_cost_without_tariffs_json() -> None:
    cost = _estimate_cost_rub("GigaChat/GigaChat-3-Pro", 100_000, 30_000)
    assert cost > Decimal("0")
