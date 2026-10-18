"""S06 · Карта компетенций и результатов обучения (Д4 §4, §5.3)."""

from __future__ import annotations

import re
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S06_competency_map"
METADATA = SkillSpec(code="S06", name="Карта компетенций (З/У/Н)", dir=DIR, model_class="struct", depends_on=("S05",))

OUTCOME_TYPES: tuple[str, ...] = ("knowledge", "skill", "experience")
_COMPETENCY_RE = re.compile(r"^C\d{1,2}$")
_OUTCOME_RE = re.compile(r"^LO\d{1,2}\.\d{1,2}$")


class OutcomeOut(BaseModel):
    ref: str = ""
    type: Literal["knowledge", "skill", "experience"] = "knowledge"
    text: str = ""


class CompetencyOut(BaseModel):
    ref: str = ""
    title: str = ""
    activity_kind: str | None = None
    labor_function_codes: list[str] = Field(default_factory=list)
    outcomes: list[OutcomeOut] = Field(default_factory=list)


class CompetencyMapOut(BaseModel):
    competencies: list[CompetencyOut] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


def normalize_competencies(
    items: list[CompetencyOut],
    allowed_lf: set[str],
    kind: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Постпроверка карты: refs, З/У/Н у каждой компетенции, коды ТФ только из входа."""
    competencies: list[dict[str, Any]] = []
    gaps: list[str] = []
    used_refs: set[str] = set()
    for index, item in enumerate(items, start=1):
        ref = item.ref.strip()
        if not _COMPETENCY_RE.match(ref) or ref in used_refs:
            ref = f"C{index}"
        if ref in used_refs:
            gaps.append(f"компетенция №{index}: дублирующийся ref — исключена")
            continue
        title = item.title.strip()
        if not title:
            gaps.append(f"{ref}: пустое название — компетенция исключена")
            continue
        outcomes: list[dict[str, Any]] = []
        seen_outcomes: set[str] = set()
        for order, outcome in enumerate(item.outcomes, start=1):
            text = outcome.text.strip()
            if not text:
                continue
            outcome_ref = outcome.ref.strip()
            if not _OUTCOME_RE.match(outcome_ref) or outcome_ref in seen_outcomes:
                outcome_ref = f"LO{ref[1:]}.{order}"
            if outcome_ref in seen_outcomes:
                continue
            seen_outcomes.add(outcome_ref)
            outcomes.append({"ref": outcome_ref, "type": outcome.type, "text": text})
        missing = [kind_name for kind_name in OUTCOME_TYPES if not any(o["type"] == kind_name for o in outcomes)]
        if missing:
            gaps.append(f"{ref}: нет результатов типа {', '.join(missing)} — компетенция исключена (V-COV-03)")
            continue
        if kind == "dop":
            labor_functions: list[str] = []
        else:
            labor_functions = [code for code in item.labor_function_codes if code in allowed_lf]
            foreign = [code for code in item.labor_function_codes if code and code not in allowed_lf]
            if foreign:
                gaps.append(f"{ref}: коды ТФ {', '.join(foreign)} отсутствуют в реестре — отброшены (V-SRC-03)")
        used_refs.add(ref)
        competencies.append(
            {
                "ref": ref,
                "title": title,
                "activity_kind": item.activity_kind.strip() if item.activity_kind else None,
                "labor_function_codes": labor_functions,
                "outcomes": outcomes,
            }
        )
    return competencies, gaps


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Сформировать компетенции З/У/Н и проверить их по правилам V-COV-03/V-SRC."""
    s05 = inputs.get("S05") if isinstance(inputs.get("S05"), dict) else {}
    profile = inputs.get("profile") if isinstance(inputs.get("profile"), dict) else {}
    kind = str(inputs.get("kind") or profile.get("kind") or "dpp_pk")
    allowed_lf = {
        str(item["code"]).strip()
        for item in (s05.get("labor_functions") or inputs.get("labor_functions") or [])
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    }
    payload = cast(
        CompetencyMapOut,
        await complete_structured(
            ctx,
            METADATA,
            CompetencyMapOut,
            kind=kind,
            profile_json=to_json(profile),
            total_hours=inputs.get("total_hours") or "не задан",
            labor_functions_json=to_json(s05.get("labor_functions") or inputs.get("labor_functions") or []),
            knowledge=str(inputs.get("knowledge") or "")[: ctx.settings.brief_max_chars],
        ),
    )
    competencies, gaps = normalize_competencies(payload.competencies, allowed_lf, kind)
    try:
        total_hours = int(inputs.get("total_hours") or profile.get("total_hours") or 0)
    except (TypeError, ValueError):
        total_hours = 0
    if 0 < total_hours <= 72:
        for comp in competencies:
            for outcome in comp["outcomes"]:
                if outcome["type"] == "experience":
                    outcome["type"] = "skill"
    if not competencies:
        raise ValueError("S06: после постпроверки не осталось валидных компетенций")
    return {
        "competencies": competencies,
        "gaps": [*[text.strip() for text in payload.gaps if text.strip()], *gaps],
    }
