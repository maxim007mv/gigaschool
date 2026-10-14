"""S01 · Разбор брифа — первый шаг конвейера (Д4 §4, §5.1)."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, clamp, complete_structured

DIR = "S01_parse_brief"
METADATA = SkillSpec(code="S01", name="Разбор брифа", dir=DIR, model_class="struct", depends_on=())

REQUIRED_SLOTS: tuple[str, ...] = (
    "kind",
    "total_hours",
    "audience",
    "entry_level",
    "form",
    "final_attestation",
)


class ConstraintsOut(BaseModel):
    min_practice_share_pct: float = 0.0
    self_study_only: bool = False
    unit_hours: int = 1
    max_hours_per_day: int = 8
    days_per_week: int = 5
    distance_share_pct: float = 0.0
    self_study_share_pct: float = 0.0


class ProfileOut(BaseModel):
    audience: str | None = None
    entry_level: str | None = None
    schedule: str | None = None
    duration_hint: str | None = None
    notes: str | None = None
    glossary: dict[str, str] = Field(default_factory=dict)
    constraints: ConstraintsOut = Field(default_factory=ConstraintsOut)


class AssumptionOut(BaseModel):
    text: str
    slot: str | None = None
    accepted_value: str | None = None
    source: Literal["default", "user", "agent"] = "agent"


class ParseBriefOut(BaseModel):
    profile: ProfileOut = Field(default_factory=ProfileOut)
    goal: str = ""
    requested: list[str] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    assumptions: list[AssumptionOut] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    template_signs: list[str] = Field(default_factory=list)


def normalize(payload: ParseBriefOut) -> dict[str, Any]:
    """Приведение к канону: диапазоны ограничений, чистка строк, известные слоты."""
    profile = payload.profile
    constraints = profile.constraints
    constraints.unit_hours = int(clamp(constraints.unit_hours, 1, 8))
    constraints.max_hours_per_day = int(clamp(constraints.max_hours_per_day, 1, 12))
    constraints.days_per_week = int(clamp(constraints.days_per_week, 1, 7))
    constraints.min_practice_share_pct = float(clamp(constraints.min_practice_share_pct, 0, 100))
    constraints.distance_share_pct = float(clamp(constraints.distance_share_pct, 0, 100))
    constraints.self_study_share_pct = float(clamp(constraints.self_study_share_pct, 0, 100))
    for name in ("audience", "entry_level", "schedule", "duration_hint", "notes"):
        value = getattr(profile, name)
        if isinstance(value, str) and not value.strip():
            setattr(profile, name, None)
    profile.glossary = {
        key.strip(): value.strip()
        for key, value in profile.glossary.items()
        if key.strip() and value.strip()
    }
    missing = [slot for slot in REQUIRED_SLOTS if slot in payload.missing_slots]
    return {
        "profile": profile.model_dump(mode="json"),
        "goal": payload.goal.strip(),
        "requested": [text.strip() for text in payload.requested if text.strip()],
        "missing_slots": missing,
        "assumptions": [item.model_dump(mode="json") for item in payload.assumptions if item.text.strip()],
        "gaps": [text.strip() for text in payload.gaps if text.strip()],
        "template_signs": [text.strip() for text in payload.template_signs if text.strip()],
    }


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Разобрать бриф в профиль программы (без выдумывания фактов)."""
    brief = str(inputs.get("brief") or "").strip()
    if not brief:
        raise ValueError("S01: пустой бриф — нечего разбирать")
    limit = ctx.settings.brief_max_chars
    payload = cast(
        ParseBriefOut,
        await complete_structured(
            ctx,
            METADATA,
            ParseBriefOut,
            brief=brief[:limit],
            files_text=str(inputs.get("files_text") or "")[:limit],
            answers_json=inputs.get("answers") or {},
        ),
    )
    return normalize(payload)
