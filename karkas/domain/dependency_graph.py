"""karkas.domain.dependency_graph — граф влияния точечных правок (Д4 §5.9).

`closure(kit, target_ref)` — элементы комплекта, которые пересобираются при
правке target_ref (для POST /edits, dry_run → «affected»):

- тема T2.3 → [T2.3, LP-T2.3, SL-T2.3, оценочные средства темы (sorted),
  MP-M2, источники темы (sorted)] — порядок из примера Д4 §6.5;
- результат LO2.2 → [LO2.2, темы с этим РО (sorted), оценочные средства
  с этим РО (sorted)];
- оценочное средство → [сам ref];
- модуль M2 → [MP-M2, темы модуля по порядку];
- слайды/план лекции/раздел/источник → [сам ref] («не меняется всё остальное»).

`unchanged(kit, target_ref)` — ["hours", "competencies"] плюс все ref
комплекта, не попавшие в closure (sorted) — для ответа dry_run.
Неизвестный ref → ValueError с понятным текстом (API → 404 EDIT_TARGET_NOT_FOUND).
"""

from __future__ import annotations

from karkas.domain.kit import (
    Assessment,
    ContentBlock,
    KitV1,
    Module,
    Outcome,
    Source,
    Topic,
    find_assessment,
    find_content_block,
    find_module,
    find_outcome,
    find_topic,
)


def _dedupe(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def _topic_of(kit: KitV1, ref: str) -> Topic | None:
    return find_topic(kit, ref)


def _module_ref_of_topic(kit: KitV1, ref: str) -> str | None:
    for module in kit.framework.modules:
        if any(topic.ref == ref for topic in module.topics):
            return module.ref
    return None


def _assessments_of_topic(kit: KitV1, topic_ref: str) -> list[Assessment]:
    return sorted(
        (a for a in kit.content.assessments if a.topic_ref == topic_ref),
        key=lambda a: a.ref,
    )


def _assessments_of_outcome(kit: KitV1, outcome_ref: str) -> list[Assessment]:
    return sorted(
        (a for a in kit.content.assessments if outcome_ref in a.outcome_refs),
        key=lambda a: a.ref,
    )


def _topics_of_outcome(kit: KitV1, outcome_ref: str) -> list[Topic]:
    return sorted(
        (t for t in kit.iter_topics() if outcome_ref in t.outcome_refs),
        key=lambda t: t.ref,
    )


def _topic_refs(source: Source) -> list[str]:
    """Связи источника с темами (Source.topic_refs; поле может отсутствовать)."""
    refs = getattr(source, "topic_refs", None) or []
    return [str(ref) for ref in refs]


def _sources_of_topic(kit: KitV1, topic_ref: str) -> list[Source]:
    return sorted(
        (s for s in kit.content.sources if topic_ref in _topic_refs(s)),
        key=lambda s: s.ref,
    )


def _closure_topic(kit: KitV1, topic: Topic) -> list[str]:
    content = kit.content
    lecture_refs = [f"LP-{topic.ref}"] + [
        block.ref for block in content.lecture_plans if block.topic_ref == topic.ref
    ]
    slides_refs = [f"SL-{topic.ref}"] + [
        block.ref for block in content.slides if block.topic_ref == topic.ref
    ]
    module_ref = _module_ref_of_topic(kit, topic.ref)
    module_program_refs: list[str] = []
    if module_ref is not None:
        module_program_refs = [f"MP-{module_ref}"] + [
            block.ref
            for block in content.module_programs
            if block.module_ref == module_ref and block.kind == "module_program"
        ]
    source_refs = [s.ref for s in _sources_of_topic(kit, topic.ref)]
    return _dedupe(
        [topic.ref]
        + _dedupe(lecture_refs)
        + _dedupe(slides_refs)
        + [a.ref for a in _assessments_of_topic(kit, topic.ref)]
        + _dedupe(module_program_refs)
        + source_refs
    )


def _closure_outcome(kit: KitV1, outcome: Outcome) -> list[str]:
    return _dedupe(
        [outcome.ref]
        + [t.ref for t in _topics_of_outcome(kit, outcome.ref)]
        + [a.ref for a in _assessments_of_outcome(kit, outcome.ref)]
    )


def _closure_module(kit: KitV1, module: Module) -> list[str]:
    return _dedupe([f"MP-{module.ref}"] + [topic.ref for topic in module.topics])


def _closure_block(kit: KitV1, block: ContentBlock) -> list[str]:
    if block.kind == "module_program" and block.module_ref is not None:
        module = find_module(kit, block.module_ref)
        if module is not None:
            return _dedupe([block.ref] + [topic.ref for topic in module.topics])
    return [block.ref]


def closure(kit: KitV1, target_ref: str) -> list[str]:
    """Все элементы комплекта, которые затрагивает правка target_ref."""
    topic = _topic_of(kit, target_ref)
    if topic is not None:
        return _closure_topic(kit, topic)
    outcome = find_outcome(kit, target_ref)
    if outcome is not None:
        return _closure_outcome(kit, outcome)
    assessment = find_assessment(kit, target_ref)
    if assessment is not None:
        return [assessment.ref]
    module = find_module(kit, target_ref)
    if module is not None:
        return _closure_module(kit, module)
    block = find_content_block(kit, target_ref)
    if block is not None:
        return _closure_block(kit, block)
    source = next((s for s in kit.content.sources if s.ref == target_ref), None)
    if source is not None:
        return [source.ref]

    known_competency = any(c.ref == target_ref for c in kit.framework.competencies)
    if known_competency:
        raise ValueError(
            f"Компетенция {target_ref!r} меняется только целиком в каркасе; "
            "точечная правка C*-элементов не поддерживается"
        )
    raise ValueError(
        f"Неизвестный элемент комплекта: {target_ref!r}. Проверьте ref: тема T*, результат LO*, "
        "оценочное средство, модуль M*, блок содержания или источник SRC-*"
    )


def _all_refs(kit: KitV1) -> list[str]:
    refs: list[str] = []
    refs += [c.ref for c in kit.framework.competencies]
    refs += [o.ref for o in kit.iter_outcomes()]
    refs += [m.ref for m in kit.framework.modules]
    refs += [t.ref for t in kit.iter_topics()]
    refs += [a.ref for a in kit.content.assessments]
    for group in (
        kit.content.module_programs,
        kit.content.lecture_plans,
        kit.content.slides,
        kit.content.sections,
    ):
        refs += [b.ref for b in group]
    refs += [s.ref for s in kit.content.sources]
    return _dedupe(refs)


def unchanged(kit: KitV1, target_ref: str) -> list[str]:
    """Элементы, которые правка не затрагивает (для ответа dry_run)."""
    affected = set(closure(kit, target_ref))
    rest = sorted(ref for ref in _all_refs(kit) if ref not in affected)
    return ["hours", "competencies", *rest]
