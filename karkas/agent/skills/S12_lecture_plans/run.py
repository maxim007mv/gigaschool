"""S12 · Планы лекций по темам каркаса (Д4 §5.6)."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S12_lecture_plans"
METADATA = SkillSpec(code="S12", name="Планы лекций", dir=DIR, model_class="bulk", depends_on=("S11",))

MAX_STAGES = 20


class StageOut(BaseModel):
    minutes: int = 0
    stage: str = ""
    activity: str = ""
    notes: str = ""


class LectureBody(BaseModel):
    goals: list[str] = Field(default_factory=list)
    stages: list[StageOut] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    notes: str = ""


class LecturePlanOut(BaseModel):
    ref: str = ""
    module_ref: str | None = None
    topic_ref: str = ""
    title: str = ""
    body: LectureBody = Field(default_factory=LectureBody)


class LecturePlansOut(BaseModel):
    lecture_plans: list[LecturePlanOut] = Field(default_factory=list)


def normalize_plans(payload: LecturePlansOut, default_topic: str, module_ref: str | None) -> list[dict[str, Any]]:
    """Постпроверка: этапы, refs, отсутствие пустых планов."""
    plans: list[dict[str, Any]] = []
    for plan in payload.lecture_plans:
        topic_ref = plan.topic_ref.strip() or default_topic
        stages: list[dict[str, Any]] = []
        seen: set[str] = set()
        for stage in plan.body.stages[:MAX_STAGES]:
            name = stage.stage.strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            stages.append(
                {
                    "minutes": max(0, int(stage.minutes)),
                    "stage": name,
                    "activity": stage.activity.strip(),
                    "notes": stage.notes.strip(),
                }
            )
        if not stages:
            continue
        plans.append(
            {
                "ref": plan.ref.strip() or f"LP-{topic_ref}",
                "kind": "lecture_plan",
                "module_ref": plan.module_ref or module_ref,
                "topic_ref": topic_ref,
                "title": plan.title.strip(),
                "body": {
                    "goals": [text.strip() for text in plan.body.goals if text.strip()],
                    "stages": stages,
                    "questions": [text.strip() for text in plan.body.questions if text.strip()],
                    "materials": [text.strip() for text in plan.body.materials if text.strip()],
                    "notes": plan.body.notes.strip(),
                },
            }
        )
    if not plans:
        raise ValueError("S12: модель не вернула ни одного плана лекции с этапами")
    return plans


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Составить план лекции по теме (источник для слайдов и заметок докладчика)."""
    topic = inputs.get("topic") if isinstance(inputs.get("topic"), dict) else {}
    if not topic or not topic.get("ref"):
        raise ValueError("S12: не передана тема каркаса (inputs['topic'])")
    topic_ref = str(topic["ref"])
    module_ref = str(inputs.get("module_ref") or "") or None
    s11 = inputs.get("S11") if isinstance(inputs.get("S11"), dict) else {}
    module_program = (s11.get("module_programs") or [None])[0] or {}
    payload = cast(
        LecturePlansOut,
        await complete_structured(
            ctx,
            METADATA,
            LecturePlansOut,
            instruction=str(inputs.get("instruction") or ""),
            topic_json=to_json(topic),
            outcomes_json=to_json(inputs.get("outcomes") or []),
            module_program_json=to_json(module_program),
            knowledge_snippets=str(inputs.get("knowledge_snippets") or ""),
        ),
    )
    return {"lecture_plans": normalize_plans(payload, topic_ref, module_ref)}
