"""karkas.domain.validators.request — явные пожелания брифа (Д4 §5.8, V-REQ-01).

Проверяется:
- длительность итоговой аттестации > 0 и её согласованность между карточкой
  программы и каркасом;
- требование слайдов, зафиксированное в profile.notes: бриф называет модули
  (M2, «модуль 2»), темы (T1.1) или занятия по номеру («занятия 1 и 2» —
  номер занятия сопоставляется с темой через календарь); если бриф просит
  слайды без уточнений — минимум один блок слайдов. На стадии каркаса
  проверка откладывается;
- доля практики из запроса ведётся правилом V-HRS-05 (здесь фиксируется
  требование в мете группы, чтобы отчёт показывал, что пожелание проверено).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from karkas.domain.kit import KitV1
from karkas.domain.validators.base import GroupResult, issue, resolve_stage

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

_SLIDES_RE = re.compile(r"слайд", re.IGNORECASE)
_MODULE_REF_RE = re.compile(r"\bM\d{1,2}\b")
_TOPIC_REF_RE = re.compile(r"\bT\d{1,2}\.\d{1,2}\b")
_MODULE_WORD_RE = re.compile(r"\bмодул\w*\s+(\d{1,2})", re.IGNORECASE)
_SESSION_WORD_RE = re.compile(r"заняти[еяй]\w*\s+(\d{1,2})", re.IGNORECASE)


def _slide_issues(kit: KitV1, notes: str) -> list:
    slides = [b for b in kit.content.slides if b.kind == "slides"]
    module_refs = {m.group(0) for m in _MODULE_REF_RE.finditer(notes)}
    module_refs |= {f"M{m.group(1)}" for m in _MODULE_WORD_RE.finditer(notes)}
    topic_refs = {t.group(0) for t in _TOPIC_REF_RE.finditer(notes)}
    calendar = kit.framework.calendar
    sessions = calendar.sessions if calendar is not None else []
    for match in _SESSION_WORD_RE.finditer(notes):
        session = next((s for s in sessions if s.seq == int(match.group(1))), None)
        if session is not None and session.topic_ref:
            topic_refs.add(session.topic_ref)
    issues = []
    if not module_refs and not topic_refs:
        if not slides:
            issues.append(
                issue(
                    "V-REQ-01",
                    "error",
                    "Бриф просит слайды, но ни одного блока слайдов нет — слайды обязательны минимум для одного модуля",
                )
            )
        return issues
    for module_ref in sorted(module_refs):
        if not any(b.module_ref == module_ref for b in slides):
            issues.append(
                issue(
                    "V-REQ-01",
                    "error",
                    f"Бриф просит слайды для модуля {module_ref}, но слайды для него не сгенерированы",
                    entity_ref=module_ref,
                )
            )
    for topic_ref in sorted(topic_refs):
        if not any(b.topic_ref == topic_ref for b in slides):
            issues.append(
                issue(
                    "V-REQ-01",
                    "error",
                    f"Бриф просит слайды для занятия {topic_ref}, но слайды для него не сгенерированы",
                    entity_ref=topic_ref,
                )
            )
    return issues


def validate(ctx: ValidationContext) -> GroupResult:
    """Проверка явных пожеланий запроса."""
    kit = ctx.kit
    issues = []

    framework_fa = kit.framework.final_attestation
    header_fa = kit.program.final_attestation
    if framework_fa.hours <= 0:
        issues.append(
            issue(
                "V-REQ-01",
                "error",
                "Итоговая аттестация занимает 0 ч — задайте длительность (форма ИА из брифа)",
            )
        )
    if header_fa.hours != framework_fa.hours:
        issues.append(
            issue(
                "V-REQ-01",
                "error",
                f"Итоговая аттестация: в карточке программы {header_fa.hours} ч, в каркасе "
                f"{framework_fa.hours} ч — значения должны совпадать",
            )
        )

    notes = kit.profile.notes or ""
    slides_requested = bool(_SLIDES_RE.search(notes))
    if slides_requested and resolve_stage(ctx) == "kit":
        issues += _slide_issues(kit, notes)

    meta = {
        "min_practice_share_pct": kit.profile.constraints.min_practice_share_pct,
        "slides_requested": slides_requested,
        "final_attestation_hours": framework_fa.hours,
    }
    return GroupResult(issues=issues, meta=meta)
