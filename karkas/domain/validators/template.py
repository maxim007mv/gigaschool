"""karkas.domain.validators.template — правила шаблона ДПП/ДОП (Д4 §5.8, §5.12).

Реализованы V-TPL-01..03. Обязательные разделы и способ проверки их
заполненности описаны в `karkas/domain/templates/{dpp_pk,dop}.yaml`:
у каждого раздела есть `filled_by` — набор проверок по данным KitV1
(словарь FILL_CHECKS ниже). На стадии «framework» разделы, требующие
содержимого, откладываются: у каркаса их ещё нет (S10 ≠ S19).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import yaml

from karkas.domain.kit import KitV1
from karkas.domain.validators.base import GroupResult, issue, resolve_stage

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

# Проверки, для которых нужно сгенерированное содержание (не только каркас).
CONTENT_CHECKS = {
    "annotation",
    "assessments",
    "assessments:current_control",
    "assessments:final",
    "module_programs",
    "sources",
    "literature",
    "methodical_materials",
}


# ---------------------------------------------------------------------------
# Проверки заполненности разделов (словарь для filled_by из YAML)
# ---------------------------------------------------------------------------


def _has_template_section(kit: KitV1, code: str) -> bool:
    for block in kit.content.sections:
        if block.kind != "template_section" or not block.body:
            continue
        labels = {
            str(block.ref),
            str(block.body.get("section_code", "")),
            str(block.body.get("code", "")),
        }
        if code in labels or block.ref.endswith(code):
            return True
    return False


def _modules_with_hours(kit: KitV1) -> bool:
    return bool(kit.framework.modules) and any(m.workload.total > 0 for m in kit.framework.modules)


def _all_modules_have_programs(kit: KitV1) -> bool:
    modules = kit.framework.modules
    if not modules:
        return False
    covered = {b.module_ref for b in kit.content.module_programs if b.kind == "module_program"}
    return all(m.ref in covered for m in modules)


def _has_calendar(kit: KitV1) -> bool:
    calendar = kit.framework.calendar
    return calendar is not None and bool(calendar.sessions)


def _has_sources(kit: KitV1) -> bool:
    return any(s.section in ("main", "additional", "internet", "normative") for s in kit.content.sources)


def _has_literature(kit: KitV1) -> bool:
    return any(s.section in ("main", "additional") for s in kit.content.sources)


def _has_normative_basis(kit: KitV1) -> bool:
    return bool(kit.program.legal_basis) or any(s.section == "normative" for s in kit.content.sources)


def _has_annotation(kit: KitV1) -> bool:
    return any(b.kind == "annotation" and bool(b.body) for b in kit.content.sections)


def _has_methodical_materials(kit: KitV1) -> bool:
    return _has_literature(kit) or _has_template_section(kit, "3.2")


FILL_CHECKS: dict[str, Callable[[KitV1], bool]] = {
    "program_header": lambda kit: bool(kit.program.title),
    "goal": lambda kit: bool(kit.framework.goal.strip()),
    "tasks": lambda kit: bool(kit.framework.tasks),
    "outcomes": lambda kit: bool(list(kit.iter_outcomes())),
    "competencies": lambda kit: bool(kit.framework.competencies),
    "modules": lambda kit: bool(kit.framework.modules),
    "prof_standards": lambda kit: any(c.prof_standard for c in kit.framework.competencies),
    "hours": _modules_with_hours,
    "calendar": _has_calendar,
    "final_attestation": lambda kit: kit.framework.final_attestation.hours > 0,
    "entry_requirements": lambda kit: bool((kit.profile.entry_level or "").strip()),
    "module_programs": _all_modules_have_programs,
    "assessments": lambda kit: bool(kit.content.assessments),
    "assessments:current_control": lambda kit: any(
        a.kind in ("test_question", "seminar_task", "interview_question")
        for a in kit.content.assessments
    )
    or any(t.control_form for t in kit.iter_topics()),
    "assessments:final": lambda kit: any(
        a.kind in ("final_project", "exam_task", "portfolio_item") for a in kit.content.assessments
    ),
    "sources": _has_sources,
    "literature": _has_literature,
    "methodical_materials": _has_methodical_materials,
    "normative_basis": _has_normative_basis,
    "annotation": _has_annotation,
    "document": lambda kit: bool((kit.program.document or "").strip()),
}


def _check_filled(kit: KitV1, key: str) -> bool:
    if key.startswith("template_section:"):
        code = key.split(":", 1)[1]
        return _has_template_section(kit, code)
    checker = FILL_CHECKS.get(key)
    if checker is None:  # неизвестный ключ в YAML — не считаем раздел заполненным
        return False
    return checker(kit)


@lru_cache(maxsize=4)
def load_template(kind: str) -> dict[str, Any]:
    """Прочитать yaml-шаблон разделов для вида программы (dpp_pk / dop)."""
    path = TEMPLATES_DIR / f"{kind}.yaml"
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("sections"), list):
        raise ValueError(f"Шаблон {path.name} повреждён: нужен список sections")
    return data


# ---------------------------------------------------------------------------
# V-TPL-01: обязательные разделы заполнены
# ---------------------------------------------------------------------------


def _tpl_01(ctx: "ValidationContext") -> tuple[list, dict]:
    kit = ctx.kit
    stage = resolve_stage(ctx)
    template = load_template(kit.program.kind)
    issues = []
    filled = 0
    empty: list[str] = []
    deferred: list[str] = []
    for section in template["sections"]:
        code = str(section.get("code", ""))
        title = str(section.get("title", code))
        keys = [str(k) for k in section.get("filled_by") or []]
        if stage == "framework" and any(
            k in CONTENT_CHECKS or k.startswith("template_section:") for k in keys
        ):
            deferred.append(code)
            continue
        if keys and all(_check_filled(kit, key) for key in keys):
            filled += 1
            continue
        if section.get("required", True):
            empty.append(code)
            issues.append(
                issue(
                    "V-TPL-01",
                    "error",
                    f"Раздел шаблона «{title}» не заполнен — нет данных: "
                    f"{section.get('source', 'не указан')}",
                    entity_ref=code,
                    fix_hint={"endpoint": "kit:generate", "section": code},
                )
            )
    meta = {
        "sections_total": len(template["sections"]),
        "filled": filled,
        "empty": empty,
        "deferred": deferred,
    }
    return issues, meta


# ---------------------------------------------------------------------------
# V-TPL-02: правила вида программы
# ---------------------------------------------------------------------------


def _tpl_02(kit: KitV1) -> list:
    issues = []
    if kit.program.kind == "dop":
        for competency in kit.framework.competencies:
            if competency.prof_standard is not None or competency.labor_functions:
                issues.append(
                    issue(
                        "V-TPL-02",
                        "error",
                        f"Общеразвивающая программа (ДОП) не опирается на профстандарты, а компетенция "
                        f"{competency.ref} ссылается на профстандарт или трудовые функции — уберите их",
                        entity_ref=competency.ref,
                    )
                )
    else:
        document = (kit.program.document or "").strip()
        if "удостоверение" not in document.casefold():
            shown = document or "пусто"
            issues.append(
                issue(
                    "V-TPL-02",
                    "error",
                    f"Для ДПП ПК выдаваемый документ — «удостоверение о повышении квалификации» "
                    f"(в том числе для стажировки), в программе указано: «{shown}»",
                    entity_ref=None,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# V-TPL-03: поля-заполнители пусты
# ---------------------------------------------------------------------------


def _tpl_03(kit: KitV1) -> list:
    placeholders = kit.placeholders
    issues = []
    for field_name, label in (("order_number", "номер приказа"), ("order_date", "дата приказа")):
        if str(getattr(placeholders, field_name, "") or "").strip():
            issues.append(
                issue(
                    "V-TPL-03",
                    "error",
                    f"Поле «{label}» заполнено в комплекте — реквизиты приказа заполняет человек "
                    "вне системы, выгрузка оставляет подчёркивания",
                    entity_ref="placeholders",
                )
            )
    teachers = getattr(placeholders, "teachers", None) or []
    if any(
        any(str(getattr(t, attr, "") or "").strip() for attr in ("name", "position", "degree"))
        for t in teachers
    ):
        issues.append(
            issue(
                "V-TPL-03",
                "error",
                "В списке преподавателей есть заполненные ФИО или должности — этот блок заполняется "
                "вручную после выгрузки",
                entity_ref="placeholders",
            )
        )
    signatures = getattr(placeholders, "signatures", None) or []
    if any(
        any(str(getattr(s, attr, "") or "").strip() for attr in ("name", "position"))
        for s in signatures
    ):
        issues.append(
            issue(
                "V-TPL-03",
                "error",
                "В подписях есть заполненные ФИО — подписи ставятся вручную после выгрузки",
                entity_ref="placeholders",
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Точка входа группы
# ---------------------------------------------------------------------------


def validate(ctx: "ValidationContext") -> GroupResult:
    """Все правила группы «Шаблон»."""
    tpl_issues, meta = _tpl_01(ctx)
    issues = list(tpl_issues)
    issues += _tpl_02(ctx.kit)
    issues += _tpl_03(ctx.kit)
    return GroupResult(issues=issues, meta=meta)
