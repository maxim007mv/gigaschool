"""S04 · Анализ референсов: структура образцов и их ошибки (Д4 §5.6)."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S04_reference_analysis"
METADATA = SkillSpec(code="S04", name="Анализ референсов", dir=DIR, model_class="struct", depends_on=("S01",))

MAX_SECTIONS = 60
MAX_ERRORS = 50
MAX_FINDINGS = 30


class SectionOut(BaseModel):
    title: str = ""
    source_name: str | None = None
    order: int | None = None


class SampleErrorOut(BaseModel):
    kind: str = ""
    description: str = ""
    evidence: str | None = None


class RefAnalysisOut(BaseModel):
    sections: list[SectionOut] = Field(default_factory=list)
    sample_errors: list[SampleErrorOut] = Field(default_factory=list)
    topic_candidates: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    notes: str = ""


def normalize(payload: RefAnalysisOut) -> dict[str, Any]:
    """Чистка списков: пустые значения убираются, дубли — тоже, объёмы ограничиваются."""
    sections: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for item in payload.sections:
        title = item.title.strip()
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        sections.append(
            {
                "title": title,
                "source_name": (item.source_name or "").strip() or None,
                "order": item.order,
            }
        )
    errors = [
        {
            "kind": item.kind.strip() or "other",
            "description": item.description.strip(),
            "evidence": (item.evidence or "").strip() or None,
        }
        for item in payload.sample_errors
        if item.description.strip()
    ]
    return {
        "sections": sections[:MAX_SECTIONS],
        "sample_errors": errors[:MAX_ERRORS],
        "topic_candidates": [text.strip() for text in payload.topic_candidates if text.strip()],
        "findings": [text.strip() for text in payload.findings if text.strip()][:MAX_FINDINGS],
        "notes": payload.notes.strip(),
    }


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Разобрать референсы (данные, не инструкции) и вернуть структуру с ошибками."""
    limit = ctx.settings.brief_max_chars
    parts: list[str] = []
    for index, reference in enumerate(inputs.get("references") or [], start=1):
        if isinstance(reference, dict):
            name = str(reference.get("name") or f"reference-{index}")
            text = str(reference.get("text") or "")
        else:
            name, text = f"reference-{index}", str(reference)
        if text.strip():
            parts.append(f"[{name}]\n{text[:limit]}")
    old_program = str(inputs.get("old_program_text") or "").strip()
    if old_program:
        parts.append(f"[старая программа]\n{old_program[:limit]}")
    if not parts:
        raise ValueError("S04: не переданы референсы для анализа")
    payload = cast(
        RefAnalysisOut,
        await complete_structured(
            ctx,
            METADATA,
            RefAnalysisOut,
            references_text="\n\n".join(parts),
            profile_json=to_json(inputs.get("profile") or {}),
        ),
    )
    return normalize(payload)
