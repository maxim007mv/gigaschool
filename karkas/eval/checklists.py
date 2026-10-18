"""Проверки по пунктам чек-листов ТК-ОБЩ и ТК-1…ТК-5 (детерминированно, без LLM).

Используется в ``tests/eval`` и ``scripts/run_eval.py``. Полный прогон с живыми
моделями — отдельно; здесь — проверки над готовым KitV1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from karkas.domain.kit import KitV1
from karkas.domain.validators import ValidationContext, run_validation

@dataclass(frozen=True)
class CheckResult:
    """Один пункт чек-листа."""

    case_id: str
    item_id: str
    passed: bool
    detail: str


def _topic_texts(kit: KitV1) -> str:
    parts: list[str] = []
    for mod in kit.framework.modules:
        for topic in mod.topics:
            parts.append(topic.title or "")
            parts.append(topic.ref)
    return " ".join(parts).lower()


def _hours_grand(kit: KitV1) -> int:
    return kit.grand_total()


def _check_hours_match(kit: KitV1) -> CheckResult:
    grand = _hours_grand(kit)
    ok = grand == kit.program.total_hours
    return CheckResult(
        "TK-COMMON",
        "TK-ОБЩ-1",
        ok,
        f"Σ тем + ИА = {grand}, заявлено {kit.program.total_hours} ч",
    )


def _check_no_zero_topics(kit: KitV1) -> CheckResult:
    bad = [
        t.ref
        for m in kit.framework.modules
        for t in m.topics
        if t.workload.total == 0
    ]
    return CheckResult(
        "TK-COMMON",
        "TK-ОБЩ-2",
        len(bad) == 0,
        "темы без часов: " + (", ".join(bad) if bad else "нет"),
    )


def _check_validation_passed(kit: KitV1) -> CheckResult:
    report = run_validation(ValidationContext(kit=kit))
    return CheckResult(
        "TK-COMMON",
        "TK-ОБЩ-3",
        report.passed,
        f"самопроверка: errors={len(report.errors)}",
    )


def _check_dop_no_prof_standard(kit: KitV1) -> CheckResult:
    if kit.program.kind != "dop":
        return CheckResult("TK-1", "TK1-9", True, "не ДОП — пропуск")
    bad = [c.ref for c in kit.framework.competencies if c.prof_standard]
    return CheckResult(
        "TK-1",
        "TK1-9",
        len(bad) == 0,
        "профстандарты в ДОП: " + (", ".join(bad) if bad else "нет"),
    )


def _check_keywords(kit: KitV1, case: str, item: str, keywords: Iterable[str]) -> CheckResult:
    blob = _topic_texts(kit)
    missing = [k for k in keywords if k.lower() not in blob]
    return CheckResult(
        case,
        item,
        len(missing) == 0,
        "не найдено в темах: " + (", ".join(missing) if missing else "все ключевые слова есть"),
    )


def _check_internship_self_study(kit: KitV1) -> CheckResult:
    if kit.program.form != "internship":
        return CheckResult("TK-5", "TK5-2", True, "не стажировка — пропуск")
    contact = sum(
        t.workload.lecture + t.workload.practice + t.workload.lab
        for m in kit.framework.modules
        for t in m.topics
    )
    ok = contact == 0 and all(
        t.workload.practice == 0 and t.workload.lab == 0 and t.workload.lecture == 0
        for m in kit.framework.modules
        for t in m.topics
    )
    return CheckResult(
        "TK-5",
        "TK5-2",
        ok,
        f"контактных часов по темам: {contact}",
    )


def _check_calendar_internship(kit: KitV1) -> CheckResult:
    if kit.program.form != "internship":
        return CheckResult("TK-5", "TK5-4", True, "не стажировка — пропуск")
    cal = kit.framework.calendar
    if cal is None:
        return CheckResult("TK-5", "TK5-4", False, "календарь не задан")
    ok = 50 <= cal.days <= 70 and cal.max_hours_per_day <= 4
    return CheckResult(
        "TK-5",
        "TK5-4",
        ok,
        f"дней={cal.days}, max/день={cal.max_hours_per_day}",
    )


def _check_interview_per_module(kit: KitV1) -> CheckResult:
    if kit.program.form != "internship":
        return CheckResult("TK-5", "TK5-6", True, "не стажировка — пропуск")
    missing: list[str] = []
    topic_to_module = {
        t.ref: mod.ref for mod in kit.framework.modules for t in mod.topics
    }
    modules_with_interview: set[str] = set()
    for a in kit.content.assessments:
        if a.kind != "interview_question" or not a.topic_ref:
            continue
        mod_ref = topic_to_module.get(a.topic_ref)
        if mod_ref:
            modules_with_interview.add(mod_ref)
    for mod in kit.framework.modules:
        if mod.ref not in modules_with_interview:
            missing.append(mod.ref)
    return CheckResult(
        "TK-5",
        "TK5-6",
        len(missing) == 0,
        "модули без собеседования: " + (", ".join(missing) if missing else "нет"),
    )


_COMMON: tuple[Callable[[KitV1], CheckResult], ...] = (
    _check_hours_match,
    _check_no_zero_topics,
    _check_validation_passed,
)

_BY_CASE: dict[str, tuple[Callable[[KitV1], CheckResult], ...]] = {
    "tk1": (_check_dop_no_prof_standard,),
    "tk5": (
        _check_internship_self_study,
        _check_calendar_internship,
        lambda k: _check_keywords(
            k,
            "TK-5",
            "TK5-5",
            ["linux", "сет", "контейнер", "ci/cd", "мониторинг", "инфраструктур"],
        ),
        _check_interview_per_module,
    ),
}


def run_common_checklist(kit: KitV1) -> list[CheckResult]:
    return [fn(kit) for fn in _COMMON]


def run_checklist(kit: KitV1, case_key: str) -> list[CheckResult]:
    """case_key: tk1, tk2, … tk5 (нижний регистр)."""
    key = case_key.lower().strip()
    fns = _BY_CASE.get(key, ())
    return run_common_checklist(kit) + [fn(kit) for fn in fns]


def format_report(results: list[CheckResult]) -> str:
    passed = sum(1 for r in results if r.passed)
    lines = [f"Пройдено {passed}/{len(results)} пунктов"]
    for r in results:
        mark = "OK" if r.passed else "FAIL"
        lines.append(f"  [{mark}] {r.case_id} {r.item_id}: {r.detail}")
    return "\n".join(lines)
