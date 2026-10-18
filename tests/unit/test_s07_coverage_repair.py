"""S07: РО, не раскрытые темами, отправляются на одну целевую перепопытку (ремонт покрытия)."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel

from karkas.agent.skills._base import SkillContext
from karkas.agent.skills.S07_module_structure.run import run, uncovered_outcomes

INPUTS: dict[str, Any] = {
    "profile": {"total_hours": 16},
    "total_hours": 16,
    "S06": {
        "competencies": [
            {"ref": "C1", "outcomes": [{"ref": "LO1.1"}, {"ref": "LO1.2"}]},
            {"ref": "C2", "outcomes": [{"ref": "LO2.1"}]},
        ]
    },
}

PARTIAL = {
    "modules": [
        {
            "ref": "M1",
            "number": 1,
            "title": "Основы",
            "topics": [
                {"ref": "T1", "title": "Тема А", "outcome_refs": ["LO1.1", "LO1.2"]},
            ],
        }
    ],
    "gaps": [],
}

FULL = {
    "modules": [
        {
            "ref": "M1",
            "number": 1,
            "title": "Основы",
            "topics": [
                {"ref": "T1", "title": "Тема А", "outcome_refs": ["LO1.1", "LO1.2"]},
                {"ref": "T2", "title": "Тема Б", "outcome_refs": ["LO2.1"]},
            ],
        }
    ],
    "gaps": [],
}


class _SequenceGateway:
    """Фейковый шлюз: отдаёт ответы по очереди и запоминает промпты."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    async def complete_json(
        self,
        skill: str,
        model_class: str,
        messages: list[dict[str, Any]],
        schema: type[BaseModel],
        temperature: float | None = None,
    ) -> BaseModel:
        self.prompts.append(messages[-1]["content"])
        return schema.model_validate(self._responses.pop(0))


def test_uncovered_outcomes_lists_only_missing_refs() -> None:
    modules = [{"topics": [{"outcome_refs": ["LO1.1"]}, {"outcome_refs": ["LO1.2"]}]}]
    assert uncovered_outcomes(modules, {"LO1.1", "LO1.2", "LO2.1"}) == ["LO2.1"]


def test_repair_call_fixes_missing_outcome() -> None:
    gateway = _SequenceGateway([PARTIAL, FULL])
    result = asyncio.run(run(INPUTS, SkillContext(gateway=gateway)))

    assert len(gateway.prompts) == 2
    assert "ВНИМАНИЕ" in gateway.prompts[1] and "LO2.1" in gateway.prompts[1]
    assert "ВНИМАНИЕ" not in gateway.prompts[0]
    covered = {ref for m in result["modules"] for t in m["topics"] for ref in t["outcome_refs"]}
    assert covered == {"LO1.1", "LO1.2", "LO2.1"}
    assert not any("не раскрыты" in gap for gap in result["gaps"])


def test_unrepaired_outcome_is_reported_in_gaps() -> None:
    gateway = _SequenceGateway([PARTIAL, PARTIAL])
    result = asyncio.run(run(INPUTS, SkillContext(gateway=gateway)))

    assert len(gateway.prompts) == 2
    assert any("РО не раскрыты ни в одной теме после ремонта: LO2.1" in gap for gap in result["gaps"])


def test_no_repair_when_all_outcomes_covered() -> None:
    gateway = _SequenceGateway([FULL])
    asyncio.run(run(INPUTS, SkillContext(gateway=gateway)))
    assert len(gateway.prompts) == 1


def test_sequence_clamps_complexity_to_non_decreasing_order() -> None:
    from karkas.agent.skills.S07_module_structure.run import ModuleOut, normalize_structure

    def topic(title: str, complexity: int) -> dict[str, Any]:
        return {"title": title, "outcome_refs": ["LO1.1"], "complexity": complexity}

    items = [
        ModuleOut.model_validate({"title": "A", "topics": [topic("t1", 3), topic("t2", 2)]}),
        ModuleOut.model_validate({"title": "B", "topics": [topic("t3", 4), topic("t4", 3)]}),
    ]
    modules, gaps = normalize_structure(items, {"LO1.1"})
    complexities = [t["complexity"] for m in modules for t in m["topics"]]
    assert complexities == [3, 3, 4, 4]
    assert sum("V-SEQ-01" in gap for gap in gaps) == 2


WORSE = {
    "modules": [
        {
            "ref": "M1",
            "number": 1,
            "title": "Основы",
            "topics": [
                {"ref": "T1", "title": "Тема А", "outcome_refs": ["LO1.1"]},
            ],
        },
    ],
    "gaps": [],
}


def test_worse_repair_is_discarded() -> None:
    # Перепопытка раскрыла меньше РО, чем первая попытка: остаётся первая.
    gateway = _SequenceGateway([PARTIAL, WORSE])
    result = asyncio.run(run(INPUTS, SkillContext(gateway=gateway)))
    covered = {ref for m in result["modules"] for t in m["topics"] for ref in t["outcome_refs"]}
    assert covered == {"LO1.1", "LO1.2"}
    assert any("РО не раскрыты ни в одной теме после ремонта: LO2.1" in gap for gap in result["gaps"])
