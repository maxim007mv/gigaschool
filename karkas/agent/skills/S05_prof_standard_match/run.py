"""S05 · Подбор профстандарта и трудовых функций из реестра (Д4 §5.3)."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S05_prof_standard_match"
METADATA = SkillSpec(code="S05", name="Подбор профстандарта и ТФ", dir=DIR, model_class="struct", depends_on=("S01",))

NOT_FOUND_NOTE = "подходящий профстандарт не выбран — требуется выбор методиста (/registry/prof-standards)"
DOP_NOTE = "ДОП: профстандарты и трудовые функции не применяются (V-TPL-02)"


class LaborFunctionOut(BaseModel):
    code: str = ""
    title: str = ""


class ProfStandardOut(BaseModel):
    code: str = ""
    title: str = ""


class MatchOut(BaseModel):
    prof_standard: ProfStandardOut | None = None
    labor_functions: list[LaborFunctionOut] = Field(default_factory=list)
    confidence: float = 0.0
    note: str = ""


def _active_candidates(raw: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code or code in result:
            continue
        if str(item.get("status") or "active") != "active":
            continue
        result[code] = item
    return result


def _labor_functions_of(candidate: dict[str, Any]) -> dict[str, str]:
    functions: dict[str, str] = {}
    for item in candidate.get("labor_functions") or []:
        if isinstance(item, dict) and str(item.get("code") or "").strip():
            functions[str(item["code"]).strip()] = str(item.get("title") or "")
    return functions


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Выбрать профстандарт и ТФ: ДОП — пусто, приложенный ПС — сверка, иначе LLM."""
    kind = str(inputs.get("kind") or "")
    if not kind:
        s02 = inputs.get("S02") if isinstance(inputs.get("S02"), dict) else {}
        kind = str(s02.get("kind") or "")
    if kind == "dop":
        return _empty(1.0, DOP_NOTE)

    candidates = _active_candidates(inputs.get("candidates"))
    if not candidates:
        return _empty(0.0, NOT_FOUND_NOTE)

    attached = inputs.get("attached_ps") if isinstance(inputs.get("attached_ps"), dict) else None
    if attached is not None:
        code = str(attached.get("code") or "").strip()
        candidate = candidates.get(code)
        if candidate is not None:
            allowed = _labor_functions_of(candidate)
            requested = [
                str(item.get("code") or "").strip()
                for item in attached.get("labor_functions") or []
                if isinstance(item, dict)
            ]
            matched = [item for item in requested if item in allowed]
            dropped = [item for item in requested if item and item not in allowed]
            functions = [{"code": item, "title": allowed[item]} for item in matched]
            if not functions:
                functions = [{"code": item, "title": title} for item, title in allowed.items()]
            return {
                "prof_standard": {
                    "code": code,
                    "title": str(candidate.get("title") or attached.get("title") or ""),
                },
                "labor_functions": functions,
                "confidence": 1.0,
                "note": "профстандарт из приложенного файла сверен с реестром",
                "dropped_codes": dropped,
            }

    payload = cast(
        MatchOut,
        await complete_structured(
            ctx,
            METADATA,
            MatchOut,
            profile_json=to_json(inputs.get("profile") or {}),
            candidates_json=to_json(list(candidates.values())),
        ),
    )
    prof_standard = payload.prof_standard
    if prof_standard is None or prof_standard.code.strip() not in candidates:
        dropped = [prof_standard.code.strip()] if prof_standard and prof_standard.code.strip() else []
        return _empty(0.0, NOT_FOUND_NOTE, dropped)

    code = prof_standard.code.strip()
    candidate = candidates[code]
    allowed = _labor_functions_of(candidate)
    functions: list[dict[str, str]] = []
    dropped: list[str] = []
    for item in payload.labor_functions:
        item_code = item.code.strip()
        if not item_code:
            continue
        if item_code in allowed:
            functions.append({"code": item_code, "title": item.title.strip() or allowed[item_code]})
        else:
            dropped.append(item_code)
    note = payload.note.strip()
    if not functions and allowed:
        note = (note + " " if note else "") + "состав ТФ не выбран — требуется выбор методиста"
    elif not allowed:
        note = (note + " " if note else "") + "реестр не передал состав ТФ профстандарта"
    if not candidate.get("file_verified"):
        note = (note + " " if note else "") + "код профстандарта — требует проверки (нет в локальном реестре)"
    return {
        "prof_standard": {
            "code": code,
            "title": prof_standard.title.strip() or str(candidate.get("title") or ""),
        },
        "labor_functions": functions,
        "confidence": max(0.0, min(1.0, payload.confidence)),
        "note": note,
        "dropped_codes": dropped,
    }


def _empty(confidence: float, note: str, dropped: list[str] | None = None) -> dict[str, Any]:
    return {
        "prof_standard": None,
        "labor_functions": [],
        "confidence": confidence,
        "note": note,
        "dropped_codes": dropped or [],
    }
