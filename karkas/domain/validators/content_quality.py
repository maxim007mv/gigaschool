"""Качество артефактов комплекта (слайды, тесты, задания) — V-CNT-01..05.

Срабатывают на стадии kit (S19). fix_hint указывает на kit:regenerate для точечной пересборки.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from karkas.domain.kit import KitV1
from karkas.domain.validators.base import GroupResult, issue, resolve_stage

if TYPE_CHECKING:  # pragma: no cover
    from karkas.domain.validators import ValidationContext

_PLACEHOLDER = re.compile(
    r"(?:\b(TBD|TODO|Lorem ipsum|заглушка|вставьте текст|___+)\b|\[\.\.\.\]|\{\.\.\.\})",
    re.IGNORECASE,
)
_MIN_STEM_LEN = 12
_MIN_OPTION_LEN = 2
_MIN_SLIDE_TITLE = 3


def _regen_hint(target_ref: str, parts: list[str]) -> dict[str, object]:
    return {"endpoint": "kit:regenerate", "body": {"target_ref": target_ref, "parts": parts}}


def _iter_slide_dicts(kit: KitV1) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    for block in kit.content.slides:
        raw = block.body.get("slides")
        if isinstance(raw, list):
            for _index, item in enumerate(raw):
                if isinstance(item, dict):
                    rows.append((block.topic_ref or block.ref, item))
        elif block.body.get("title") or block.body.get("bullets"):
            rows.append((block.topic_ref or block.ref, block.body))
    return rows


def validate(ctx: ValidationContext) -> GroupResult:
    if resolve_stage(ctx) != "kit":
        return GroupResult(skipped=["V-CNT-01", "V-CNT-02", "V-CNT-03", "V-CNT-04", "V-CNT-05"])
    kit = ctx.kit
    issues = []
    seen_stems: dict[str, str] = {}

    for block in kit.content.lecture_plans:
        lines = block.body.get("plan") or block.body.get("bullets") or block.body.get("outline")
        if not lines:
            ref = block.topic_ref or block.ref
            issues.append(
                issue(
                    "V-CNT-01",
                    "error",
                    f"План лекции {ref}: нет структуры (plan/bullets) — пересоберите материал",
                    entity_ref=ref,
                    fix_hint=_regen_hint(ref, ["lecture_plan"]),
                )
            )

    slide_titles: set[str] = set()
    for topic_ref, slide in _iter_slide_dicts(kit):
        title = str(slide.get("title") or "").strip()
        if len(title) < _MIN_SLIDE_TITLE:
            issues.append(
                issue(
                    "V-CNT-01",
                    "error",
                    f"Слайды темы {topic_ref}: пустой или слишком короткий заголовок слайда",
                    entity_ref=topic_ref,
                    fix_hint=_regen_hint(topic_ref, ["slides"]),
                )
            )
        elif title.lower() in slide_titles:
            issues.append(
                issue(
                    "V-CNT-01",
                    "warning",
                    f"Слайды: повторяющийся заголовок «{title}» — уточните формулировки",
                    entity_ref=topic_ref,
                    fix_hint=_regen_hint(topic_ref, ["slides"]),
                )
            )
        else:
            slide_titles.add(title.lower())
        notes = slide.get("speaker_notes") or slide.get("notes") or ""
        if not str(notes).strip():
            issues.append(
                issue(
                    "V-CNT-01",
                    "warning",
                    f"Слайд «{title or topic_ref}»: нет заметок докладчика",
                    entity_ref=topic_ref,
                    fix_hint=_regen_hint(topic_ref, ["slides"]),
                )
            )
        bullets = slide.get("bullets") or slide.get("lines") or []
        if isinstance(bullets, list) and len(bullets) > 6:
            issues.append(
                issue(
                    "V-CNT-01",
                    "warning",
                    f"Слайд «{title}»: больше одной идеи на слайд ({len(bullets)} пунктов)",
                    entity_ref=topic_ref,
                    fix_hint=_regen_hint(topic_ref, ["slides"]),
                )
            )

    for assessment in kit.content.assessments:
        stem_norm = " ".join(assessment.stem.split()).lower()
        if _PLACEHOLDER.search(assessment.stem):
            issues.append(
                issue(
                    "V-CNT-02",
                    "error",
                    f"{assessment.ref}: текст-заглушка в формулировке вопроса/задания",
                    entity_ref=assessment.ref,
                    fix_hint=_regen_hint(
                        assessment.topic_ref or assessment.ref,
                        ["tests"] if assessment.kind == "test_question" else ["tasks"],
                    ),
                )
            )
        if assessment.kind == "test_question":
            if len(assessment.stem.strip()) < _MIN_STEM_LEN:
                issues.append(
                    issue(
                        "V-CNT-02",
                        "error",
                        f"{assessment.ref}: слишком короткий текст вопроса",
                        entity_ref=assessment.ref,
                        fix_hint=_regen_hint(assessment.topic_ref or assessment.ref, ["tests"]),
                    )
                )
            if len(assessment.options) < 2:
                issues.append(
                    issue(
                        "V-CNT-02",
                        "error",
                        f"{assessment.ref}: меньше двух вариантов ответа",
                        entity_ref=assessment.ref,
                        fix_hint=_regen_hint(assessment.topic_ref or assessment.ref, ["tests"]),
                    )
                )
            correct = set(assessment.answer_key.correct if assessment.answer_key else [])
            for opt in assessment.options:
                if len(opt.text.strip()) < _MIN_OPTION_LEN:
                    issues.append(
                        issue(
                            "V-CNT-02",
                            "error",
                            f"{assessment.ref}: пустой вариант ответа {opt.id}",
                            entity_ref=assessment.ref,
                            fix_hint=_regen_hint(assessment.topic_ref or assessment.ref, ["tests"]),
                        )
                    )
                if opt.id not in correct and opt.text.strip().lower() == assessment.stem.strip().lower():
                    issues.append(
                        issue(
                            "V-CNT-02",
                            "warning",
                            f"{assessment.ref}: дистрактор совпадает с текстом вопроса",
                            entity_ref=assessment.ref,
                            fix_hint=_regen_hint(assessment.topic_ref or assessment.ref, ["tests"]),
                        )
                    )
            if stem_norm in seen_stems:
                issues.append(
                    issue(
                        "V-CNT-02",
                        "warning",
                        f"{assessment.ref}: дублирует вопрос {seen_stems[stem_norm]}",
                        entity_ref=assessment.ref,
                        fix_hint=_regen_hint(assessment.topic_ref or assessment.ref, ["tests"]),
                    )
                )
            else:
                seen_stems[stem_norm] = assessment.ref
        if assessment.kind == "seminar_task" and (
            not assessment.rubric or not any(c.criterion.strip() for c in assessment.rubric)
        ):
            issues.append(
                issue(
                    "V-CNT-03",
                    "error",
                    f"{assessment.ref}: задание семинара без критериев оценки (rubric)",
                    entity_ref=assessment.ref,
                    fix_hint=_regen_hint(assessment.topic_ref or assessment.ref, ["tasks"]),
                )
            )

    for comp in kit.framework.competencies:
        if comp.labor_functions and comp.prof_standard is None:
            issues.append(
                issue(
                    "V-CNT-05",
                    "error",
                    f"Компетенция {comp.ref}: трудовые функции без привязки к профстандарту",
                    entity_ref=comp.ref,
                )
            )
        for lf in comp.labor_functions:
            if not lf.code.strip():
                issues.append(
                    issue(
                        "V-CNT-05",
                        "error",
                        f"Компетенция {comp.ref}: пустой код трудовой функции",
                        entity_ref=comp.ref,
                    )
                )

    for outcome in kit.iter_outcomes():
        if not outcome.text.strip() or _PLACEHOLDER.search(outcome.text):
            issues.append(
                issue(
                    "V-CNT-04",
                    "error",
                    f"Результат {outcome.ref}: пустой или шаблонный текст",
                    entity_ref=outcome.ref,
                )
            )

    return GroupResult(issues=issues, meta={"content_checks": len(issues)})
