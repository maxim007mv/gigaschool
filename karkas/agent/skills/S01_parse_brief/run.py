"""S01 · Разбор брифа — первый шаг конвейера (Д4 §4, §5.1)."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field, field_validator

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

    @field_validator("source", mode="before")
    @classmethod
    def _coerce_source(cls, value: object) -> str:
        if value in ("default", "user", "agent"):
            return str(value)
        return "agent"


class ParseBriefOut(BaseModel):
    profile: ProfileOut = Field(default_factory=ProfileOut)
    goal: str = ""
    requested: list[str] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    assumptions: list[AssumptionOut] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    template_signs: list[str] = Field(default_factory=list)

    @field_validator("requested", mode="before")
    @classmethod
    def _coerce_requested(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                for key in ("text", "value", "description", "name", "title"):
                    raw = item.get(key)
                    if isinstance(raw, str) and raw.strip():
                        out.append(raw.strip())
                        break
        return out


def normalize(payload: ParseBriefOut) -> dict[str, Any]:
    """Приведение к канону: диапазоны ограничений, чистка строк, известные слоты."""
    profile = payload.profile
    constraints = profile.constraints
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
        key.strip(): value.strip() for key, value in profile.glossary.items() if key.strip() and value.strip()
    }
    missing = [slot for slot in REQUIRED_SLOTS if slot in payload.missing_slots]
    return {
        "profile": profile.model_dump(mode="json"),
        "goal": payload.goal.strip(),
        "requested": [text.strip() for text in payload.requested if text.strip()],
        "missing_slots": missing,
        "assumptions": [
            (lambda row: row if row.get("source") in ("default", "user", "agent") else {**row, "source": "agent"})(
                item.model_dump(mode="json")
            )
            for item in payload.assumptions
            if item.text.strip()
        ],
        "gaps": [text.strip() for text in payload.gaps if text.strip()],
        "template_signs": [text.strip() for text in payload.template_signs if text.strip()],
    }


def _reconcile_answers(data: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Согласовать missing_slots и gaps с уже известными ответами (бриф, clarification)."""
    if not answers:
        return data
    data["missing_slots"] = [
        slot for slot in (data.get("missing_slots") or []) if not str(answers.get(slot) or "").strip()
    ]
    data["gaps"] = _filter_gaps_with_answers(data.get("gaps") or [], answers)
    profile = dict(data.get("profile") or {})
    for slot in ("audience", "entry_level", "schedule", "duration_hint"):
        if not profile.get(slot) and str(answers.get(slot) or "").strip():
            profile[slot] = str(answers[slot]).strip()
    data["profile"] = profile
    return data


def _filter_gaps_with_answers(gaps: list[str], answers: dict[str, Any]) -> list[str]:
    import json

    out: list[str] = []
    for raw in gaps:
        text = str(raw).strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                out.append(text)
                continue
            if isinstance(obj, dict):
                field = str(obj.get("field") or obj.get("slot") or "").strip()
                if field and str(answers.get(field) or "").strip():
                    continue
        out.append(text)
    return out


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
    return _reconcile_answers(normalize(payload), dict(inputs.get("answers") or {}))
