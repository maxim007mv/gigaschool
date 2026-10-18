"""S07 · Структура модулей и тем: веса и практичность для солвера (Д4 §5.4)."""

from __future__ import annotations

import re
from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, clamp, complete_structured, to_json

DIR = "S07_module_structure"
METADATA = SkillSpec(code="S07", name="Структура модулей и тем", dir=DIR, model_class="struct", depends_on=("S06",))

_OUTCOME_RE = re.compile(r"^LO\d{1,2}\.\d{1,2}$")


class TopicOut(BaseModel):
    ref: str = ""
    title: str = ""
    summary: str | None = None
    outcome_refs: list[str] = Field(default_factory=list)
    complexity: int = 1
    practicality: float = 0.5
    weight: float = 1.0
    has_lab: bool = False


class ModuleOut(BaseModel):
    ref: str = ""
    number: int = 1
    title: str = ""
    weight: float = 1.0
    att_form: str | None = None
    topics: list[TopicOut] = Field(default_factory=list)


class StructureOut(BaseModel):
    modules: list[ModuleOut] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


def known_outcomes(inputs: dict[str, Any]) -> set[str]:
    """Все известные refs результатов обучения (из S06 или явного списка)."""
    s06 = inputs.get("S06") if isinstance(inputs.get("S06"), dict) else {}
    refs: set[str] = set()
    for competency in inputs.get("competencies") or s06.get("competencies") or []:
        if not isinstance(competency, dict):
            continue
        for outcome in competency.get("outcomes") or []:
            if isinstance(outcome, dict) and outcome.get("ref"):
                refs.add(str(outcome["ref"]))
    for outcome in inputs.get("outcomes") or []:
        if isinstance(outcome, dict) and outcome.get("ref"):
            refs.add(str(outcome["ref"]))
    return refs


def normalize_structure(
    items: list[ModuleOut], known: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Постпроверка: refs, диапазоны весов/сложности, привязка тем к существующим РО."""
    modules: list[dict[str, Any]] = []
    gaps: list[str] = []
    for index, module in enumerate(items, start=1):
        title = module.title.strip()
        if not title:
            gaps.append(f"модуль №{index}: пустое название — исключён")
            continue
        module_ref = f"M{index}"
        topics: list[dict[str, Any]] = []
        for order, topic in enumerate(module.topics, start=1):
            topic_title = topic.title.strip()
            if not topic_title:
                gaps.append(f"{module_ref}: тема без названия — исключена")
                continue
            if known:
                refs = [ref for ref in topic.outcome_refs if ref in known]
                foreign = [ref for ref in topic.outcome_refs if ref and ref not in known]
                if foreign:
                    gaps.append(
                        f"{module_ref}.{order}: ссылки на несуществующие РО "
                        f"{', '.join(foreign)} отброшены (V-COV-04)"
                    )
            else:
                refs = [ref for ref in topic.outcome_refs if _OUTCOME_RE.match(ref)]
            if not refs:
                gaps.append(f"{module_ref}.{order}: тема без привязки к РО (V-COV-04)")
            topics.append(
                {
                    "ref": f"T{index}.{order}",
                    "title": topic_title,
                    "summary": (topic.summary or "").strip() or None,
                    "outcome_refs": refs,
                    "complexity": int(clamp(topic.complexity, 1, 5)),
                    "practicality": round(float(clamp(topic.practicality, 0.0, 1.0)), 3),
                    "weight": round(float(clamp(topic.weight, 0.1, 10.0)), 3),
                    "has_lab": bool(topic.has_lab),
                }
            )
        if not topics:
            gaps.append(f"{module_ref} «{title}»: нет валидных тем — модуль исключён")
            continue
        modules.append(
            {
                "ref": module_ref,
                "number": index,
                "title": title,
                "weight": round(float(clamp(module.weight, 0.1, 10.0)), 3),
                "att_form": (module.att_form or "").strip() or None,
                "topics": topics,
            }
        )
    _enforce_sequence(modules, gaps)
    return modules, gaps


def _enforce_sequence(modules: list[dict[str, Any]], gaps: list[str]) -> None:
    """V-SEQ-01: сложность не убывает по порядку программы (модули по номеру, темы по порядку).

    Модель часто ставит базовую тему после продвинутой. Поднимаем сложность такой темы до
    предыдущей (детерминированно, без повторного вызова LLM) и фиксируем поправку в gaps.
    """
    previous = 1
    for module in modules:
        for topic in module["topics"]:
            if topic["complexity"] < previous:
                gaps.append(
                    f"{topic['ref']}: сложность {topic['complexity']} поднята до {previous} "
                    "(V-SEQ-01: сложность не убывает по программе)"
                )
                topic["complexity"] = previous
            previous = topic["complexity"]


def uncovered_outcomes(modules: list[dict[str, Any]], known: set[str]) -> list[str]:
    """РО из S06, которые не раскрыты ни в одной теме (иначе упадёт V-COV-01 на утверждении)."""
    covered = {ref for module in modules for topic in module["topics"] for ref in topic["outcome_refs"]}
    return sorted(known - covered)


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Построить модули и темы по компетенциям S06 (часы не распределяются!)."""
    profile = inputs.get("profile") if isinstance(inputs.get("profile"), dict) else {}
    s06 = inputs.get("S06") if isinstance(inputs.get("S06"), dict) else {}
    competencies_json = to_json(inputs.get("competencies") or s06.get("competencies") or [])
    total_hours = inputs.get("total_hours") or (profile.get("total_hours") or "не задан")
    known = known_outcomes(inputs)

    payload = cast(
        StructureOut,
        await complete_structured(
            ctx,
            METADATA,
            StructureOut,
            profile_json=to_json(profile),
            total_hours=total_hours,
            competencies_json=competencies_json,
        ),
    )
    modules, gaps = normalize_structure(payload.modules, known)
    missing = uncovered_outcomes(modules, known) if known else []
    if missing:
        # Одна целевая перепопытка: модель пропустила РО — просим раскрыть их в темах.
        retry = cast(
            StructureOut,
            await complete_structured(
                ctx,
                METADATA,
                StructureOut,
                profile_json=to_json(profile),
                total_hours=total_hours,
                competencies_json=competencies_json,
                missing_outcomes=", ".join(missing),
                previous_json=to_json(payload.model_dump()),
            ),
        )
        retry_modules, retry_gaps = normalize_structure(retry.modules, known)
        retry_missing = uncovered_outcomes(retry_modules, known)
        # Берём вариант, который раскрывает больше РО: перепопытка не должна ухудшить результат.
        if retry_modules and len(retry_missing) <= len(missing):
            payload, modules, gaps, missing = retry, retry_modules, retry_gaps, retry_missing
    if not modules:
        raise ValueError("S07: после постпроверки не осталось валидных модулей")
    if missing:
        gaps.append(f"РО не раскрыты ни в одной теме после ремонта: {', '.join(missing)}")
    return {
        "modules": modules,
        "gaps": [*[text.strip() for text in payload.gaps if text.strip()], *gaps],
    }
