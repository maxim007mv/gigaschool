from decimal import Decimal

from karkas.eval.defense_metrics import estimate_gigachat3_pro_cost


def test_gigachat_cost_positive() -> None:
    cost = estimate_gigachat3_pro_cost(1_000_000, 500_000)
    assert cost.cost_rub > Decimal("0")
    assert cost.total_tokens == 1_500_000
