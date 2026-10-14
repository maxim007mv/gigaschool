"""karkas.domain.validators.hours — правила арифметики часов и графика (Д4 §5.8).

Реализованы V-HRS-01..09 и V-CAL-01. Источник данных — только KitV1:
часы тем (единственное место хранения часов), карточка программы,
ограничения профиля и календарный график.

V-HRS-06 («ЛК + ПР + ЛБ + СРС + контроль = "Всего" по строке») и V-HRS-07
(«Σ тем = часы модуля») в KitV1 не имеют хранимых итогов, поэтому проверяются
там, где итог объявлен: per-row итоги образца (`ctx.declared_totals["rows"]`),
часы рабочей программы модуля (body блока `module_program`, ключ `hours`)
и `ctx.declared_totals["modules"]`. Структурная сумма видов работ по строке
проверяется всегда и может дать сбой только при повреждённой модели.
"""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING, Any

from karkas.domain.kit import KitV1, Topic
from karkas.domain.validators.base import GroupResult, issue

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

_REBALANCE_HINT: dict[str, Any] = {"endpoint": "framework:rebalance", "body": {"keep_locked": True}}
_ACTIVITY_LABELS = {
    "lecture": "ЛК",
    "practice": "ПР",
    "lab": "ЛБ",
    "self_study": "СРС",
    "current_control": "контроль",
}


def _rus_row(workload: Any) -> str:
    parts = [f"{label} {workload.by_activity(name)}" for name, label in _ACTIVITY_LABELS.items()]
    return f"{' + '.join(parts)} = {workload.total}"


def _is_internship(kit: KitV1) -> bool:
    """Стажировка: либо ограничение self_study_only, либо форма «internship»."""
    return kit.profile.constraints.self_study_only or kit.program.form == "internship"


# ---------------------------------------------------------------------------
# V-HRS-01..05: карточка программы, строки, стажировка, доля практики
# ---------------------------------------------------------------------------


def _hrs_01(kit: KitV1) -> list:
    topics_total = kit.framework_workload().total
    ia = kit.framework.final_attestation.hours
    declared = kit.program.total_hours
    grand = topics_total + ia
    if grand == declared:
        return []
    return [
        issue(
            "V-HRS-01",
            "error",
            f"Сумма часов тем {topics_total} ч + итоговая аттестация {ia} ч = {grand} ч, "
            f"а в запросе {declared} ч (расхождение {grand - declared:+d} ч)",
            fix_hint=dict(_REBALANCE_HINT),
        )
    ]


def _hrs_02_03(kit: KitV1) -> list:
    issues = []
    for topic in kit.iter_topics():
        if topic.workload.total <= 0:
            issues.append(
                issue(
                    "V-HRS-02",
                    "error",
                    f"У темы {topic.ref} «{topic.title}» не указаны часы — распишите часы по видам работ",
                    entity_ref=topic.ref,
                    fix_hint=dict(_REBALANCE_HINT),
                )
            )
    for module in kit.framework.modules:
        if not module.topics:
            issues.append(
                issue(
                    "V-HRS-03",
                    "error",
                    f"Модуль {module.ref} «{module.title}» не содержит тем — добавьте темы с часами",
                    entity_ref=module.ref,
                )
            )
        elif module.workload.total <= 0:
            issues.append(
                issue(
                    "V-HRS-03",
                    "error",
                    f"У модуля {module.ref} «{module.title}» нет часов — у тем не заполнены часы",
                    entity_ref=module.ref,
                    fix_hint=dict(_REBALANCE_HINT),
                )
            )
    return issues


def _hrs_04(kit: KitV1) -> list:
    """Стажировка без аудиторных занятий: ЛК = ПР = ЛБ = 0 во всех строках."""
    if not _is_internship(kit):
        return []
    issues = []
    for topic in kit.iter_topics():
        contact = topic.workload.contact
        if contact > 0:
            issues.append(
                issue(
                    "V-HRS-04",
                    "error",
                    f"Стажировка: у темы {topic.ref} указаны аудиторные часы ({_rus_row(topic.workload)}) — "
                    "допустима только самостоятельная работа",
                    entity_ref=topic.ref,
                )
            )
    return issues


def _hrs_05(kit: KitV1) -> list:
    share_pct = kit.profile.constraints.min_practice_share_pct
    if share_pct <= 0:
        return []
    threshold = ceil(share_pct / 100.0 * kit.program.total_hours)
    practice_lab = sum(t.workload.practice + t.workload.lab for t in kit.iter_topics())
    if practice_lab >= threshold:
        return []
    return [
        issue(
            "V-HRS-05",
            "error",
            f"Доля практики {practice_lab} ч из {kit.program.total_hours} ч ниже требуемых {share_pct:g} % "
            f"(нужно не менее {threshold} ч практики и лабораторных)",
            fix_hint={
                "endpoint": "framework:rebalance",
                "body": {"keep_locked": True, "min_practice_share_pct": share_pct},
            },
        )
    ]


# ---------------------------------------------------------------------------
# V-HRS-06..08: итоги строк, модуль = Σ тем, кратность
# ---------------------------------------------------------------------------


def _declared_rows(ctx: "ValidationContext") -> dict[str, Any]:
    declared = ctx.declared_totals or {}
    rows = declared.get("rows")
    return rows if isinstance(rows, dict) else {}


def _hrs_06(ctx: "ValidationContext") -> list:
    """ЛК + ПР + ЛБ + СРС + контроль = «Всего» по строке.

    Итог строки хранится только в образце (ctx.declared_totals["rows"]),
    поэтому сверяем объявленное «Всего» с суммой видов работ.
    """
    issues = []
    for ref, value in _declared_rows(ctx).items():
        topic = next((t for t in ctx.kit.iter_topics() if t.ref == ref), None)
        if topic is None:
            continue
        declared_total: Any = value.get("total") if isinstance(value, dict) else value
        if declared_total is None or isinstance(declared_total, bool):
            continue
        try:
            declared_int = int(declared_total)
        except (TypeError, ValueError):
            continue
        if declared_int != topic.workload.total:
            issues.append(
                issue(
                    "V-HRS-06",
                    "error",
                    f"Строка {ref}: заявлено «Всего» {declared_int} ч, а сумма видов работ — "
                    f"{_rus_row(topic.workload)}; распишите или исправьте итог",
                    entity_ref=ref,
                    fix_hint=dict(_REBALANCE_HINT),
                )
            )
    return issues


def _module_declared_hours(kit: KitV1, module_ref: str) -> int | None:
    for block in kit.content.module_programs:
        if block.module_ref != module_ref or block.kind != "module_program":
            continue
        value = block.body.get("hours")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def _hrs_07(ctx: "ValidationContext") -> list:
    """Σ тем = часы модуля (на всех уровнях: тема → модуль → программа).

    Часы модуля в KitV1 вычисляются, поэтому проверяются объявленные итоги:
    body блока module_program («hours») и ctx.declared_totals["modules"].
    """
    kit = ctx.kit
    issues = []
    declared_modules = (ctx.declared_totals or {}).get("modules")
    declared_modules = declared_modules if isinstance(declared_modules, dict) else {}
    for module in kit.framework.modules:
        computed = module.workload.total
        declared = _module_declared_hours(kit, module.ref)
        if declared is None and module.ref in declared_modules:
            value = declared_modules[module.ref]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                declared = int(value)
        if declared is not None and declared != computed:
            issues.append(
                issue(
                    "V-HRS-07",
                    "error",
                    f"Модуль {module.ref}: заявлено {declared} ч, а сумма тем — {computed} ч "
                    f"(расхождение {computed - declared:+d} ч)",
                    entity_ref=module.ref,
                    fix_hint=dict(_REBALANCE_HINT),
                )
            )
    total_sum = sum(m.workload.total for m in kit.framework.modules)
    all_topics = kit.framework_workload().total
    if kit.framework.modules and total_sum != all_topics:
        # Страховка от повреждённой модели: Module.workload обязан быть суммой тем.
        issues.append(
            issue(
                "V-HRS-07",
                "error",
                f"Сумма часов модулей {total_sum} ч не совпадает с суммой часов тем {all_topics} ч",
                fix_hint=dict(_REBALANCE_HINT),
            )
        )
    return issues


def _hrs_08(kit: KitV1) -> list:
    unit = kit.profile.constraints.unit_hours
    if unit <= 1:
        return []
    issues = []
    for topic in kit.iter_topics():
        total = topic.workload.total
        if total % unit != 0:
            issues.append(
                issue(
                    "V-HRS-08",
                    "error",
                    f"Часы темы {topic.ref} ({total} ч) не кратны длительности занятия {unit} ч "
                    f"(остаток {total % unit} ч)",
                    entity_ref=topic.ref,
                    fix_hint=dict(_REBALANCE_HINT),
                )
            )
    return issues


# ---------------------------------------------------------------------------
# V-HRS-09: ДОТ и очные часы разделены явно
# ---------------------------------------------------------------------------


def _hrs_09(kit: KitV1) -> list:
    need_distance = kit.profile.constraints.distance_share_pct > 0 or kit.program.form == "distance"
    issues = []
    topics = list(kit.iter_topics())
    total_contact = sum(t.workload.contact for t in topics)
    total_distance = sum(t.workload.distance for t in topics)
    if need_distance and total_contact > 0 and total_distance == 0:
        issues.append(
            issue(
                "V-HRS-09",
                "error",
                "В программе есть дистанционная часть, но часы с применением ДОТ нигде не выделены "
                "в поле «дистанционно» — укажите их явно по темам",
            )
        )
    for topic in topics:
        # Иерархия «дистанционные — часть контактных» проверяется ВСЕГДА, даже если
        # форму с ДОТ позже сняли: противоречивые часы не должны оставаться незамеченными.
        if topic.workload.distance > topic.workload.contact:
            issues.append(
                issue(
                    "V-HRS-09",
                    "error",
                    f"Тема {topic.ref}: дистанционных часов {topic.workload.distance} больше контактных "
                    f"({topic.workload.contact}) — дистанционные часы являются их частью",
                    entity_ref=topic.ref,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# V-CAL-01: календарный график
# ---------------------------------------------------------------------------


def _calendar(kit: KitV1) -> tuple[list, list[str]]:
    calendar = kit.framework.calendar
    if calendar is None:
        return [], ["V-CAL-01"]
    if not calendar.sessions:
        return (
            [
                issue(
                    "V-CAL-01",
                    "error",
                    "Календарный график не содержит занятий — разложите часы тем по неделям и дням",
                )
            ],
            [],
        )

    issues = []
    constraints = kit.profile.constraints
    if calendar.max_hours_per_day > constraints.max_hours_per_day:
        issues.append(
            issue(
                "V-CAL-01",
                "error",
                f"График допускает {calendar.max_hours_per_day} ч в день, а в ограничениях запроса — "
                f"{constraints.max_hours_per_day} ч",
            )
        )
    min_weeks = ceil(calendar.days / calendar.days_per_week)
    if calendar.weeks < min_weeks:
        issues.append(
            issue(
                "V-CAL-01",
                "error",
                f"Дней в графике {calendar.days}, а недель {calendar.weeks}: при {calendar.days_per_week} "
                f"учебных днях в неделю нужно минимум {min_weeks} недель",
            )
        )

    topic_refs = {t.ref for t in kit.iter_topics()}
    day_hours: dict[tuple[int, int], int] = {}
    ia_hours = 0
    for session in calendar.sessions:
        if session.hours > calendar.max_hours_per_day:
            issues.append(
                issue(
                    "V-CAL-01",
                    "error",
                    f"Занятие {session.seq} (неделя {session.week}, день {session.day}) длится "
                    f"{session.hours} ч — больше допустимых {calendar.max_hours_per_day} ч в день",
                    entity_ref=session.topic_ref,
                )
            )
        if session.week > calendar.weeks:
            issues.append(
                issue(
                    "V-CAL-01",
                    "error",
                    f"Занятие {session.seq} стоит в неделе {session.week}, а срок программы — "
                    f"{calendar.weeks} недель",
                    entity_ref=session.topic_ref,
                )
            )
        if session.day > calendar.days:
            issues.append(
                issue(
                    "V-CAL-01",
                    "error",
                    f"Занятие {session.seq} стоит в учебный день {session.day}, а всего дней — "
                    f"{calendar.days}",
                    entity_ref=session.topic_ref,
                )
            )
        if session.topic_ref is not None:
            if session.topic_ref not in topic_refs:
                issues.append(
                    issue(
                        "V-CAL-01",
                        "error",
                        f"Занятие {session.seq} ссылается на несуществующую тему {session.topic_ref}",
                        entity_ref=session.topic_ref,
                    )
                )
        else:
            ia_hours += session.hours
        key = (session.week, session.day)
        day_hours[key] = day_hours.get(key, 0) + session.hours

    for (week, day), hours in sorted(day_hours.items()):
        if hours > calendar.max_hours_per_day:
            issues.append(
                issue(
                    "V-CAL-01",
                    "error",
                    f"В день {day} недели {week} суммарно {hours} ч занятий — больше допустимых "
                    f"{calendar.max_hours_per_day} ч",
                )
            )

    lecture_days = len({(s.week, s.day) for s in calendar.sessions})
    if lecture_days != calendar.days:
        issues.append(
            issue(
                "V-CAL-01",
                "error",
                f"В графике занято {lecture_days} учебных дней, а заявлено {calendar.days} — "
                "приведите срок и число занятий в соответствие",
            )
        )

    ia_declared = kit.framework.final_attestation.hours
    if ia_hours != ia_declared:
        issues.append(
            issue(
                "V-CAL-01",
                "error",
                f"Итоговая аттестация в графике — {ia_hours} ч, а в карточке программы — {ia_declared} ч",
            )
        )

    sessions_total = sum(s.hours for s in calendar.sessions)
    grand = kit.grand_total()
    if sessions_total != grand:
        issues.append(
            issue(
                "V-CAL-01",
                "error",
                f"Сумма часов занятий в графике {sessions_total} ч, а объём тем с итоговой аттестацией "
                f"{grand} ч — часы должны сходиться",
            )
        )
    return issues, []


# ---------------------------------------------------------------------------
# Точка входа группы
# ---------------------------------------------------------------------------


def validate(ctx: "ValidationContext") -> GroupResult:
    """Все правила группы «Часы» и «График»."""
    kit = ctx.kit
    topics: list[Topic] = list(kit.iter_topics())
    modules = kit.framework.modules

    issues = []
    issues += _hrs_01(kit)
    issues += _hrs_02_03(kit)
    issues += _hrs_04(kit)
    issues += _hrs_05(kit)
    issues += _hrs_06(ctx)
    issues += _hrs_07(ctx)
    issues += _hrs_08(kit)
    issues += _hrs_09(kit)
    calendar_issues, calendar_skipped = _calendar(kit)
    issues += calendar_issues

    meta = {
        "checked": len(topics) + len(modules) + 1,
        "topics": len(topics),
        "modules": len(modules),
    }
    return GroupResult(issues=issues, skipped=calendar_skipped, meta=meta)
