"""S10 · Проверка каркаса доменными валидаторами (Д4 §5.8)."""

from __future__ import annotations

from typing import Any

from karkas.agent.skills._base import (
    SkillContext,
    SkillSpec,
    kit_from_inputs,
    registry_bundle,
    today_from_inputs,
)
from karkas.domain.validators import ValidationContext, run_validation

DIR = "S10_framework_validation"
METADATA = SkillSpec(
    code="S10",
    name="Проверка каркаса",
    dir=DIR,
    depends_on=("S09", "S04"),
)


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Прогнать V-* по каркасу и вернуть отчёт для Human Gate."""
    kit = kit_from_inputs(inputs, ctx, "S10")
    context = ValidationContext(
        kit=kit,
        registries=registry_bundle(inputs.get("registries") or ctx.extra.get("registries")),
        reference_texts=[str(text) for text in (inputs.get("reference_texts") or [])],
        declared_totals=inputs.get("declared_totals"),
        today=today_from_inputs(inputs),
    )
    report = run_validation(context)
    return {
        "report": report.model_dump(mode="json"),
        "passed": bool(report.passed),
        "error_count": len(report.errors),
    }
