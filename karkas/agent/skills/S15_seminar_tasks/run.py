"""S15 · Задания семинаров с критериями оценки (Д4 §5.6)."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S15_seminar_tasks"
METADATA = SkillSpec(code="S15", name="Задания семинаров", dir=DIR, model_class="bulk", depends_on=("S11",))

DEFAULT_LEVELS: list[str] = ["выполнено", "не выполнено"]


class CriterionOut(BaseModel):
    criterion: str = ""
    max_points: float = 0.0
    levels: list[str] = Field(default_factory=list)


class TaskOut(BaseModel):
    ref: str = ""
    topic_ref: str | None = None
    module_ref: str | None = None
    stem: str = ""
    rubric: list[CriterionOut] = Field(default_factory=list)
    outcome_refs: list[str] = Field(default_factory=list)


class TasksOut(BaseModel):
    tasks: list[TaskOut] = Field(default_factory=list)


def normalize_tasks(
    items: list[TaskOut],
    known_outcomes: set[str],
    known_topics: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Постпроверка: rubric и РО обязательны, баллы положительные, refs нормализуются."""
    tasks: list[dict[str, Any]] = []
    dropped: list[str] = []
    for index, task in enumerate(items, start=1):
        stem = task.stem.strip()
        topic_ref = task.topic_ref.strip() if isinstance(task.topic_ref, str) else None
        if topic_ref and known_topics and topic_ref not in known_topics:
            topic_ref = None
        ref = task.ref.strip() or f"ST-{topic_ref or 'T'}-{index}"
        if not stem:
            dropped.append(f"{ref}: пустая формулировка задания")
            continue
        rubric: list[dict[str, Any]] = []
        for criterion in task.rubric:
            text = criterion.criterion.strip()
            if not text:
                continue
            rubric.append(
                {
                    "criterion": text,
                    "max_points": float(criterion.max_points) if criterion.max_points > 0 else 1.0,
                    "levels": [level.strip() for level in criterion.levels if level.strip()] or list(DEFAULT_LEVELS),
                }
            )
        if not rubric:
            dropped.append(f"{ref}: нет критериев оценки (rubric обязателен)")
            continue
        refs = [ref_name for ref_name in task.outcome_refs if not known_outcomes or ref_name in known_outcomes]
        if not refs:
            dropped.append(f"{ref}: нет привязки к РО (V-COV-04)")
            continue
        tasks.append(
            {
                "ref": ref,
                "kind": "seminar_task",
                "topic_ref": topic_ref,
                "module_ref": task.module_ref.strip() if isinstance(task.module_ref, str) else None,
                "stem": stem,
                "rubric": rubric,
                "outcome_refs": refs,
            }
        )
    return tasks, dropped


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Составить задания семинаров с критериями и привязкой к РО."""
    outcomes = inputs.get("outcomes") or []
    known_outcomes = {str(item.get("ref")) for item in outcomes if isinstance(item, dict) and item.get("ref")}
    topics = inputs.get("topics") or ([inputs["topic"]] if isinstance(inputs.get("topic"), dict) else [])
    known_topics = {str(item.get("ref")) for item in topics if isinstance(item, dict) and item.get("ref")}
    payload = cast(
        TasksOut,
        await complete_structured(
            ctx,
            METADATA,
            TasksOut,
            instruction=str(inputs.get("instruction") or ""),
            topics_json=to_json(topics),
            outcomes_json=to_json(outcomes),
            profile_json=to_json(inputs.get("profile") or {}),
        ),
    )
    tasks, dropped = normalize_tasks(payload.tasks, known_outcomes, known_topics)
    if not tasks:
        raise ValueError("S15: после постпроверки не осталось валидных заданий (rubric/РО)")
    return {"tasks": tasks, "dropped": dropped, "count": len(tasks)}
