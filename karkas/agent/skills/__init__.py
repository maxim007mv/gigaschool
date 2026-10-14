"""karkas.agent.skills — каталог навыков S01–S23 (Д1 §6, Д4 §4).

Каждый навык — каталог с четырьмя файлами: ``SKILL.md`` (инструкция методисту),
``schema.json`` (вход/выход), ``prompt.jinja`` (шаблон сообщения модели),
``run.py`` (код шага с ``METADATA = SkillSpec(...)`` и ``async def run``).

``SKILLS`` собирается из ``METADATA`` всех ``run.py`` по списку ``SKILL_DIRS``;
``load_skill(code)`` возвращает паспорт навыка по коду.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

from karkas.agent.skills._base import (
    CacheProtocol,
    CheckpointStore,
    InMemoryCache,
    InMemoryCheckpointStore,
    LlmGatewayProtocol,
    MeterProtocol,
    NullMeter,
    SkillContext,
    SkillModelClass,
    SkillSpec,
    complete_structured,
    maybe_await,
    render_prompt,
    require_gateway,
)

#: Код навыка → каталог внутри karkas/agent/skills.
SKILL_DIRS: dict[str, str] = {
    "S01": "S01_parse_brief",
    "S02": "S02_template_choice",
    "S03": "S03_clarifying_questions",
    "S04": "S04_reference_analysis",
    "S05": "S05_prof_standard_match",
    "S06": "S06_competency_map",
    "S07": "S07_module_structure",
    "S08": "S08_hours_solver",
    "S09": "S09_calendar",
    "S10": "S10_framework_validation",
    "S11": "S11_module_programs",
    "S12": "S12_lecture_plans",
    "S13": "S13_slides",
    "S14": "S14_test_questions",
    "S15": "S15_seminar_tasks",
    "S16": "S16_final_assessment",
    "S17": "S17_sources",
    "S18": "S18_source_verification",
    "S19": "S19_kit_validation",
    "S20": "S20_export",
    "S21": "S21_targeted_edit",
    "S22": "S22_actualize",
    "S23": "S23_adapt",
}

SKILL_CODES: tuple[str, ...] = tuple(SKILL_DIRS)


def _import_spec(code: str) -> SkillSpec:
    """Импортировать run.py навыка и проверить его METADATA."""
    directory = SKILL_DIRS[code]
    module = importlib.import_module(f"karkas.agent.skills.{directory}.run")
    spec = getattr(module, "METADATA", None)
    if not isinstance(spec, SkillSpec):
        raise ImportError(f"{directory}/run.py: METADATA должен быть SkillSpec")
    if spec.code != code:
        raise ImportError(f"{directory}/run.py: METADATA.code={spec.code!r}, ожидался {code!r}")
    if spec.dir != directory:
        raise ImportError(f"{directory}/run.py: METADATA.dir={spec.dir!r}, ожидался {directory!r}")
    run_func = getattr(module, "run", None)
    if run_func is None or not callable(run_func):
        raise ImportError(f"{directory}/run.py: нет callable run()")
    return spec


SKILLS: dict[str, SkillSpec] = {code: _import_spec(code) for code in SKILL_CODES}


def load_skill(code: str) -> SkillSpec:
    """Паспорт навыка по коду; KeyError с понятным текстом, если кода нет."""
    try:
        return SKILLS[code]
    except KeyError:
        raise KeyError(f"навык {code!r} не найден; доступны: {', '.join(SKILL_CODES)}") from None


def iter_skills() -> Iterator[SkillSpec]:
    """Итератор паспортов всех навыков в порядке кодов."""
    return iter(SKILLS.values())


__all__ = [
    "CacheProtocol",
    "CheckpointStore",
    "InMemoryCache",
    "InMemoryCheckpointStore",
    "LlmGatewayProtocol",
    "MeterProtocol",
    "NullMeter",
    "SKILLS",
    "SKILL_CODES",
    "SKILL_DIRS",
    "SkillContext",
    "SkillModelClass",
    "SkillSpec",
    "complete_structured",
    "iter_skills",
    "load_skill",
    "maybe_await",
    "render_prompt",
    "require_gateway",
]
