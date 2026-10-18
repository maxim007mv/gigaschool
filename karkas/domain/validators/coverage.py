"""karkas.domain.validators.coverage — покрытие, логика, дубли (Д4 §5.8).

Реализованы V-COV-01..04, V-SEQ-01 и V-DUP-01. Источник данных — связи
KitV1: темы ↔ результаты обучения ↔ оценочные средства, поле complexity,
тексты вопросов и (опционально) эмбеддинги ctx.embeddings для косинусных дублей.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karkas.domain.kit import Assessment, KitV1, Outcome, Topic
from karkas.domain.validators.base import GroupResult, cosine, issue, resolve_stage, stem_hash
from karkas.settings import settings

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

_TYPE_LABELS = {"knowledge": "знание", "skill": "умение", "experience": "практический опыт"}


# ---------------------------------------------------------------------------
# V-COV-01/02: покрытие результатов обучения
# ---------------------------------------------------------------------------


def _cov_01(kit: KitV1, outcomes: list[Outcome], topics: list[Topic]) -> list:
    issues = []
    if outcomes and not topics:
        issues.append(
            issue(
                "V-COV-01",
                "error",
                "В программе есть результаты обучения, но нет тем — добавьте темы и привяжите к ним РО",
                entity_ref=None,
            )
        )
    return issues


def _cov_02(kit: KitV1, outcomes: list[Outcome], assessments: list[Assessment]) -> list:
    minimum = settings.min_assessments_per_outcome
    issues = []
    for outcome in outcomes:
        count = sum(1 for a in assessments if outcome.ref in a.outcome_refs)
        if count < minimum:
            issues.append(
                issue(
                    "V-COV-02",
                    "error",
                    f"Результат {outcome.ref} проверяется {count} оценочными средствами — нужно минимум "
                    f"{minimum} (например, тест и практическое задание)",
                    entity_ref=outcome.ref,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# V-COV-03/04: компетенции и привязки
# ---------------------------------------------------------------------------


def _cov_03(kit: KitV1) -> list:
    issues = []
    for competency in kit.framework.competencies:
        present = {o.type for o in competency.outcomes}
        missing = [label for key, label in _TYPE_LABELS.items() if key not in present]
        if missing:
            issues.append(
                issue(
                    "V-COV-03",
                    "warning",
                    f"У компетенции {competency.ref} «{competency.title}» нет результатов: "
                    f"{', '.join(missing)} — дополните карту компетенций (З/У/Н)",
                    entity_ref=competency.ref,
                )
            )
    return issues


def _cov_04(kit: KitV1) -> list:
    issues = []
    outcome_refs = {o.ref for o in kit.iter_outcomes()}
    for topic in kit.iter_topics():
        if not topic.outcome_refs:
            issues.append(
                issue(
                    "V-COV-04",
                    "error",
                    f"У темы {topic.ref} «{topic.title}» не указан ни один результат обучения — привяжите тему к РО",
                    entity_ref=topic.ref,
                )
            )
            continue
        for ref in topic.outcome_refs:
            if ref not in outcome_refs:
                issues.append(
                    issue(
                        "V-COV-04",
                        "error",
                        f"Тема {topic.ref} ссылается на неизвестный результат обучения {ref}",
                        entity_ref=topic.ref,
                    )
                )
    for assessment in kit.content.assessments:
        if not assessment.outcome_refs:
            issues.append(
                issue(
                    "V-COV-04",
                    "error",
                    f"Оценочное средство {assessment.ref} не привязано ни к одному результату обучения — укажите РО",
                    entity_ref=assessment.ref,
                )
            )
        for ref in assessment.outcome_refs:
            if ref not in outcome_refs:
                issues.append(
                    issue(
                        "V-COV-04",
                        "error",
                        f"Оценочное средство {assessment.ref} привязано к неизвестному результату {ref}",
                        entity_ref=assessment.ref,
                    )
                )
    return issues


# ---------------------------------------------------------------------------
# V-SEQ-01: сложность тем не убывает в порядке программы
# ---------------------------------------------------------------------------


def _seq_01(kit: KitV1) -> list:
    ordered: list[Topic] = []
    for module in sorted(kit.framework.modules, key=lambda m: m.number):
        ordered.extend(module.topics)
    issues = []
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if current.complexity < previous.complexity:
            issues.append(
                issue(
                    "V-SEQ-01",
                    "error",
                    f"Тема {current.ref} (сложность {current.complexity}) идёт после темы {previous.ref} "
                    f"(сложность {previous.complexity}) — сначала должны идти базовые темы",
                    entity_ref=current.ref,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# V-DUP-01: повторы вопросов (хэш) и близкие по смыслу (эмбеддинги)
# ---------------------------------------------------------------------------


def _dup_by_hash(kit: KitV1) -> list:
    issues = []
    seen: dict[str, str] = {}
    for assessment in kit.content.assessments:
        digest = stem_hash(assessment.stem)
        first = seen.get(digest)
        if first is not None:
            issues.append(
                issue(
                    "V-DUP-01",
                    "warning",
                    f"Оценочное средство {assessment.ref} повторяет текст {first} — удалите или переформулируйте дубль",
                    entity_ref=assessment.ref,
                )
            )
        else:
            seen[digest] = assessment.ref
    return issues


def _dup_by_embeddings(kit: KitV1, embeddings: dict[str, list[float]]) -> list:
    issues = []
    groups: list[tuple[str, list[str]]] = [
        ("тем", [t.ref for t in kit.iter_topics()]),
        ("оценочных средств", [a.ref for a in kit.content.assessments]),
    ]
    for label, refs in groups:
        known = [ref for ref in refs if ref in embeddings]
        for i, first in enumerate(known):
            for second in known[i + 1 :]:
                score = cosine(embeddings[first], embeddings[second])
                if score >= settings.dup_cosine:
                    issues.append(
                        issue(
                            "V-DUP-01",
                            "warning",
                            f"Близнецы среди {label}: {first} и {second} совпадают по смыслу "
                            f"(косинус {score:.2f} ≥ {settings.dup_cosine:.2f}) — возможно дублирование",
                            entity_ref=second,
                        )
                    )
    return issues


def _dup_01(ctx: ValidationContext) -> tuple[list, dict]:
    kit = ctx.kit
    issues = _dup_by_hash(kit)
    embeddings = ctx.embeddings or {}
    used = bool(embeddings)
    if used:
        issues += _dup_by_embeddings(kit, embeddings)
    meta = {
        "ok": not any(i.severity == "error" for i in issues),
        "count": len(issues),
        "embeddings_used": used,
        "cosine_threshold": settings.dup_cosine,
    }
    return issues, meta


# ---------------------------------------------------------------------------
# Точка входа группы
# ---------------------------------------------------------------------------


def validate(ctx: ValidationContext) -> GroupResult:
    """Все правила группы «Покрытие» и «Логика»."""
    kit = ctx.kit
    outcomes = list(kit.iter_outcomes())
    topics = list(kit.iter_topics())
    assessments = kit.content.assessments

    issues = []
    skipped: list[str] = []
    stage = resolve_stage(ctx)
    if outcomes:
        issues += _cov_01(kit, outcomes, topics)
        if stage == "kit":
            issues += _cov_02(kit, outcomes, assessments)
        else:
            # Оценочные средства появляются на этапе комплекта (S14–S16).
            skipped.append("V-COV-02")
    else:
        skipped += ["V-COV-01", "V-COV-02"]
    if kit.framework.competencies:
        issues += _cov_03(kit)
    else:
        skipped.append("V-COV-03")
    issues += _cov_04(kit)
    issues += _seq_01(kit)

    dup_issues, dup_meta = _dup_01(ctx)
    issues += dup_issues

    meta = {
        "outcomes": len(outcomes),
        "min_assessments": settings.min_assessments_per_outcome,
        "duplicates": dup_meta,
    }
    return GroupResult(issues=issues, skipped=skipped, meta=meta)
