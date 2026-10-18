"""S19 · Самопроверка комплекта: полный прогон V-* и сборка Report (Д4 §5.8)."""

from __future__ import annotations

from typing import Any

from karkas.agent.skills._base import (
    SkillContext,
    SkillSpec,
    kit_from_inputs,
    registry_bundle,
    today_from_inputs,
)
from karkas.domain.kit import Report
from karkas.domain.validators import ValidationContext, run_validation

DIR = "S19_kit_validation"
METADATA = SkillSpec(
    code="S19",
    name="Самопроверка комплекта",
    dir=DIR,
    depends_on=("S18", "S16", "S15", "S14", "S13"),
)


def _reference_texts(inputs: dict[str, Any]) -> list[str]:
    return [str(text) for text in (inputs.get("reference_texts") or []) if str(text).strip()]


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Прогнать полный набор V-* по комплекту и вернуть канонический Report."""
    kit = kit_from_inputs(inputs, ctx, "S19")
    context = ValidationContext(
        kit=kit,
        registries=registry_bundle(inputs.get("registries") or ctx.extra.get("registries")),
        reference_texts=_reference_texts(inputs),
        declared_totals=inputs.get("declared_totals"),
        today=today_from_inputs(inputs),
    )
    report = run_validation(context)
    assembled = Report.model_validate(report.model_dump(mode="json"))
    return {
        "report": assembled.model_dump(mode="json"),
        "passed": bool(assembled.passed),
        "error_count": len(assembled.errors),
    }
