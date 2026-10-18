"""ТК-3: S06/S07 не оставляют нераскрытых РО; формулировки слушателя, не преподавателя."""

from __future__ import annotations

import asyncio
from typing import Any

from karkas.agent.skills._base import SkillContext
from karkas.agent.skills.S07_module_structure.run import run as s07_run
from karkas.domain.outcome_coverage import link_uncovered_outcomes


class _Gateway:
    async def complete_json(self, skill, model_class, messages, schema, temperature=None):
        if "S06" in skill:
            return schema.model_validate(
                {
                    "competencies": [
                        {
                            "ref": "C1",
                            "title": "Анализ данных",
                            "labor_function_codes": [],
                            "outcomes": [
                                {"ref": "LO1.1", "type": "knowledge", "text": "Знает основы Python"},
                                {"ref": "LO1.2", "type": "skill", "text": "Умеет работать с pandas"},
                                {
                                    "ref": "LO1.3",
                                    "type": "experience",
                                    "text": "Имеет опыт разработки учебных материалов и проведения занятий",
                                },
                            ],
                        }
                    ],
                    "gaps": [],
                }
            )
        return schema.model_validate(
            {
                "modules": [
                    {
                        "title": "Python и аналитика",
                        "topics": [
                            {
                                "title": "Введение в Python",
                                "outcome_refs": ["LO1.1", "LO1.2"],
                                "practicality": 0.8,
                                "has_lab": True,
                            }
                        ],
                    }
                ],
                "gaps": [],
            }
        )


async def _s06_run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    from karkas.agent.skills.S06_competency_map.run import run as s06_run

    return await s06_run(inputs, ctx)


def test_s06_rewrites_teacher_side_outcome_for_72h() -> None:
    inputs = {
        "kind": "dpp_pk",
        "total_hours": 72,
        "profile": {"total_hours": 72},
        "labor_functions": [],
    }
    result = asyncio.run(_s06_run(inputs, SkillContext(gateway=_Gateway())))
    lo13 = next(o for c in result["competencies"] for o in c["outcomes"] if o["ref"] == "LO1.3")
    assert lo13["type"] == "skill"
    assert "учебн" not in lo13["text"].casefold()
    assert "начальн" in lo13["text"].casefold()


def test_link_uncovered_outcomes_covers_lo13() -> None:
    modules = [
        {
            "ref": "M1",
            "number": 1,
            "topics": [
                {
                    "ref": "T1.1",
                    "title": "Python",
                    "outcome_refs": ["LO1.1", "LO1.2"],
                    "practicality": 0.9,
                    "has_lab": True,
                }
            ],
        }
    ]
    gaps: list[str] = []
    link_uncovered_outcomes(modules, {"LO1.1", "LO1.2", "LO1.3"}, gaps)
    refs = modules[0]["topics"][0]["outcome_refs"]
    assert "LO1.3" in refs


def test_s07_pipeline_links_missing_outcome() -> None:
    inputs: dict[str, Any] = {
        "brief": "банк Python 72 часа",
        "profile": {"total_hours": 72},
        "total_hours": 72,
        "constraints": {"total": 72, "final_att": 2, "unit": 4},
        "S06": {
            "competencies": [
                {
                    "ref": "C1",
                    "outcomes": [
                        {"ref": "LO1.1"},
                        {"ref": "LO1.2"},
                        {"ref": "LO1.3"},
                    ],
                }
            ]
        },
    }
    result = asyncio.run(s07_run(inputs, SkillContext(gateway=_Gateway())))
    covered = {ref for m in result["modules"] for t in m["topics"] for ref in t["outcome_refs"]}
    assert "LO1.3" in covered
    assert not any("не раскрыты" in g for g in result["gaps"])
