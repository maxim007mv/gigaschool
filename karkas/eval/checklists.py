"""Проверки по пунктам чек-листов ТК-ОБЩ и ТК-1…ТК-5 (детерминированно, без LLM).

Используется в ``tests/eval`` и ``scripts/run_eval.py``. Полный прогон с живыми
моделями — отдельно; здесь — проверки над готовым KitV1.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from karkas.domain.kit import KitV1
from karkas.domain.validators import ValidationContext


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
    bad = [t.ref for m in kit.framework.modules for t in m.topics if t.workload.total == 0]
    return CheckResult(
        "TK-COMMON",
        "TK-ОБЩ-2",
        len(bad) == 0,
        "темы без часов: " + (", ".join(bad) if bad else "нет"),
    )


def _check_acr_docx_structure(kit: KitV1) -> CheckResult:
    """Сверка .docx с эталонами АЦР (V-ACR-01) — пункт «обязательные разделы» из ТК-ОБЩ."""
    from karkas.domain.validators.acr_export import validate_acr_export

    ctx = ValidationContext(kit=kit)
    if ctx.kit.content.assessments or ctx.kit.content.module_programs:
        stage = "kit"
    else:
        return CheckResult("TK-COMMON", "TK-ОБЩ-3", True, "нет содержания — V-ACR пропущен")
    result = validate_acr_export(ValidationContext(kit=kit, stage=stage))
    return CheckResult(
        "TK-COMMON",
        "TK-ОБЩ-3",
        result.ok,
        "структура .docx по эталону АЦР" if result.ok else (result.issues[0].message if result.issues else "V-ACR-01"),
    )


def _full_text_blob(kit: KitV1) -> str:
    parts = [_topic_texts(kit)]
    for comp in kit.framework.competencies:
        for outcome in comp.outcomes:
            parts.append(outcome.text or "")
    for block in kit.content.module_programs:
        body = block.body if isinstance(block.body, dict) else {}
        parts.append(str(body.get("summary") or ""))
    return " ".join(parts).lower()


def _check_tk2_template_and_hours(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 36:
        return CheckResult("TK-2", "TK2-1", True, "не 36 ч — пропуск ТК-2")
    ok_kind = kit.program.kind == "dpp_pk"
    ok_hours = _hours_grand(kit) == 36
    return CheckResult(
        "TK-2",
        "TK2-1",
        ok_kind and ok_hours,
        f"шаблон={kit.program.kind}, итого {_hours_grand(kit)} ч",
    )


def _check_tk2_distance_split(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 36:
        return CheckResult("TK-2", "TK2-2", True, "не ТК-2")
    contact = sum(
        t.workload.lecture + t.workload.practice + t.workload.lab for m in kit.framework.modules for t in m.topics
    )
    distance = sum(t.workload.distance for m in kit.framework.modules for t in m.topics)
    ok = contact > 0 and distance >= 8
    return CheckResult(
        "TK-2",
        "TK2-2",
        ok,
        f"контакт={contact}, дистанционно={distance} (ожид. ≥8)",
    )


def _check_tk2_ethics_topic(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 36:
        return CheckResult("TK-2", "TK2-4", True, "не ТК-2")
    blob = _full_text_blob(kit)
    ok = any(k in blob for k in ("этик", "персональн", "защит", "риск"))
    return CheckResult("TK-2", "TK2-4", ok, "тема этики/ПДн в текстах" if ok else "нет этики/ПДн в темах и РО")


def _check_tk2_prof_standard(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 36:
        return CheckResult("TK-2", "TK2-3", True, "не ТК-2")
    linked = [c.ref for c in kit.framework.competencies if c.prof_standard]
    return CheckResult(
        "TK-2",
        "TK2-3",
        len(linked) > 0,
        "компетенции с профстандартом: " + (", ".join(linked) if linked else "нет"),
    )


def _check_tk3_hours_calendar(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 72:
        return CheckResult("TK-3", "TK3-1", True, "не 72 ч — пропуск ТК-3")
    cal = kit.framework.calendar
    ok_h = _hours_grand(kit) == 72
    ok_cal = cal is not None and cal.weeks == 4
    return CheckResult(
        "TK-3",
        "TK3-1",
        ok_h and ok_cal,
        f"итого {_hours_grand(kit)} ч, недель={cal.weeks if cal else '—'}",
    )


def _check_tk3_modules_stack(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 72:
        return CheckResult("TK-3", "TK3-2", True, "не ТК-3")
    blob = _full_text_blob(kit)
    need = ("pandas", "sql")
    missing = [k for k in need if k not in blob]
    viz = "визуал" in blob or "matplotlib" in blob or "график" in blob
    ok = len(missing) == 0 and viz
    detail = "нет: " + ", ".join(missing) if missing else "pandas/sql есть"
    if not viz:
        detail += "; визуализация не найдена"
    return CheckResult("TK-3", "TK3-2", ok, detail)


def _check_tk3_python_intro(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 72:
        return CheckResult("TK-3", "TK3-3", True, "не ТК-3")
    blob = _full_text_blob(kit)
    ok = "python" in blob or "питон" in blob
    return CheckResult("TK-3", "TK3-3", ok, "вводный Python" if ok else "нет вводного блока Python")


def _check_tk4_hours_after_clarify(kit: KitV1) -> CheckResult:
    """ТК4-5: после уточнений — ПК и ровно 72 ч (на готовом комплекте)."""
    title = (kit.program.title or "").lower()
    cyber = "кибер" in title or "кибер" in _full_text_blob(kit)
    if not cyber and kit.program.total_hours != 72:
        return CheckResult("TK-4", "TK4-5", True, "не сценарий ТК-4")
    ok = kit.program.kind == "dpp_pk" and kit.program.total_hours == 72 and _hours_grand(kit) == 72
    return CheckResult(
        "TK-4",
        "TK4-5",
        ok,
        f"шаблон={kit.program.kind}, Σ={_hours_grand(kit)}, заявлено {kit.program.total_hours}",
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
        t.workload.lecture + t.workload.practice + t.workload.lab for m in kit.framework.modules for t in m.topics
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
    topic_to_module = {t.ref: mod.ref for mod in kit.framework.modules for t in mod.topics}
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


def _check_tk1_template_and_practice(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 16:
        return CheckResult("TK-1", "TK1-1", True, "не ТК-1")
    practice = sum(t.workload.practice for m in kit.framework.modules for t in m.topics)
    ok = kit.program.kind == "dop" and practice >= 8
    return CheckResult("TK-1", "TK1-1", ok, f"шаблон={kit.program.kind}, практика {practice} ч")


def _check_tk1_calendar(kit: KitV1) -> CheckResult:
    if kit.program.total_hours != 16:
        return CheckResult("TK-1", "TK1-3", True, "не ТК-1")
    cal = kit.framework.calendar
    if cal is None:
        return CheckResult("TK-1", "TK1-3", False, "календарь не задан")
    sessions = [s for s in cal.sessions if s.hours == 2]
    ok = len(sessions) == 8 and cal.weeks <= 4
    return CheckResult("TK-1", "TK1-3", ok, f"занятий={len(sessions)}, недель={cal.weeks}")


def _check_tk5_total_256(kit: KitV1) -> CheckResult:
    if kit.program.form != "internship":
        return CheckResult("TK-5", "TK5-1", True, "не стажировка")
    ss = sum(t.workload.self_study for m in kit.framework.modules for t in m.topics)
    ok = (
        kit.program.total_hours == 256
        and _hours_grand(kit) == 256
        and ss == 254
        and kit.framework.final_attestation.hours == 2
    )
    return CheckResult(
        "TK-5",
        "TK5-1",
        ok,
        f"Σ={_hours_grand(kit)}, СРС={ss}, ИА={kit.framework.final_attestation.hours}",
    )


_COMMON: tuple[Callable[[KitV1], CheckResult], ...] = (
    _check_hours_match,
    _check_no_zero_topics,
    _check_acr_docx_structure,
)

_BY_CASE: dict[str, tuple[Callable[[KitV1], CheckResult], ...]] = {
    "tk1": (_check_tk1_template_and_practice, _check_tk1_calendar, _check_dop_no_prof_standard),
    "tk2": (
        _check_tk2_template_and_hours,
        _check_tk2_distance_split,
        _check_tk2_prof_standard,
        _check_tk2_ethics_topic,
    ),
    "tk3": (
        _check_tk3_hours_calendar,
        _check_tk3_modules_stack,
        _check_tk3_python_intro,
        lambda k: _check_keywords(k, "TK-3", "TK3-8", ["банк", "клиент", "задолжен"]),
    ),
    "tk4": (_check_tk4_hours_after_clarify,),
    "tk5": (
        _check_tk5_total_256,
        _check_internship_self_study,
        _check_calendar_internship,
        lambda k: _check_keywords(
            k,
            "TK-5",
            "TK5-5",
            ["linux", "сет", "контейнер", "ci/cd", "мониторинг", "инфраструктур", "iac", "cloud"],
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
