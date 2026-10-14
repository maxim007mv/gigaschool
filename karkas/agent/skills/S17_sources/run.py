"""S17 · Кандидаты источников: НПА, литература, интернет, ПО (Д4 §5.7)."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S17_sources"
METADATA = SkillSpec(code="S17", name="Литература и ресурсы", dir=DIR, model_class="bulk", depends_on=("S11",))

SECTIONS: tuple[str, ...] = ("normative", "main", "additional", "internet", "software")
MAX_SOURCES = 60


class SourceOut(BaseModel):
    ref: str = ""
    section: Literal["normative", "main", "additional", "internet", "software", ""] = "main"
    citation: str = ""
    url: str | None = None
    isbn: str | None = None
    normative_act_ref: str | None = None


class SourcesOut(BaseModel):
    sources: list[SourceOut] = Field(default_factory=list)
    notes: str = ""


def normalize_sources(
    items: list[SourceOut], allowed_normative: set[str] | None
) -> list[dict[str, Any]]:
    """Дедупликация, порядок разделов, нумерация SRC-nn, сверка кодов реестра."""
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    section_order = {name: index for index, name in enumerate(SECTIONS)}
    ordered = sorted(items, key=lambda item: section_order.get(item.section if item.section in SECTIONS else "main", 9))
    for source in ordered:
        citation = " ".join(source.citation.split())
        if not citation:
            continue
        key = citation.casefold()
        if key in seen:
            continue
        seen.add(key)
        section = source.section if source.section in SECTIONS else "main"
        norm_ref = (source.normative_act_ref or "").strip() or None
        if norm_ref and allowed_normative is not None and norm_ref.casefold() not in allowed_normative:
            norm_ref = None
        unique.append(
            {
                "section": section,
                "citation": citation,
                "url": (source.url or "").strip() or None,
                "isbn": (source.isbn or "").strip() or None,
                "normative_act_ref": norm_ref,
            }
        )
    unique = unique[:MAX_SOURCES]
    for index, source in enumerate(unique, start=1):
        source["ref"] = f"SRC-{index:02d}"
    return [
        {"ref": source["ref"], **{key: value for key, value in source.items() if key != "ref"}}
        for source in unique
    ]


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Собрать кандидатов источников (проверка — в S18)."""
    topics = inputs.get("topics") or [
        topic for module in inputs.get("modules") or [] if isinstance(module, dict) for topic in module.get("topics") or []
    ]
    allowed_raw = inputs.get("allowed_normative")
    allowed_normative = (
        {str(item).strip().casefold() for item in allowed_raw if str(item).strip()}
        if isinstance(allowed_raw, list)
        else None
    )
    payload = cast(
        SourcesOut,
        await complete_structured(
            ctx,
            METADATA,
            SourcesOut,
            topics_json=to_json(topics),
            allowed_normative_json=to_json(sorted(allowed_normative) if allowed_normative else []),
        ),
    )
    sources = normalize_sources(payload.sources, allowed_normative)
    if not sources:
        raise ValueError("S17: не вернулось ни одного источника с цитатой")
    return {"sources": sources, "notes": payload.notes.strip()}
