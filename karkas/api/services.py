"""karkas.api.services — сервисные операции API поверх домена и репозиториев.

Слой api тонкий: здесь только оркестрация (загрузка реестров, прогон валидаторов,
сборка входов солвера, сохранение отчёта). Бизнес-логика — в karkas.domain.*.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.domain.hours import Constraints, ModuleIn, Plan, TopicIn
from karkas.domain.verified_registry import merge_registry_bundle_prof_standards
from karkas.domain.kit import ACTIVITIES, KitV1, Report
from karkas.domain.validators import (
    LaborFunction,
    NormativeAct,
    ProfStandard,
    RegistryBundle,
    ServiceRecord,
    ValidationContext,
    run_validation,
)
from karkas.settings import settings

HOURS_RULES = {"V-HRS-01", "V-HRS-02", "V-HRS-03", "V-HRS-04", "V-HRS-05", "V-HRS-06", "V-HRS-07", "V-HRS-08", "V-HRS-09"}


async def build_registries(session: AsyncSession) -> RegistryBundle:
    """Загрузить реестры из БД для валидаторов (НПА, профстандарты, ТФ, сервисы)."""
    act_rows = (
        await session.execute(
            text(
                """
                SELECT issuer, number, signed_on, valid_from, valid_to, kind
                FROM normative_act
                """
            )
        )
    ).mappings().all()
    ps_rows = (
        await session.execute(text("SELECT code, title, status FROM prof_standard"))
    ).mappings().all()
    lf_rows = (
        await session.execute(
            text(
                """
                SELECT ps.code AS ps_code, lf.code AS lf_code, lf.title AS lf_title
                FROM labor_function lf JOIN prof_standard ps ON ps.id = lf.prof_standard_id
                """
            )
        )
    ).mappings().all()
    svc_rows = (
        await session.execute(
            text("SELECT name, available_ru, lifecycle, latest_version FROM service_catalog")
        )
    ).mappings().all()
    prof_standards = merge_registry_bundle_prof_standards(
        [ProfStandard(code=r["code"], title=r["title"] or "", status=r["status"]) for r in ps_rows]
    )
    labor_functions = [
        LaborFunction(prof_standard_code=r["ps_code"], code=r["lf_code"], title=r["lf_title"] or "")
        for r in lf_rows
    ]
    known = {(lf.prof_standard_code, lf.code) for lf in labor_functions}
    from karkas.domain.verified_registry import VERIFIED_JSON, load_file_verified

    load_file_verified()
    raw: dict[str, Any] = {}
    if VERIFIED_JSON.is_file():
        try:
            raw = json.loads(VERIFIED_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
    for item in raw.get("labor_functions") or []:
        key = (str(item.get("prof_standard_code") or "").strip(), str(item.get("code") or "").strip())
        if key[0] and key[1] and key not in known:
            labor_functions.append(
                LaborFunction(prof_standard_code=key[0], code=key[1], title=str(item.get("title") or ""))
            )
            known.add(key)
    return RegistryBundle(
        normative_acts=[
            NormativeAct(
                issuer=r["issuer"], number=r["number"], signed_on=r["signed_on"],
                valid_from=r["valid_from"], valid_to=r["valid_to"], kind=r["kind"],
            )
            for r in act_rows
        ],
        prof_standards=prof_standards,
        labor_functions=labor_functions,
        services=[
            ServiceRecord(
                name=r["name"], available_ru=r["available_ru"], lifecycle=r["lifecycle"],
                latest_version=r["latest_version"],
            )
            for r in svc_rows
        ],
    )


def _add_hours_fix_hints(report: Report) -> None:
    """Для нарушений часов подсказать вызываемый ремонт (framework:rebalance)."""
    for issue in report.issues:
        if issue.rule_code in HOURS_RULES and issue.fix_hint is None and issue.entity_ref:
            issue.fix_hint = {
                "endpoint": "framework:rebalance",
                "body": {"scope": issue.entity_ref, "keep_locked": True},
            }


async def run_full_validation(
    session: AsyncSession,
    *,
    kit: KitV1,
    scope: str = "framework",
    reference_texts: list[str] | None = None,
    declared_totals: dict[str, Any] | None = None,
    today: date | None = None,
) -> Report:
    """Прогнать все правила V-* по KitV1 с реестрами из БД."""
    registries = await build_registries(session)
    stage = "framework" if scope == "framework" else ("kit" if scope == "kit" else "auto")
    ctx = ValidationContext(
        kit=kit,
        registries=registries,
        reference_texts=reference_texts or [],
        declared_totals=declared_totals,
        today=today or date.today(),
        stage=stage,
    )
    report = run_validation(ctx)
    report.summary.setdefault("scope", scope)
    _add_hours_fix_hints(report)
    return report


def checks_payload(report: Report) -> dict[str, Any]:
    """Формат checks для Ответов API (framework, kit:generate)."""
    return {
        "passed": report.passed,
        "issues": [issue.model_dump(mode="json") for issue in report.issues],
        "summary": report.summary,
        "duration_ms": report.duration_ms,
    }


def kit_to_module_inputs(kit: KitV1) -> tuple[list[ModuleIn], Constraints]:
    """KitV1 → вход солвера часов (веса, практичность, ограничения)."""
    modules = [
        ModuleIn(
            ref=module.ref,
            weight=module.weight,
            topics=[
                TopicIn(
                    ref=topic.ref,
                    weight=topic.weight,
                    practicality=topic.practicality,
                    has_lab=topic.workload.lab > 0,
                )
                for topic in module.topics
            ],
        )
        for module in kit.framework.modules
    ]
    c = kit.profile.constraints
    constraints = Constraints(
        total=kit.program.total_hours,
        final_att=kit.program.final_attestation.hours,
        unit=c.unit_hours,
        self_study_only=c.self_study_only,
        min_practice_share=c.min_practice_share_pct / 100.0,
        self_study_share=c.self_study_share_pct / 100.0,
        distance_share=c.distance_share_pct / 100.0,
    )
    return modules, constraints


def locked_cells_from_kit(kit: KitV1) -> dict[str, dict[str, int]]:
    """Разобрать topic.locked («practice:in_person») в {T-ref: {activity: hours}}."""
    locked: dict[str, dict[str, int]] = {}
    for topic in kit.iter_topics():
        for tag in topic.locked:
            activity = tag.split(":", 1)[0]
            if activity not in ACTIVITIES:
                continue
            locked.setdefault(topic.ref, {})[activity] = topic.workload.by_activity(activity)
    return locked


def apply_plan_to_kit(kit: KitV1, plan: Plan) -> list[dict[str, Any]]:
    """Разложить план солвера обратно в Topic.workload; вернуть список изменений."""
    changed: list[dict[str, Any]] = []
    for topic in kit.iter_topics():
        row = plan.rows.get(topic.ref)
        if row is None:
            continue
        for activity in ACTIVITIES:
            old = topic.workload.by_activity(activity)
            new = int(row.get(activity, 0))
            if old != new:
                setattr(topic.workload, activity, new)
                changed.append({"ref": topic.ref, "field": activity, "from": old, "to": new})
        old_distance = topic.workload.distance
        new_distance = int(plan.distance.get(topic.ref, 0))
        if old_distance != new_distance:
            topic.workload.distance = new_distance
            changed.append({"ref": topic.ref, "field": "distance", "from": old_distance, "to": new_distance})
    return changed
