"""Детерминированный LLM-шлюз для бенчмарков и интеграционных тестов."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

# Минимальные ответы каркаса (расширяйте в тестах при необходимости).
FRAMEWORK_RESPONSES: dict[str, dict[str, Any]] = {
    "S01": {
        "profile": {
            "audience": "ИТ-специалисты",
            "entry_level": "базовый",
            "constraints": {"min_practice_share_pct": 50, "max_hours_per_day": 8, "days_per_week": 5},
        },
        "goal": "Освоить анализ данных на Python",
        "requested": [],
        "missing_slots": [],
        "assumptions": [],
        "gaps": [],
        "template_signs": [],
    },
    "S02": {"kind": "dop", "confidence": 0.9, "rationale": "ДОП"},
    "S03": {"questions": [], "assumptions": []},
    "S05": {"prof_standard": None, "labor_functions": [], "confidence": 1.0, "note": ""},
    "S06": {
        "competencies": [
            {
                "ref": "C1",
                "title": "Анализ данных",
                "outcomes": [
                    {"ref": "LO1.1", "type": "knowledge", "text": "Знает pandas"},
                    {"ref": "LO1.2", "type": "skill", "text": "Строит отчёты"},
                    {"ref": "LO1.3", "type": "experience", "text": "Выполнил проект"},
                ],
            }
        ],
        "gaps": [],
    },
}


class FakeGateway:
    """Подмена Cloud.ru FM: ответы по коду навыка."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = {**FRAMEWORK_RESPONSES, **(responses or {})}
        self.calls: list[str] = []

    @staticmethod
    def _topic_ref(messages: list[dict[str, Any]]) -> str:
        prompt = "\n".join(str(m.get("content") or "") for m in messages)
        match = re.search(r'"ref":\s*"(T\d{1,2}\.\d{1,2})"', prompt)
        return match.group(1) if match else "T1.1"

    def _dynamic(self, skill: str, topic_ref: str) -> dict[str, Any]:
        if skill == "S12":
            return {
                "lecture_plans": [
                    {
                        "ref": f"LP-{topic_ref}",
                        "title": f"Лекция {topic_ref}",
                        "body": {
                            "goals": ["Цель"],
                            "stages": [{"stage": "Введение", "minutes": 10, "activity": "лекция", "notes": ""}],
                            "questions": [],
                            "materials": [],
                            "notes": "",
                        },
                    }
                ]
            }
        if skill == "S13":
            return {
                "title": topic_ref,
                "body": {
                    "slides": [{"title": "Слайд", "bullets": ["тезис"], "notes": "", "layout": "title_and_content"}],
                    "notes": "",
                },
            }
        if skill == "S14":
            return {
                "questions": [
                    {
                        "ref": f"Q-{topic_ref}",
                        "topic_ref": topic_ref,
                        "stem": "Вопрос",
                        "qtype": "single",
                        "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                        "answer_key": {"correct": ["a"], "explanation": "A"},
                        "outcome_refs": ["LO1.1"],
                        "difficulty": 1,
                    }
                ]
            }
        if skill == "S15":
            return {
                "tasks": [
                    {
                        "ref": f"ST-{topic_ref}",
                        "topic_ref": topic_ref,
                        "stem": "Задание",
                        "rubric": [{"criterion": "OK", "max_points": 5, "levels": ["зачтено"]}],
                        "outcome_refs": ["LO1.1"],
                    }
                ]
            }
        raise AssertionError(f"FakeGateway: нет динамического ответа для {skill}")

    async def complete_json(
        self,
        skill: str,
        model_class: str,
        messages: list[dict[str, Any]],
        schema: type[BaseModel],
        temperature: float | None = None,
    ) -> BaseModel:
        self.calls.append(skill)
        if skill in ("S12", "S13", "S14", "S15"):
            payload = self._dynamic(skill, self._topic_ref(messages))
        else:
            payload = self.responses.get(skill)
            if payload is None:
                raise AssertionError(f"FakeGateway: нет заготовки для навыка {skill}")
        return schema.model_validate(payload)
