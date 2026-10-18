"""Метрики защиты: стоимость токенов Cloud.ru FM (тарифы хаба, GigaChat-3-Pro)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# hub_notes.md — GigaChat/GigaChat-3-Pro, ₽ за 1M токенов
GIGACHAT_3_PRO_IN_RUB_PER_M = Decimal("73.03")
GIGACHAT_3_PRO_OUT_RUB_PER_M = Decimal("176.39")
MANUAL_BASELINE_HOURS_DEFAULT = Decimal("40")


@dataclass(frozen=True)
class TokenCost:
    prompt_tokens: int
    completion_tokens: int
    cost_rub: Decimal

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def estimate_gigachat3_pro_cost(prompt_tokens: int, completion_tokens: int) -> TokenCost:
    cost = (
        Decimal(prompt_tokens) * GIGACHAT_3_PRO_IN_RUB_PER_M / Decimal(1_000_000)
        + Decimal(completion_tokens) * GIGACHAT_3_PRO_OUT_RUB_PER_M / Decimal(1_000_000)
    )
    return TokenCost(
        prompt_tokens=max(0, prompt_tokens),
        completion_tokens=max(0, completion_tokens),
        cost_rub=cost.quantize(Decimal("0.01")),
    )


def savings_hours(active_methodologist_h: float, baseline_h: float = 40.0) -> float:
    return max(0.0, baseline_h - active_methodologist_h)
