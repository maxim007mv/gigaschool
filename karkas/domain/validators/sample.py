"""karkas.domain.validators.sample — расхождения образца (Д4 §5.8, V-SMP-01).

Если методист передал итоговые строки приложенного образца
(`ctx.declared_totals`), они сверяются с тем, что вычислено из комплекта:
- {'self_study': 174, 'total': 248} — верхнеуровневые итоги;
- {'rows': {'T1.6': 9 или {'practice': 9, 'total': 12}}} — строки тем;
- {'modules': {'M1': 246}} — итоги разделов.

Каждое расхождение — warning плюс строка в `sample_findings` отчёта вида
«Образец: итоговая строка СРС 174 ч ≠ сумме тем 168 ч — не перенесено»
(сценарии Д5 §6.7: образец 248 ч). Нет declared_totals — правило пропускается.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from karkas.domain.kit import KitV1
from karkas.domain.validators.base import GroupResult, issue

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

_ACTIVITY_LABELS = {
    "lecture": "ЛК",
    "practice": "ПР",
    "lab": "ЛБ",
    "self_study": "СРС",
    "current_control": "текущий контроль",
}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _check_totals(kit: KitV1, declared: dict[str, Any]) -> list:
    issues = []
    computed = kit.framework_workload()
    for key, label in _ACTIVITY_LABELS.items():
        if key not in declared:
            continue
        declared_value = _as_int(declared[key])
        if declared_value is None:
            continue
        actual = computed.by_activity(key)
        if declared_value != actual:
            issues.append(
                issue(
                    "V-SMP-01",
                    "warning",
                    f"Образец: итоговая строка {label} {declared_value} ч ≠ сумме тем {actual} ч — не перенесено",
                )
            )
    if "total" in declared:
        declared_value = _as_int(declared["total"])
        actual = kit.grand_total()
        if declared_value is not None and declared_value != actual:
            issues.append(
                issue(
                    "V-SMP-01",
                    "warning",
                    f"Образец: итоговая строка «Всего» {declared_value} ч ≠ сумме тем и ИА {actual} ч — не перенесено",
                )
            )
    if "content_total" in declared:
        declared_value = _as_int(declared["content_total"])
        actual = computed.total
        if declared_value is not None and declared_value != actual:
            issues.append(
                issue(
                    "V-SMP-01",
                    "warning",
                    f"Образец: итог раздела без ИА {declared_value} ч ≠ сумме тем {actual} ч — не перенесено",
                )
            )
    return issues


def _check_rows(kit: KitV1, rows: Any) -> list:
    if not isinstance(rows, dict):
        return []
    topics = {t.ref: t for t in kit.iter_topics()}
    issues = []
    for ref, value in rows.items():
        topic = topics.get(str(ref))
        if topic is None:
            continue
        if isinstance(value, dict):
            for key, label in _ACTIVITY_LABELS.items():
                declared_value = _as_int(value.get(key))
                actual = topic.workload.by_activity(key)
                if declared_value is not None and declared_value != actual:
                    issues.append(
                        issue(
                            "V-SMP-01",
                            "warning",
                            f"Образец: тема {ref}: {label} {declared_value} ч ≠ значению в комплекте "
                            f"{actual} ч — не перенесено",
                            entity_ref=str(ref),
                        )
                    )
            declared_total = _as_int(value.get("total"))
        else:
            declared_total = _as_int(value)
        if declared_total is not None and declared_total != topic.workload.total:
            issues.append(
                issue(
                    "V-SMP-01",
                    "warning",
                    f"Образец: тема {ref}: всего {declared_total} ч ≠ сумме видов работ "
                    f"{topic.workload.total} ч — не перенесено",
                    entity_ref=str(ref),
                )
            )
    return issues


def _check_modules(kit: KitV1, modules: Any) -> list:
    if not isinstance(modules, dict):
        return []
    known = {m.ref: m for m in kit.framework.modules}
    issues = []
    for ref, value in modules.items():
        module = known.get(str(ref))
        declared_value = _as_int(value)
        if module is None or declared_value is None:
            continue
        actual = module.workload.total
        if declared_value != actual:
            issues.append(
                issue(
                    "V-SMP-01",
                    "warning",
                    f"Образец: раздел {ref}: всего {declared_value} ч ≠ сумме тем {actual} ч — не перенесено",
                    entity_ref=str(ref),
                )
            )
    return issues


def validate(ctx: ValidationContext) -> GroupResult:
    """Сверка заявленных итогов образца с комплектом."""
    declared = ctx.declared_totals
    if not declared:
        return GroupResult(skipped=["V-SMP-01"], meta={"mismatches": 0})
    issues = []
    issues += _check_totals(ctx.kit, declared)
    issues += _check_rows(ctx.kit, declared.get("rows"))
    issues += _check_modules(ctx.kit, declared.get("modules"))
    return GroupResult(issues=issues, meta={"mismatches": len(issues)})
