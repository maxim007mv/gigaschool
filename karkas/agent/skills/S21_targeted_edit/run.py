"""S21 · Точечная правка: граф зависимостей + разбор инструкции (Д4 §5.9)."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import (
    SkillContext,
    SkillSpec,
    complete_structured,
    kit_from_inputs,
    to_json,
)
from karkas.domain.dependency_graph import closure
from karkas.domain.kit import KitV1

DIR = "S21_targeted_edit"
METADATA = SkillSpec(code="S21", name="Точечная правка", dir=DIR, model_class="bulk", depends_on=("S20",))

INSTRUCTION_MIN = 3
INSTRUCTION_MAX = 2000


class EditIntentOut(BaseModel):
    action: str = ""
    target_ref: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


def why_rebuild(ref: str) -> str:
    """Причина пересборки по префиксу ref (таблица 4.7)."""
    if ref.startswith("T"):
        return "тема: план лекции, слайды, задания и раздел рабочей программы"
    if ref.startswith("M"):
        return "модуль: учебный план, рабочая программа, часы (солвер)"
    if ref.startswith("LO"):
        return "результат обучения: связи с темами и оценочные средства"
    if ref.startswith("Q-"):
        return "тест: вопросы выбранного теста и проверка покрытия"
    if ref.startswith("ST-"):
        return "задание семинара: критерии и привязка к РО"
    if ref.startswith("SL-"):
        return "слайды лекции"
    if ref.startswith("SRC-"):
        return "источник: статус верификации и список литературы"
    return "зависимый элемент комплекта"


def all_refs(kit: KitV1) -> set[str]:
    """Все refs комплекта (для проверки, что план не выходит за его пределы)."""
    refs: set[str] = set()
    for competency in kit.framework.competencies:
        refs.add(competency.ref)
        refs.update(outcome.ref for outcome in competency.outcomes)
    for module in kit.framework.modules:
        refs.add(module.ref)
        for topic in module.topics:
            refs.add(topic.ref)
    refs.update(assessment.ref for assessment in kit.content.assessments)
    for group in (
        kit.content.module_programs,
        kit.content.lecture_plans,
        kit.content.slides,
        kit.content.sections,
    ):
        refs.update(block.ref for block in group)
    refs.update(source.ref for source in kit.content.sources)
    return refs


def mark_stale(kit: KitV1, affected: set[str]) -> KitV1:
    """Пометить затронутые ContentBlock как stale (копия комплекта)."""
    patched = kit.model_copy(deep=True)
    for group in (
        patched.content.module_programs,
        patched.content.lecture_plans,
        patched.content.slides,
        patched.content.sections,
    ):
        for block in group:
            if block.ref in affected:
                block.stale = True
    return patched


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Разобрать инструкцию, вычислить affected и вернуть план пересборки."""
    target_ref = str(inputs.get("target_ref") or "").strip()
    instruction = str(inputs.get("instruction") or "").strip()
    if not target_ref:
        raise ValueError("S21: не указан target_ref")
    if not (INSTRUCTION_MIN <= len(instruction) <= INSTRUCTION_MAX):
        raise ValueError("S21: инструкция должна быть 3…2000 символов (Д4 §10)")

    kit = kit_from_inputs(inputs, ctx, "S21")
    affected = [str(ref) for ref in (inputs.get("affected") or []) if str(ref).strip()]
    if not affected:
        affected = [str(ref) for ref in closure(kit, target_ref)]
    payload = cast(
        EditIntentOut,
        await complete_structured(
            ctx,
            METADATA,
            EditIntentOut,
            instruction=instruction,
            target_ref=target_ref,
            affected_json=to_json(affected),
        ),
    )
    known = all_refs(kit)
    stale_refs = [ref for ref in affected if ref in known]
    plan = [{"ref": ref, "rebuild": True, "reason": why_rebuild(ref)} for ref in affected]
    patched = mark_stale(kit, set(affected))
    return {
        "intent": payload.model_dump(mode="json"),
        "affected": affected,
        "stale_refs": stale_refs,
        "plan": plan,
        "dry_run": bool(inputs.get("dry_run", True)),
        "kit": patched.model_dump(mode="json"),
    }
