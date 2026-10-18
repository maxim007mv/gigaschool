"""karkas.domain.validators — самопроверка комплекта (S10/S19, Д4 §5.8).

`run_validation(ctx)` прогоняет все правила V-* по KitV1 и возвращает Report:
issues (rule_code, severity, entity_ref, сообщение по-русски, fix_hint),
summary по группам, sample_findings и gaps. Правила, для которых нет
исходных данных (реестры, reference_texts, embeddings, declared_totals,
календарь), не падают: они пропускаются, а их коды попадают в
`summary["skipped"]`.

Группы правил лежат в соседних модулях: hours (V-HRS-01..09, V-CAL-01),
coverage (V-COV-01..04, V-SEQ-01, V-DUP-01), sources (V-SRC-01..04, V-SVC-01,
V-ACT-01), template (V-TPL-01..03), language (V-LNG-01), plagiarism (V-PLG-01),
realism (V-REA-01), request (V-REQ-01), sample (V-SMP-01), acr_export (V-ACR-01 — структура .docx по эталонам АЦР).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from karkas.domain.kit import KitV1, Report, ReportIssue


@dataclass
class NormativeAct:
    """Запись реестра НПА (Д2 §5.3)."""

    issuer: str
    number: str
    signed_on: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    replaced_by_number: str | None = None
    kind: str = "order"
    title: str = ""
    applies_to: tuple[str, ...] = ()
    ref: str | None = None


@dataclass
class ProfStandard:
    """Запись реестра профстандартов."""

    code: str
    title: str = ""
    status: str = "active"


@dataclass
class LaborFunction:
    """Трудовая функция профстандарта (только из реестра)."""

    prof_standard_code: str
    code: str
    title: str = ""


@dataclass
class ServiceRecord:
    """Запись каталога сервисов и ПО (доступность в РФ, жизненный цикл)."""

    name: str
    available_ru: bool | None = None
    lifecycle: str = "current"
    latest_version: str | None = None


@dataclass
class RegistryBundle:
    """Реестры, переданные в валидаторы (из БД; могут отсутствовать)."""

    normative_acts: list[NormativeAct] = field(default_factory=list)
    prof_standards: list[ProfStandard] = field(default_factory=list)
    labor_functions: list[LaborFunction] = field(default_factory=list)
    services: list[ServiceRecord] = field(default_factory=list)


@dataclass
class ValidationContext:
    """Вход самопроверки: комплект, реестры и необязательные данные."""

    kit: KitV1
    registries: RegistryBundle | None = None
    reference_texts: list[str] = field(default_factory=list)
    declared_totals: dict[str, Any] | None = None  # для V-SMP-01 (образец)
    today: date = field(default_factory=date.today)
    embeddings: dict[str, list[float]] | None = None  # ref → вектор (V-DUP-01)
    # "auto": каркас проверяется, если в комплекте нет содержания (S10/S19)
    stage: Literal["auto", "framework", "kit"] = "auto"


def run_validation(ctx: ValidationContext) -> Report:
    """Полный прогон правил V-*; возвращает отчёт (S10 для каркаса, S19 для комплекта)."""
    from karkas.domain.validators import (
        acr_export,
        coverage,
        hours,
        language,
        plagiarism,
        realism,
        request,
        sample,
        sources,
        template,
    )
    from karkas.domain.validators.base import GroupResult, resolve_stage

    started = time.perf_counter()
    groups: dict[str, GroupResult] = {}
    issues: list[ReportIssue] = []
    skipped: list[str] = []
    for name, module in (
        ("hours", hours),
        ("coverage", coverage),
        ("sources", sources),
        ("template", template),
        ("language", language),
        ("plagiarism", plagiarism),
        ("realism", realism),
        ("request", request),
        ("sample", sample),
        ("acr_export", acr_export),
    ):
        result = module.validate(ctx)
        groups[name] = result
        issues.extend(result.issues)
        skipped.extend(result.skipped)

    summary: dict[str, Any] = {}
    for name, result in groups.items():
        entry: dict[str, Any] = {"ok": result.ok}
        entry.update(result.meta)
        summary[name] = entry
    # Дубли и сервисы — самостоятельные срезы отчёта (разрешены Д4 §5.8).
    for group_name, key in (("coverage", "duplicates"), ("sources", "services")):
        sub = groups[group_name].meta.get(key)
        if isinstance(sub, dict):
            summary[key] = sub

    summary["skipped"] = list(dict.fromkeys(skipped))
    summary["stage"] = resolve_stage(ctx)

    passed = not any(i.severity == "error" for i in issues)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return Report(
        passed=passed,
        duration_ms=duration_ms,
        summary=summary,
        issues=issues,
        gaps=list(ctx.kit.framework.gaps),
        sample_findings=[i.message for i in issues if i.rule_code == "V-SMP-01"],
        assumptions=[a.text for a in ctx.kit.assumptions],
    )
