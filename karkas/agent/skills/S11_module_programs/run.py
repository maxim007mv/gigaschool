"""S11 · Рабочие программы модулей (Д4 §5.6)."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S11_module_programs"
METADATA = SkillSpec(code="S11", name="Рабочие программы модулей", dir=DIR, model_class="bulk", depends_on=("S10",))


class BlockOut(BaseModel):
    ref: str = ""
    kind: Literal["module_program"] = "module_program"
    module_ref: str | None = None
    topic_ref: str | None = None
    body: dict[str, Any] = Field(default_factory=dict)


class ModuleProgramsOut(BaseModel):
    module_programs: list[BlockOut] = Field(default_factory=list)
    notes: str = ""


def normalize_blocks(
    payload: ModuleProgramsOut, module_ref: str, topic_refs: set[str]
) -> tuple[list[dict[str, Any]], str]:
    """Оставить только темы модуля, нормализовать refs и структуру body."""
    blocks: list[dict[str, Any]] = []
    for index, block in enumerate(payload.module_programs, start=1):
        body = block.body if isinstance(block.body, dict) else {}
        topics: list[dict[str, Any]] = []
        for item in body.get("topics") or []:
            if not isinstance(item, dict):
                continue
            topic_ref = str(item.get("topic_ref") or "").strip()
            if topic_refs and topic_ref not in topic_refs:
                continue
            topics.append(
                {
                    "topic_ref": topic_ref or None,
                    "summary": str(item.get("summary") or "").strip(),
                    "work_forms": [str(x).strip() for x in item.get("work_forms") or [] if str(x).strip()],
                    "materials": [str(x).strip() for x in item.get("materials") or [] if str(x).strip()],
                }
            )
        ref = f"MP-{module_ref}" if index == 1 else f"MP-{module_ref}-{index}"
        blocks.append(
            {
                "ref": ref,
                "kind": "module_program",
                "module_ref": module_ref,
                "topic_ref": None,
                "body": {
                    "annotation": str(body.get("annotation") or "").strip(),
                    "topics": topics,
                    "att_form": str(body.get("att_form") or "").strip(),
                },
            }
        )
    if not blocks or not blocks[0]["body"]["topics"]:
        raise ValueError("S11: рабочая программа модуля не содержит тем")
    return blocks, payload.notes.strip()


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Собрать рабочую программу модуля по темам каркаса."""
    module = inputs.get("module") if isinstance(inputs.get("module"), dict) else {}
    if not module or not module.get("ref"):
        raise ValueError("S11: не передан модуль каркаса (inputs['module'])")
    module_ref = str(module["ref"])
    topic_refs = {str(topic.get("ref")) for topic in module.get("topics") or [] if isinstance(topic, dict)}
    outcomes = inputs.get("outcomes") or []
    payload = cast(
        ModuleProgramsOut,
        await complete_structured(
            ctx,
            METADATA,
            ModuleProgramsOut,
            instruction=str(inputs.get("instruction") or ""),
            module_json=to_json(module),
            outcomes_json=to_json(outcomes),
            profile_json=to_json(inputs.get("profile") or {}),
        ),
    )
    blocks, notes = normalize_blocks(payload, module_ref, topic_refs)
    return {"module_programs": blocks, "notes": notes}
