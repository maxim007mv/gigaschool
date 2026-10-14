"""S13 · Структура слайдов по плану лекции (Д4 §5.6)."""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S13_slides"
METADATA = SkillSpec(code="S13", name="Слайды", dir=DIR, model_class="bulk", depends_on=("S12",))

MAX_SLIDES = 12
MAX_BULLETS = 8


class SlideOut(BaseModel):
    title: str = ""
    bullets: list[str] = Field(default_factory=list)
    notes: str = ""


class SlidesBodyOut(BaseModel):
    slides: list[SlideOut] = Field(default_factory=list)
    notes: str = ""


class SlidesOut(BaseModel):
    topic_ref: str = ""
    module_ref: str | None = None
    title: str = ""
    body: SlidesBodyOut = Field(default_factory=SlidesBodyOut)


def normalize_block(
    payload: SlidesOut,
    topic_ref: str,
    module_ref: str | None,
    source_ref: str | None,
) -> tuple[dict[str, Any], int]:
    """Постпроверка слайдов: заголовки, ≤ 8 пунктов, ≤ 12 слайдов."""
    slides: list[dict[str, Any]] = []
    for slide in payload.body.slides:
        title = slide.title.strip()
        if not title:
            continue
        slides.append(
            {
                "title": title,
                "bullets": [text.strip() for text in slide.bullets[:MAX_BULLETS] if text.strip()],
                "notes": slide.notes.strip(),
            }
        )
    trimmed = max(0, len(slides) - MAX_SLIDES)
    slides = slides[:MAX_SLIDES]
    if not slides:
        raise ValueError("S13: модель не вернула ни одного слайда с заголовком")
    block = {
        "ref": f"SL-{topic_ref}",
        "kind": "slides",
        "module_ref": module_ref,
        "topic_ref": topic_ref,
        "body": {
            "title": payload.title.strip() or topic_ref,
            "slides": slides,
            "source_ref": source_ref,
        },
    }
    return block, trimmed


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Собрать структуру слайдов по плану лекции (без выхода за её рамки)."""
    topic = inputs.get("topic") if isinstance(inputs.get("topic"), dict) else {}
    if not topic or not topic.get("ref"):
        raise ValueError("S13: не передана тема каркаса (inputs['topic'])")
    s12 = inputs.get("S12") if isinstance(inputs.get("S12"), dict) else {}
    lecture_plan = inputs.get("lecture_plan") or (s12.get("lecture_plans") or [None])[0] or {}
    topic_ref = str(topic["ref"])
    module_ref = str(inputs.get("module_ref") or "") or None
    payload = cast(
        SlidesOut,
        await complete_structured(
            ctx,
            METADATA,
            SlidesOut,
            topic_json=to_json(topic),
            lecture_plan_json=to_json(lecture_plan),
        ),
    )
    block, trimmed = normalize_block(payload, topic_ref, module_ref, str(lecture_plan.get("ref") or "") or None)
    notes = payload.body.notes.strip()
    if trimmed:
        notes = (notes + " " if notes else "") + f"обрезано слайдов: {trimmed} (лимит {MAX_SLIDES})"
    return {"slides": [block], "notes": notes, "trimmed": trimmed}
