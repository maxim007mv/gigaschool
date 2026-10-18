"""karkas.domain.validators.realism — реалистичность каркаса (Д4 §5.8, V-REA-01).

Эвристики (документированы и покрыты тестами на границах):
- результат типа «практический опыт» (experience) при объёме ≤ 72 ч — warning:
  за такой объём реально сформировать лишь начальный опыт;
- разных результатов обучения больше, чем объём/2 (то есть меньше 2 ч на
  результат) — warning: формулировки слишком дробные для объёма.

Разрыв между пожеланиями заказчика и результатами показывается в отчёте
через framework.gaps (переносится run_validation в Report.gaps).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karkas.domain.validators.base import GroupResult, issue

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

EXPERIENCE_MAX_HOURS = 72  # порог объёма для результата «практический опыт»
OUTCOMES_PER_HOUR = 0.5  # не более 1 РО на каждые 2 часа


def validate(ctx: ValidationContext) -> GroupResult:
    """Проверки реалистичности объёма и результатов."""
    kit = ctx.kit
    total = kit.program.total_hours
    outcomes = list(kit.iter_outcomes())
    issues = []

    if total <= EXPERIENCE_MAX_HOURS:
        for outcome in outcomes:
            if outcome.type == "experience":
                issues.append(
                    issue(
                        "V-REA-01",
                        "warning",
                        f"Практический опыт {outcome.ref} за {total} ч — нереалистично: за такой объём "
                        "формируется начальный опыт, перенесите результат в умения или увеличьте объём",
                        entity_ref=outcome.ref,
                    )
                )
    if len(outcomes) > total * OUTCOMES_PER_HOUR:
        issues.append(
            issue(
                "V-REA-01",
                "warning",
                f"Результатов обучения {len(outcomes)} на {total} ч — меньше 2 ч на результат; "
                "укрупните формулировки или добавьте часы (разрыв с пожеланием покажите в отчёте)",
            )
        )

    meta = {
        "outcomes": len(outcomes),
        "limits": {
            "experience_max_hours": EXPERIENCE_MAX_HOURS,
            "outcomes_per_hour": OUTCOMES_PER_HOUR,
        },
    }
    return GroupResult(issues=issues, meta=meta)
