"""karkas.domain.validators.sources — источники, сервисы, актуальность (Д4 §5.8).

Реализованы V-SRC-01..04, V-SVC-01 и V-ACT-01. Проверки кодов профстандартов,
трудовых функций и НПА выполняются только при переданных реестрах
(ctx.registries); если данных реестра нет — правило пропускается и его код
попадает в summary["skipped"]. Неподтверждённые источники не удаляются:
они помечаются и попадают в отчёт (ЗАД-22).
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Iterable

from karkas.domain.kit import Source
from karkas.domain.validators.base import GroupResult, issue

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import (
        LaborFunction,
        NormativeAct,
        ProfStandard,
        ServiceRecord,
        ValidationContext,
    )

_LITERATURE_SECTIONS = {"main", "additional", "internet"}
_SOFTWARE_SECTION = "software"
_STALE_LIFECYCLES = {"deprecated", "eol", "outdated"}


# ---------------------------------------------------------------------------
# V-SRC-01: НПА в реестре и действует на дату программы
# ---------------------------------------------------------------------------


def _number_pattern(number: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\d){re.escape(number)}(?!\d)", re.IGNORECASE)


def _find_act(source: Source, acts: list["NormativeAct"]) -> "NormativeAct | None":
    ref = source.normative_act_ref
    if ref:
        for act in acts:
            if getattr(act, "ref", None) == ref or act.number == ref:
                return act
    for act in acts:
        if act.number and _number_pattern(act.number).search(source.citation):
            return act
    return None


def _act_state(act: "NormativeAct", today: date) -> tuple[bool, str]:
    """(действует ли, причина) для НПА на дату программы."""
    if act.replaced_by_number:
        return False, f"заменён на №{act.replaced_by_number}"
    if act.valid_from and today < act.valid_from:
        return False, f"вступает в силу только с {act.valid_from:%d.%m.%Y}"
    if act.valid_to and today > act.valid_to:
        return False, f"утратил силу с {act.valid_to:%d.%m.%Y}"
    return True, ""


def _replacement_hint(act: "NormativeAct", acts: list["NormativeAct"]) -> str:
    if not act.replaced_by_number:
        return ""
    replacement = next((a for a in acts if a.number == act.replaced_by_number), None)
    if replacement is None:
        return f"; действующая замена — №{act.replaced_by_number}"
    return f"; действующая замена — №{replacement.number} «{replacement.title or 'без названия'}»"


def _src_01(ctx: "ValidationContext", skipped: list[str]) -> list:
    kit = ctx.kit
    acts = list(ctx.registries.normative_acts) if ctx.registries else []
    normative_sources = [s for s in kit.content.sources if s.section == "normative"]
    legal_basis = kit.program.legal_basis
    if not acts:
        if normative_sources or legal_basis:
            skipped.append("V-SRC-01")
        return []

    issues = []
    today = ctx.today
    hint = {"endpoint": "/api/v1/registry/normative-acts", "query": {"on_date": today.isoformat()}}
    for source in normative_sources:
        act = _find_act(source, acts)
        if act is None:
            issues.append(
                issue(
                    "V-SRC-01",
                    "error",
                    f"НПА «{source.citation}» не найден в реестре — уточните орган, номер и дату "
                    "акта или выберите действующий из реестра",
                    entity_ref=source.ref,
                    fix_hint=dict(hint),
                )
            )
            continue
        valid, reason = _act_state(act, today)
        if not valid:
            issues.append(
                issue(
                    "V-SRC-01",
                    "error",
                    f"НПА №{act.number} «{act.title or 'без названия'}» {reason} "
                    f"(на дату {today:%d.%m.%Y}){_replacement_hint(act, acts)} — в документе нужен "
                    "действующий акт",
                    entity_ref=source.ref,
                    fix_hint=dict(hint),
                )
            )
    for basis in legal_basis:
        number = basis.act.strip()
        act = next((a for a in acts if a.number and _number_pattern(a.number).search(number)), None)
        if act is None:
            issues.append(
                issue(
                    "V-SRC-01",
                    "error",
                    f"НПА «{basis.act}» из раздела «Программа разработана на основе» не найден в реестре",
                    entity_ref=basis.ref,
                    fix_hint=dict(hint),
                )
            )
            continue
        valid, reason = _act_state(act, today)
        if not valid:
            issues.append(
                issue(
                    "V-SRC-01",
                    "error",
                    f"НПА «{basis.act}» {reason} на дату {today:%d.%m.%Y}"
                    f"{_replacement_hint(act, acts)} — замените на действующий акт",
                    entity_ref=basis.ref,
                    fix_hint=dict(hint),
                )
            )
    return issues


# ---------------------------------------------------------------------------
# V-SRC-02/03: коды профстандартов и трудовых функций — из реестра
# ---------------------------------------------------------------------------


def _src_02_03(ctx: "ValidationContext", skipped: list[str]) -> list:
    kit = ctx.kit
    competencies = kit.framework.competencies
    issues = []
    if kit.program.kind == "dop":
        return issues  # профстандарты для ДОП запрещает V-TPL-02

    has_prof_standard = any(c.prof_standard for c in competencies)
    if not has_prof_standard:
        issues.append(
            issue(
                "V-SRC-02",
                "error",
                "Для ДПП ПК нужен хотя бы один профстандарт из реестра — подберите ПС и "
                "трудовые функции (S05)",
                fix_hint={"endpoint": "/api/v1/registry/prof-standards"},
            )
        )

    prof_standards: list["ProfStandard"] = list(ctx.registries.prof_standards) if ctx.registries else []
    labor_functions: list["LaborFunction"] = list(ctx.registries.labor_functions) if ctx.registries else []
    if not prof_standards:
        if any(c.prof_standard or c.labor_functions for c in competencies):
            skipped += ["V-SRC-02", "V-SRC-03"]
        return issues

    for competency in competencies:
        prof_standard = competency.prof_standard
        if prof_standard is not None:
            hit = next((p for p in prof_standards if p.code == prof_standard.code), None)
            if hit is None:
                issues.append(
                    issue(
                        "V-SRC-02",
                        "error",
                        f"Профстандарт {prof_standard.code} у компетенции {competency.ref} не найден "
                        "в реестре — выберите код из реестра Минтруда",
                        entity_ref=competency.ref,
                        fix_hint={"endpoint": "/api/v1/registry/prof-standards"},
                    )
                )
            elif hit.status != "active":
                issues.append(
                    issue(
                        "V-SRC-02",
                        "error",
                        f"Профстандарт {prof_standard.code} в реестре имеет статус «{hit.status}» — "
                        "выберите действующий профстандарт",
                        entity_ref=competency.ref,
                        fix_hint={"endpoint": "/api/v1/registry/prof-standards"},
                    )
                )
        for lf in competency.labor_functions:
            if prof_standard is None:
                issues.append(
                    issue(
                        "V-SRC-03",
                        "error",
                        f"У компетенции {competency.ref} указана трудовая функция {lf.code}, но нет "
                        "профстандарта — сначала выберите профстандарт",
                        entity_ref=competency.ref,
                    )
                )
                continue
            hit = next(
                (
                    item
                    for item in labor_functions
                    if item.code == lf.code and item.prof_standard_code == prof_standard.code
                ),
                None,
            )
            if hit is None:
                issues.append(
                    issue(
                        "V-SRC-03",
                        "error",
                        f"Трудовая функция {lf.code} не найдена в реестре для профстандарта "
                        f"{prof_standard.code} — код ТФ берётся только из реестра",
                        entity_ref=competency.ref,
                        fix_hint={
                            "endpoint": (
                                f"/api/v1/registry/prof-standards/{prof_standard.code}/labor-functions"
                            )
                        },
                    )
                )
    return issues


# ---------------------------------------------------------------------------
# V-SRC-04: литература подтверждена или явно помечена
# ---------------------------------------------------------------------------


def _src_04(ctx: "ValidationContext", skipped: list[str]) -> list:
    literature = [s for s in ctx.kit.content.sources if s.section in _LITERATURE_SECTIONS]
    if not literature:
        skipped.append("V-SRC-04")
        return []
    issues = []
    for source in literature:
        if source.status == "verified" and not source.evidence:
            issues.append(
                issue(
                    "V-SRC-04",
                    "error",
                    f"Источник «{source.citation}» помечен как проверенный, но подтверждений нет — "
                    "снимите статус или добавьте evidence",
                    entity_ref=source.ref,
                )
            )
        elif source.status == "partially_verified":
            issues.append(
                issue(
                    "V-SRC-04",
                    "info",
                    f"Источник «{source.citation}»: ISBN проверен по контрольной сумме — уточните издание вручную",
                    entity_ref=source.ref,
                )
            )
        elif source.status == "unverified":
            issues.append(
                issue(
                    "V-SRC-04",
                    "warning",
                    f"Источник «{source.citation}» не подтверждён — проверьте вручную (в документе будет "
                    "пометка «не подтверждено»)",
                    entity_ref=source.ref,
                )
            )
        elif source.status == "not_found":
            issues.append(
                issue(
                    "V-SRC-04",
                    "error",
                    f"Источник «{source.citation}» не найден — удалите или замените; выгрузка пометит его "
                    "как «не найдено»",
                    entity_ref=source.ref,
                )
            )
        elif source.status == "outdated":
            issues.append(
                issue(
                    "V-SRC-04",
                    "warning",
                    f"Источник «{source.citation}» устарел — проверьте актуальность издания",
                    entity_ref=source.ref,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# V-SVC-01 и V-ACT-01: сервисы из реестра service_catalog
# ---------------------------------------------------------------------------


def _match_service(citation: str, services: Iterable["ServiceRecord"]) -> "ServiceRecord | None":
    lowered = citation.casefold()
    hits = [s for s in services if s.name and s.name.casefold() in lowered]
    if not hits:
        return None
    return max(hits, key=lambda s: len(s.name))


def _svc_01(ctx: "ValidationContext", skipped: list[str]) -> list:
    software = [s for s in ctx.kit.content.sources if s.section == _SOFTWARE_SECTION]
    services = list(ctx.registries.services) if ctx.registries else []
    if not software:
        skipped.append("V-SVC-01")
        return []
    if not services:
        skipped.append("V-SVC-01")
        return []
    issues = []
    for source in software:
        service = _match_service(source.citation, services)
        if service is None:
            issues.append(
                issue(
                    "V-SVC-01",
                    "warning",
                    f"Упоминание «{source.citation}» отсутствует в каталоге сервисов — проверьте, доступен "
                    "ли инструмент в России и дайте ссылку",
                    entity_ref=source.ref,
                )
            )
        elif service.available_ru is False:
            issues.append(
                issue(
                    "V-SVC-01",
                    "error",
                    f"Сервис «{service.name}» недоступен в России — замените его на доступный аналог",
                    entity_ref=source.ref,
                )
            )
        elif service.available_ru is None:
            issues.append(
                issue(
                    "V-SVC-01",
                    "info",
                    f"Доступность «{service.name}» в России не подтверждена — проверьте вручную",
                    entity_ref=source.ref,
                )
            )
    return issues


def _act_01(ctx: "ValidationContext", skipped: list[str]) -> list:
    software = [s for s in ctx.kit.content.sources if s.section == _SOFTWARE_SECTION]
    services = list(ctx.registries.services) if ctx.registries else []
    if not software or not services:
        skipped.append("V-ACT-01")
        return []
    issues = []
    for source in software:
        service = _match_service(source.citation, services)
        if service is not None and service.lifecycle in _STALE_LIFECYCLES:
            version = f" (актуальная версия: {service.latest_version})" if service.latest_version else ""
            issues.append(
                issue(
                    "V-ACT-01",
                    "warning",
                    f"«{service.name}»: жизненный цикл «{service.lifecycle}»{version} — обновите инструмент "
                    "или версию в материалах",
                    entity_ref=source.ref,
                )
            )
    return issues


# ---------------------------------------------------------------------------
# Точка входа группы
# ---------------------------------------------------------------------------


def validate(ctx: "ValidationContext") -> GroupResult:
    """Все правила группы «Источники» и «Ограничения»."""
    issues = []
    skipped: list[str] = []
    issues += _src_01(ctx, skipped)
    issues += _src_02_03(ctx, skipped)
    issues += _src_04(ctx, skipped)
    svc_issues = _svc_01(ctx, skipped)
    act_issues = _act_01(ctx, skipped)
    issues += svc_issues
    issues += act_issues

    counts: dict[str, int] = {}
    for source in ctx.kit.content.sources:
        counts[source.status] = counts.get(source.status, 0) + 1
    software_checked = sum(1 for s in ctx.kit.content.sources if s.section == _SOFTWARE_SECTION)
    meta = {
        "verified": counts.get("verified", 0),
        "unverified": counts.get("unverified", 0),
        "not_found": counts.get("not_found", 0),
        "outdated": counts.get("outdated", 0),
        "services": {
            "ok": not any(i.severity == "error" for i in svc_issues + act_issues),
            "checked": software_checked,
        },
    }
    return GroupResult(issues=issues, skipped=skipped, meta=meta)
