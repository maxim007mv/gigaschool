"""karkas.agent.pipeline — оркестрация конвейера S01–S23 (Д1 §6, Д4 §4–5, §9).

Слой между очередью/HTTP и навыками:

- собирает входы из БД (бриф, файлы, ответы, реестры, каркас);
- исполняет навыки через ``SkillRunner`` (зависимости, параллелизм, чекпоинты);
- сохраняет результаты в нормализованные таблицы, пишет снимки версий и отчёты;
- публикует события SSE и формирует артефакты выгрузки.

Один шаг = один навык; LLM пишет тексты, структура и арифметика — доменный код.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.agent.skill_runner import SkillRunner
from karkas.agent.skills import SKILLS, SkillContext
from karkas.agent.skills._base import InMemoryCheckpointStore
from karkas.api.sse import bus
from karkas.domain.intake_slots import detect_hour_total_conflicts
from karkas.domain.verified_registry import (
    annotate_registries_dict,
    apply_source_verification_flags,
    merge_file_prof_standards,
    verification_assumptions_for_competencies,
)
from karkas.settings import settings
from karkas.domain.kit import (
    ACTIVITIES,
    AnswerKey,
    Assessment,
    AssessmentOption,
    Calendar,
    CalendarSession,
    Competency,
    Content,
    ContentBlock,
    Criterion,
    FinalAttestation,
    Framework,
    KitV1,
    LaborFunctionRef,
    Module,
    Outcome,
    ProfStandardRef,
    ProgramConstraints,
    ProgramHeader,
    ProgramProfile,
    Report,
    Source,
    Topic,
    Workload,
)
from karkas.domain.intake_slots import parse_total_hours as _parse_hours
from karkas.infra import ingest, storage
from karkas.infra.db import get_session_factory
from karkas.infra.repos import framework as framework_repo
from karkas.infra.repos import programs as programs_repo
from karkas.infra.repos import usage as usage_repo
from karkas.logging_setup import get_logger
from karkas.settings import settings

logger = get_logger("karkas.pipeline")

ProgressFn = Callable[[dict[str, Any]], Awaitable[None]]
ProgressCallback = Callable[[str, int, int, str], None] | None

DEFAULT_FINAL_FORM = "Итоговая аттестация"

ARTIFACT_KIND_MAP: dict[str, tuple[str, str]] = {
    # формат S20 → (artifact_kind, расширение файла)
    "docx": ("program_docx", "docx"),
    "pptx": ("slides_pptx", "pptx"),
    "gift": ("tests_gift", "gift.txt"),
    "moodle_xml": ("tests_moodle_xml", "xml"),
    "csv": ("tests_csv", "csv"),
    "json": ("kit_json", "json"),
    "report": ("report_docx", "docx"),
}

CONTENT_TYPES = {
    "program_docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "report_docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "slides_pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "tests_gift": "text/plain; charset=utf-8",
    "tests_moodle_xml": "application/xml; charset=utf-8",
    "tests_csv": "text/csv; charset=utf-8",
    "kit_json": "application/json; charset=utf-8",
}


# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------


def _estimate_cost_rub(model: str, prompt_tokens: int, completion_tokens: int) -> "Decimal":
    """Стоимость вызова по тарифной таблице организации (organization.settings.tariffs
    на пилоте; в конфигурации — TARIFFS_JSON: {"<model>": {"in": руб/1M, "out": руб/1M}})."""
    import json as json_module
    from decimal import Decimal

    try:
        tariffs = json_module.loads(settings.tariffs_json or "{}")
    except ValueError:
        return Decimal("0")
    row = tariffs.get(model) if isinstance(tariffs, dict) else None
    if not isinstance(row, dict):
        return Decimal("0")
    price_in = Decimal(str(row.get("in", 0) or 0))
    price_out = Decimal(str(row.get("out", 0) or 0))
    million = Decimal(1_000_000)
    return (Decimal(prompt_tokens) * price_in + Decimal(completion_tokens) * price_out) / million


class PgMeter:
    """MeterProtocol: каждый вызов модели пишется в llm_call (токены, задержка, стоимость).

    Без этого учёта экран «Эффект» и расчёт стоимости на защите пусты (Д1 §7/§14).
    """

    def __init__(self, *, org_id: str, program_id: str | None = None, job_id: str | None = None) -> None:
        self.org_id = org_id
        self.program_id = program_id
        self.job_id = job_id

    async def record(
        self,
        skill: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        ok: bool,
        cache_hit: bool,
    ) -> None:
        from karkas.infra.repos import usage as usage_repo

        factory = get_session_factory()
        try:
            async with factory() as session:
                await usage_repo.record_llm_call(
                    session,
                    org_id=self.org_id,
                    skill=skill,
                    model=model,
                    prompt_tokens=int(prompt_tokens),
                    completion_tokens=int(completion_tokens),
                    latency_ms=int(latency_ms),
                    ok=bool(ok),
                    program_id=self.program_id,
                    job_id=self.job_id,
                    cost_rub=_estimate_cost_rub(model, int(prompt_tokens), int(completion_tokens)),
                    cache_hit=bool(cache_hit),
                )
                await session.commit()
        except Exception:  # учёт не должен ломать генерацию
            logger.warning("llm.meter_failed", skill=skill, model=model)


class PgCache:
    """CacheProtocol поверх llm_cache: ответы моделей переживают рестарт процесса (TTL 7 суток)."""

    @staticmethod
    def _digest(key: str) -> bytes:
        import hashlib

        return hashlib.sha256(key.encode("utf-8")).digest()

    async def get(self, key: str) -> dict[str, Any] | None:
        from karkas.infra.repos import usage as usage_repo

        factory = get_session_factory()
        try:
            async with factory() as session:
                value = await usage_repo.cache_get(session, self._digest(key))
                await session.commit()
                return value
        except Exception:
            return None

    async def put(self, key: str, value: dict[str, Any], ttl_s: float | None = None) -> None:
        from karkas.infra.repos import usage as usage_repo

        ttl_hours = settings.llm_cache_ttl_h if ttl_s is None else max(1, int(ttl_s / 3600))
        factory = get_session_factory()
        try:
            async with factory() as session:
                await usage_repo.cache_put(
                    session, key=self._digest(key), model="cache", response=value, ttl_hours=ttl_hours
                )
                await session.commit()
        except Exception:
            logger.warning("llm.cache_put_failed")


def make_gateway(program_id: str | None = None, org_id: str | None = None) -> Any:
    """LLM-шлюз Cloud.ru FM (ленивый импорт: без ключа пайплайн не падает на импорте).

    При известной организации подключаются БД-учёт вызовов (PgMeter) и кэш (PgCache);
    резервные модели берутся из конфигурации (Д1 §7/§14).
    """
    from karkas.agent.llm_gateway import LlmGateway

    backup_models: dict[str, str] = {}
    if settings.model_struct_backup:
        backup_models["struct"] = settings.model_struct_backup
    if settings.model_bulk_backup:
        backup_models["bulk"] = settings.model_bulk_backup

    kwargs: dict[str, Any] = {}
    if backup_models:
        kwargs["backup_models"] = backup_models
    if org_id:
        kwargs["meter"] = PgMeter(org_id=org_id, program_id=program_id)
        kwargs["cache"] = PgCache()
    return LlmGateway(**kwargs)


def make_runner() -> SkillRunner:
    return SkillRunner(skills=SKILLS.values())


async def _seeded_context(
    program_id: str,
    scope: str,
    seeds: dict[str, dict[str, Any]] | None,
    *,
    gateway: Any,
    extra: dict[str, Any] | None = None,
) -> SkillContext:
    """Контекст с уникальным префиксом чекпоинтов и предзаполненными зависимостями.

    Префикс обязан включать program_id и версию задачи (контракт SkillRunner),
    иначе повторный прогон переиспользует чужие результаты.
    """
    prefix = f"{program_id}:{scope}:"
    ctx = SkillContext(
        gateway=gateway,
        checkpoint=InMemoryCheckpointStore(),
        extra={"program_id": program_id, "checkpoint_prefix": prefix, **(extra or {})},
    )
    for code, output in (seeds or {}).items():
        await ctx.checkpoint.save(f"{prefix}{code}", output)
    return ctx


def _topic_outcomes(outcomes_json: list[dict[str, Any]], outcome_refs: list[str]) -> list[dict[str, Any]]:
    """РО, относящиеся к теме, — их одних передаём в промпт (экономия токенов).

    Полный список повторялся бы в каждом вызове S12/S13/S14/S15. Если у темы нет
    привязки к РО — отдаём полный список (безопасный откат).
    """
    refs = set(outcome_refs)
    selected = [outcome for outcome in outcomes_json if outcome.get("ref") in refs]
    return selected or list(outcomes_json)


def _progress_adapter(on_progress: ProgressFn | None) -> ProgressCallback:
    if on_progress is None:
        return None

    def callback(code: str, done: int, total: int, label: str) -> None:
        task = asyncio.ensure_future(
            on_progress({"step": code, "done": done, "total": total, "label": label})
        )
        task.add_done_callback(lambda t: t.cancelled() or t.exception())

    return callback


async def _publish(program_id: str | None, event: str, data: dict[str, Any]) -> None:
    await bus.publish(program_id, event, data)


async def _load_program(session: AsyncSession, program_id: str) -> dict[str, Any]:
    program = await programs_repo.get_program(session, program_id)
    if program is None:
        raise ValueError(f"Программа {program_id} не найдена")
    return program


async def _brief_of(program: dict[str, Any]) -> str:
    return str((program.get("profile") or {}).get("brief") or "").strip()


async def _files_context(session: AsyncSession, program_id: str) -> tuple[str, list[dict[str, Any]]]:
    """Общий текст приложенных файлов и список референсов для S04."""
    rows = (
        await session.execute(
            text(
                """
                SELECT pf.role, fo.filename, fo.extracted_text, fo.extract_meta
                FROM program_file pf JOIN file_object fo ON fo.id = pf.file_id
                WHERE pf.program_id = CAST(:pid AS uuid)
                ORDER BY fo.filename
                """
            ),
            {"pid": program_id},
        )
    ).mappings().all()
    references: list[dict[str, Any]] = []
    parts: list[str] = []
    for row in rows:
        text_value = (row["extracted_text"] or "")[:40_000]
        references.append(
            {
                "role": row["role"],
                "name": row["filename"],  # S04 читает "name" — не теряем имя образца
                "filename": row["filename"],
                "text": text_value,
                "meta": row["extract_meta"] or {},
            }
        )
        if text_value:
            parts.append(f"[{row['filename']}]\n{text_value}")
    return "\n\n".join(parts), references


async def _answers_by_slot(session: AsyncSession, program_id: str) -> dict[str, str]:
    """Ответы на слоты: явные ответы вопросов + зафиксированные допущения (slot_defaults)."""
    rows = (
        await session.execute(
            text(
                """
                SELECT slot, answer FROM clarification
                WHERE program_id = CAST(:pid AS uuid) AND answer IS NOT NULL
                """
            ),
            {"pid": program_id},
        )
    ).mappings().all()
    profile = (
        await session.execute(
            text("SELECT profile FROM program WHERE id = CAST(:pid AS uuid)"), {"pid": program_id}
        )
    ).scalar_one_or_none()
    defaults = dict((profile or {}).get("slot_defaults") or {})
    answers = {row["slot"]: str(row["answer"]) for row in rows}
    return {**defaults, **answers}


async def _registries_for_inputs(session: AsyncSession) -> dict[str, Any]:
    """Реестры в виде словаря для адаптера registry_bundle и S05-кандидатов."""
    acts = (
        await session.execute(
            text(
                """
                SELECT issuer, number, signed_on, valid_from, valid_to, kind, title
                FROM normative_act
                """
            )
        )
    ).mappings().all()
    ps_rows = (
        await session.execute(text("SELECT code, title, status, order_number FROM prof_standard"))
    ).mappings().all()
    lf_rows = (
        await session.execute(
            text(
                """
                SELECT ps.code AS ps_code, lf.code AS lf_code, lf.title AS lf_title, lf.otf_code
                FROM labor_function lf JOIN prof_standard ps ON ps.id = lf.prof_standard_id
                ORDER BY lf.code
                """
            )
        )
    ).mappings().all()
    services = (
        await session.execute(
            text("SELECT name, available_ru, lifecycle, latest_version FROM service_catalog")
        )
    ).mappings().all()

    lf_by_ps: dict[str, list[dict[str, Any]]] = {}
    for row in lf_rows:
        lf_by_ps.setdefault(row["ps_code"], []).append(
            {"code": row["lf_code"], "title": row["lf_title"] or "", "otf_code": row["otf_code"]}
        )
    payload: dict[str, Any] = {
        "normative_acts": [
            {
                "issuer": r["issuer"],
                "number": r["number"],
                "signed_on": r["signed_on"].isoformat() if r["signed_on"] else None,
                "valid_from": r["valid_from"].isoformat() if r["valid_from"] else None,
                "valid_to": r["valid_to"].isoformat() if r["valid_to"] else None,
                "kind": r["kind"],
                "title": r["title"],
            }
            for r in acts
        ],
        "prof_standards": [
            {
                "code": r["code"],
                "title": r["title"],
                "status": r["status"],
                "order_number": r["order_number"],
                "labor_functions": lf_by_ps.get(r["code"], []),
            }
            for r in ps_rows
        ],
        "labor_functions": [
            {"prof_standard_code": r["ps_code"], "code": r["lf_code"], "title": r["lf_title"] or ""}
            for r in lf_rows
        ],
        "services": [
            {
                "name": r["name"],
                "available_ru": r["available_ru"],
                "lifecycle": r["lifecycle"],
                "latest_version": r["latest_version"],
            }
            for r in services
        ],
    }
    payload["prof_standards"] = merge_file_prof_standards(payload["prof_standards"])
    return annotate_registries_dict(payload)


def _map_form(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower().replace("ё", "е")
    if "стажиров" in lowered:
        return "internship"
    if "дистанц" in lowered or "дот" in lowered:
        return "distance"
    if "очно-заоч" in lowered or "заоч" in lowered:
        return "part_time"
    if "очн" in lowered:
        return "full_time"
    return None


def _document_for(kind: str) -> str:
    if kind == "dpp_pk":
        return "удостоверение о повышении квалификации"
    return "сертификат об обучении"


def guess_title(brief: str) -> str:
    """Название программы из брифа (первая содержательная строка ≤ 120 символов)."""
    for line in brief.splitlines():
        cleaned = line.strip().strip("«»\"'.")
        if len(cleaned) >= 8:
            return cleaned[:120]
    return "Новая программа"


def _sample_declared_totals_from_errors(errors: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Итоги образца из S04 (для V-SMP-01), без копирования в каркас."""
    if not errors:
        return None
    declared: dict[str, Any] = {}
    for item in errors:
        kind = str(item.get("kind") or "")
        if kind != "hours_mismatch":
            continue
        evidence = str(item.get("evidence") or item.get("description") or "")
        for key, label in (("self_study", "срс"), ("total", "всего"), ("content_total", "раздел")):
            if label in evidence.lower():
                nums = [int(n) for n in re.findall(r"\d{2,3}", evidence)]
                if nums:
                    declared[key] = nums[0]
    return declared or None


def _constraints_dict(program: dict[str, Any], answers: dict[str, str]) -> dict[str, Any]:
    constraints = dict(program.get("constraints") or {})
    total = program.get("total_hours") or _parse_hours(answers.get("total_hours"))
    if not total:
        raise ValueError("CLARIFICATION_REQUIRED: не задан объём программы в часах")
    final_att = int(program.get("final_att_hours") or 2)
    form = program.get("form") or _map_form(answers.get("form"))
    self_study_only = bool(constraints.get("self_study_only", False))
    max_hpd = int(constraints.get("max_hours_per_day") or 8)
    if form == "internship":
        self_study_only = True
        max_hpd = min(max_hpd, 4)
    return {
        "total": int(total),
        "final_att": final_att,
        "unit": int(constraints.get("unit_hours") or 1),
        "self_study_only": self_study_only,
        "min_practice_share_pct": float(constraints.get("min_practice_share_pct") or 0),
        "self_study_share_pct": float(constraints.get("self_study_share_pct") or 0),
        "distance_share_pct": float(constraints.get("distance_share_pct") or 0),
        "max_hours_per_day": max_hpd,
        "days_per_week": int(constraints.get("days_per_week") or 5),
    }


# ---------------------------------------------------------------------------
# Ядро: разбор брифа (S01–S03)
# ---------------------------------------------------------------------------


async def intake_core(
    session: AsyncSession,
    program_id: str,
    *,
    brief: str | None = None,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """S01–S03: профиль, шаблон, уточняющие вопросы. Обновляет программу и вопросы."""
    program = await _load_program(session, program_id)
    brief_text = (brief or await _brief_of(program)).strip()
    if not brief_text:
        raise ValueError("intake: пустой бриф")
    files_text, references = await _files_context(session, program_id)

    gateway = gateway or make_gateway(program_id, str(program["org_id"]))
    runner = make_runner()
    ctx = await _seeded_context(program_id, "intake", {}, gateway=gateway)

    # Ответы пользователя (уже данные ранее) — вход S01/S03: агент не спрашивает
    # повторно и учитывает их в профиле. missing_slots фильтруются по ответам.
    answers = await _answers_by_slot(session, program_id)
    inputs: dict[str, Any] = {
        "brief": brief_text,
        "files_text": files_text,
        "references": references,
        "answers": answers,
    }

    s01 = (await runner.run("S01", inputs, ctx, progress_cb)).output
    missing_slots = [slot for slot in (s01.get("missing_slots") or []) if slot not in answers]
    inputs = {**inputs, "missing_slots": missing_slots}
    s02 = (await runner.run("S02", inputs, ctx, progress_cb)).output
    if missing_slots:
        s03 = (await runner.run("S03", inputs, ctx, progress_cb)).output
    else:
        # Все недостающие слоты уже отвечены — повторно НЕ спрашиваем
        # (иначе S03 с пустым missing вернёт вопросы по всем обязательным слотам).
        s03 = {"questions": [], "assumptions": []}
        await ctx.checkpoint.save(f"{ctx.extra['checkpoint_prefix']}S03", s03)

    profile_json = dict(program.get("profile") or {})
    s01_profile = s01.get("profile") or {}
    profile_json.update(
        {
            "audience": s01_profile.get("audience") or profile_json.get("audience"),
            "entry_level": s01_profile.get("entry_level") or profile_json.get("entry_level"),
            "schedule": s01_profile.get("schedule") or profile_json.get("schedule"),
            "duration_hint": s01_profile.get("duration_hint") or profile_json.get("duration_hint"),
            "notes": s01_profile.get("notes") or profile_json.get("notes"),
            "glossary": s01_profile.get("glossary") or profile_json.get("glossary") or {},
            "gaps": s01.get("gaps") or profile_json.get("gaps") or [],
            "assumptions": [
                *(profile_json.get("assumptions") or []),
                *(a.get("text") for a in (s01.get("assumptions") or []) if a.get("text")),
                *detect_hour_total_conflicts(brief_text),
                *(a.get("text") for a in (s03.get("assumptions") or []) if a.get("text")),
            ],
        }
    )
    constraints = dict(s01_profile.get("constraints") or {})
    total_hours = _parse_hours(answers.get("total_hours"))
    # Ответ пользователя на слот kind важнее правил S02: «повышение квалификации»
    # из ответа должен давать dpp_pk, а не дефолт dop (иначе неверный шаблон и документ).
    kind = _kind_from_answer(answers.get("kind")) or s02.get("kind") or program.get("kind")
    form = _map_form(answers.get("form")) or program.get("form")

    fields: dict[str, Any] = {"profile": profile_json}
    # Ограничения из S01 объединяем с уже сохранёнными (не затираем допущения).
    # unit_hours задаёт только методист (API/UI): S01 его не выводит и не перезаписывает.
    s01_constraints = {k: v for k, v in constraints.items() if k != "unit_hours"}
    merged_constraints = {**dict(program.get("constraints") or {}), **s01_constraints}
    if merged_constraints:
        fields["constraints"] = merged_constraints
    if kind:
        fields["kind"] = kind
    if total_hours:
        fields["total_hours"] = total_hours
    if form:
        fields["form"] = form
    if not program.get("title") or program.get("title") == "Новая программа":
        fields["title"] = guess_title(brief_text)
    if s01.get("goal"):
        fields["goal"] = s01["goal"]
    final_form = answers.get("final_attestation")
    if final_form:
        fields["final_att_form"] = final_form

    await programs_repo.update_program(session, program_id=program_id, fields=fields)

    questions = s03.get("questions") or []
    if questions:
        await programs_repo.replace_questions(session, program_id=program_id, questions=questions)

    # Отвеченные вопросы не удаляются; если остались открытые — статус clarifying.
    open_count = await programs_repo.open_questions_count(session, program_id)
    stored = await programs_repo.get_questions(session, program_id)
    questions_out = [
        {
            "id": str(row["id"]),
            "slot": row["slot"],
            "ord": row["ord"],
            "text": row["question"],
            "options": row["options"] or [],
            "allow_default": True,
            "allow_free_text": row["slot"] in ("total_hours", "audience", "entry_level"),
        }
        for row in stored
        if row["answer"] is None
    ]
    if open_count > 0:
        if program["status"] in ("draft", "clarifying"):
            await programs_repo.set_status(session, program_id=program_id, status="clarifying")
        await _publish(
            program_id,
            "needs_input",
            {"questions_url": f"/api/v1/programs/{program_id}/questions"},
        )
    elif program["status"] == "clarifying":
        await programs_repo.set_status(session, program_id=program_id, status="draft")

    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="agent.intake",
        program_id=program_id,
        details={"kind": kind, "total_hours": total_hours, "questions": open_count},
    )
    return {"s01": s01, "s02": s02, "s03": s03, "questions": questions_out}


def _kind_from_answer(value: str | None) -> str | None:
    """Вид программы из ответа пользователя на слот kind (важнее правил S02)."""
    if not value:
        return None
    lowered = value.lower().replace("ё", "е")
    if "общеразвива" in lowered:
        return "dop"
    if any(marker in lowered for marker in ("повыш", "квалификац", "переподготов", "стажиров", "дпп")):
        return "dpp_pk"
    return None


# ---------------------------------------------------------------------------
# Ядро: сборка каркаса (S04–S10)
# ---------------------------------------------------------------------------


def _assemble_kit(
    program: dict[str, Any],
    answers: dict[str, str],
    s01: dict[str, Any],
    s02: dict[str, Any],
    s04: dict[str, Any],
    s05: dict[str, Any],
    s06: dict[str, Any],
    s07: dict[str, Any],
    s08: dict[str, Any],
    s09: dict[str, Any],
) -> KitV1:
    """Собрать KitV1 из выходов навыков S01–S09 (часы — только из S08)."""
    kind = str(s02.get("kind") or program.get("kind") or "dop")
    total_hours = int(program.get("total_hours") or 0)
    if total_hours <= 0:
        raise ValueError("framework: не задан объём программы")
    constraints = s08.get("constraints") or {}
    final_hours = int(constraints.get("final_att") or program.get("final_att_hours") or 2)
    final_form = answers.get("final_attestation") or program.get("final_att_form") or DEFAULT_FINAL_FORM
    form = program.get("form") or _map_form(answers.get("form")) or "part_time"

    header = ProgramHeader(
        kind=kind,
        title=program.get("title") or "Программа",
        form=form,
        total_hours=total_hours,
        final_attestation=FinalAttestation(form=final_form, hours=final_hours),
        document=_document_for(kind),
        organization=program.get("org_name"),
        year=datetime.now(timezone.utc).year,
    )

    s01_profile = s01.get("profile") or {}
    profile = ProgramProfile(
        audience=s01_profile.get("audience"),
        entry_level=s01_profile.get("entry_level"),
        schedule=s01_profile.get("schedule"),
        duration_hint=s01_profile.get("duration_hint"),
        notes=s01_profile.get("notes"),
        glossary=s01_profile.get("glossary") or {},
        constraints=ProgramConstraints(
            **{
                key: value
                for key, value in (program.get("constraints") or {}).items()
                if key in ProgramConstraints.model_fields
            }
        ),
    )

    prof_standard_raw = s05.get("prof_standard") or None
    labor_functions_raw = s05.get("labor_functions") or []
    competencies: list[Competency] = []
    for comp in s06.get("competencies") or []:
        codes = set(comp.get("labor_function_codes") or [])
        lf_refs = [
            LaborFunctionRef(code=lf["code"], title=lf.get("title", ""), otf_code=lf.get("otf_code"))
            for lf in labor_functions_raw
            if lf.get("code") and (not codes or lf["code"] in codes)
        ]
        prof_ref = None
        if kind == "dpp_pk" and prof_standard_raw and prof_standard_raw.get("code"):
            prof_ref = ProfStandardRef(
                code=prof_standard_raw["code"], title=prof_standard_raw.get("title", "")
            )
        competencies.append(
            Competency(
                ref=comp["ref"],
                title=comp["title"],
                activity_kind=comp.get("activity_kind"),
                prof_standard=prof_ref,
                labor_functions=lf_refs,
                outcomes=[
                    Outcome(
                        ref=outcome["ref"],
                        type=outcome["type"],
                        text=outcome["text"],
                        bloom_level=outcome.get("bloom_level"),
                    )
                    for outcome in comp.get("outcomes") or []
                ],
            )
        )

    rows = s08.get("rows") or {}
    distance = s08.get("distance") or {}
    modules: list[Module] = []
    for module in s07.get("modules") or []:
        topics: list[Topic] = []
        for topic in module.get("topics") or []:
            row = rows.get(topic["ref"]) or {}
            topics.append(
                Topic(
                    ref=topic["ref"],
                    title=topic["title"],
                    summary=topic.get("summary"),
                    workload=Workload(
                        lecture=int(row.get("lecture", 0) or 0),
                        practice=int(row.get("practice", 0) or 0),
                        lab=int(row.get("lab", 0) or 0),
                        self_study=int(row.get("self_study", 0) or 0),
                        current_control=int(row.get("current_control", 0) or 0),
                        distance=int(distance.get(topic["ref"], 0) or 0),
                    ),
                    outcome_refs=list(topic.get("outcome_refs") or []),
                    complexity=int(topic.get("complexity", 1) or 1),
                    practicality=float(topic.get("practicality", 0.5) or 0.5),
                    weight=float(topic.get("weight", 1.0) or 1.0),
                )
            )
        modules.append(
            Module(
                ref=module["ref"],
                number=int(module["number"]),
                title=module["title"],
                weight=float(module.get("weight", 1.0) or 1.0),
                att_form=module.get("att_form"),
                topics=topics,
            )
        )

    calendar = None
    if s09.get("sessions"):
        calendar = Calendar(
            weeks=int(s09.get("weeks") or 1),
            days=int(s09.get("days") or 1),
            days_per_week=int(s09.get("days_per_week") or 5),
            max_hours_per_day=int(s09.get("max_hours_per_day") or 8),
            sessions=[CalendarSession(**session_row) for session_row in s09["sessions"]],
        )

    gaps = [
        *(s01.get("gaps") or []),
        *(s06.get("gaps") or []),
        *(s07.get("gaps") or []),
        *verification_assumptions_for_competencies(competencies),
    ]
    # Задачи программы (раздел шаблона 1.2) выводим из компетенций детерминированно:
    # отдельного поля «задачи» навыки S01–S07 не формируют.
    tasks = [f"Сформировать компетенцию: {comp.title}" for comp in competencies]
    return KitV1(
        program=header,
        profile=profile,
        framework=Framework(
            goal=s01.get("goal") or "",
            tasks=tasks,
            competencies=competencies,
            modules=modules,
            final_attestation=FinalAttestation(form=final_form, hours=final_hours),
            calendar=calendar,
            gaps=gaps,
        ),
        content=Content(),
    )


async def framework_core(
    session: AsyncSession,
    program_id: str,
    *,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """S04–S10: собрать каркас, сохранить снимок и отчёт, вернуть на проверку."""
    if not await programs_repo.clarification_allows_framework(session, program_id):
        raise ValueError("CLARIFICATION_REQUIRED: есть неотвеченные уточнения — каркас не собираем (ТК-4)")
    program = await _load_program(session, program_id)
    brief_text = await _brief_of(program)
    if not brief_text:
        raise ValueError("framework: у программы нет брифа")
    files_text, references = await _files_context(session, program_id)
    answers = await _answers_by_slot(session, program_id)
    registries = await _registries_for_inputs(session)
    constraints = _constraints_dict(program, answers)

    gateway = gateway or make_gateway(program_id, str(program["org_id"]))
    runner = make_runner()
    scope = f"framework:{program['current_version']}"
    ctx = await _seeded_context(program_id, scope, {}, gateway=gateway, extra={"registries": registries})
    prefix = ctx.extra["checkpoint_prefix"]

    inputs: dict[str, Any] = {
        "brief": brief_text,
        "files_text": files_text,
        "references": references,
        "reference_texts": [ref["text"] for ref in references if (ref.get("text") or "").strip()],
        "kind": program.get("kind") or answers.get("kind"),
        "profile": program.get("profile") or {},
        "constraints": constraints,
        "registries": registries,
        "answers": answers,
        "candidates": registries["prof_standards"],
        "allowed_normative": [f"{a['number']}" for a in registries["normative_acts"]],
    }

    await runner.run("S09", inputs, ctx, progress_cb)  # цепочка S01 → S05 → S06 → S07 → S08 → S09
    if any((ref.get("text") or "").strip() for ref in references):
        await runner.run("S04", inputs, ctx, progress_cb)
    else:
        # Референсов с извлекаемым текстом нет (пустой скан/нет файлов) —
        # анализ пропускаем, а не валим задачу (S10 ждёт S04 в зависимостях).
        await ctx.checkpoint.save(f"{prefix}S04", {})

    s01 = await ctx.checkpoint.load(f"{prefix}S01") or {}
    s02 = await ctx.checkpoint.load(f"{prefix}S02") or {}
    s04 = await ctx.checkpoint.load(f"{prefix}S04") or {}
    s05 = await ctx.checkpoint.load(f"{prefix}S05") or {}
    s06 = await ctx.checkpoint.load(f"{prefix}S06") or {}
    s07 = await ctx.checkpoint.load(f"{prefix}S07") or {}
    s08 = await ctx.checkpoint.load(f"{prefix}S08") or {}
    s09 = await ctx.checkpoint.load(f"{prefix}S09") or {}

    kit = _assemble_kit(program, answers, s01, s02, s04, s05, s06, s07, s08, s09)
    kit_dump = kit.model_dump(mode="json")
    sample_declared = _sample_declared_totals_from_errors(s04.get("sample_errors") or [])
    s10 = (
        await runner.run(
            "S10",
            {
                **inputs,
                "kit": kit_dump,
                "declared_totals": sample_declared,
                "reference_texts": inputs.get("reference_texts") or [],
            },
            ctx,
            progress_cb,
        )
    ).output

    await framework_repo.save_kit(session, program_id, kit)
    version = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason="framework_generated",
        snapshot=kit.model_dump(mode="json"),
        created_by=program.get("owner_id"),
    )
    report = Report.model_validate(s10["report"]) if s10.get("report") else None
    if report is not None:
        await framework_repo.save_report(session, program_id, version, report)
    await programs_repo.set_status(session, program_id=program_id, status="framework_review")
    await _publish(
        program_id,
        "framework_ready",
        {"version": version, "checks": {"passed": bool(s10.get("passed"))}},
    )
    logger.info(
        "framework.saved", program_id=program_id, version=version,
        modules=len(kit.framework.modules), total_hours=kit.program.total_hours,
        checks_passed=bool(s10.get("passed")),
    )
    return {"kit": kit, "version": version, "report": report, "s10": s10}


# ---------------------------------------------------------------------------
# Ядро: генерация комплекта (S11–S19)
# ---------------------------------------------------------------------------


def _dedupe_assessment_refs(items: list[Assessment]) -> list[Assessment]:
    """Уникальность ref оценочных средств: дубликаты получают суффикс -N.

    Модель может выдать Q-001 в каждой теме — в БД ref уникален, а GET
    /kit/items/{ref} должен возвращать ровно один элемент.
    """
    seen: dict[str, int] = {}
    result: list[Assessment] = []
    for item in items:
        count = seen.get(item.ref, 0) + 1
        seen[item.ref] = count
        result.append(item if count == 1 else item.model_copy(update={"ref": f"{item.ref}-{count}"}))
    return result


def _assessment_from(item: dict[str, Any]) -> Assessment | None:
    """Оценочное средство из выхода S14/S15/S16 (с отбрасыванием невалидных)."""
    try:
        options = [
            AssessmentOption(id=str(o.get("id") or "a"), text=str(o.get("text") or ""))
            for o in item.get("options") or []
            if isinstance(o, dict)
        ]
        answer_key = item.get("answer_key")
        rubric = [
            Criterion(
                criterion=str(c.get("criterion") or ""),
                max_points=float(c.get("max_points") or 0),
                levels=[str(level) for level in c.get("levels") or []],
            )
            for c in item.get("rubric") or []
            if isinstance(c, dict)
        ]
        return Assessment(
            ref=str(item["ref"]),
            kind=item["kind"],
            topic_ref=item.get("topic_ref"),
            module_ref=item.get("module_ref"),
            stem=str(item.get("stem") or ""),
            qtype=item.get("qtype"),
            options=options,
            answer_key=AnswerKey(**answer_key) if isinstance(answer_key, dict) else None,
            rubric=rubric,
            outcome_refs=[str(r) for r in item.get("outcome_refs") or []],
            difficulty=item.get("difficulty"),
        )
    except Exception:
        return None


async def kit_core(
    session: AsyncSession,
    program_id: str,
    options: dict[str, Any] | None = None,
    *,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """S11–S19: параллельная генерация содержания по темам + самопроверка."""
    options = options or {}
    program = await _load_program(session, program_id)
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None or not kit.framework.modules:
        raise ValueError("kit: каркас не собран")
    registries = await _registries_for_inputs(session)
    gateway = gateway or make_gateway(program_id, str(program["org_id"]))
    runner = make_runner()
    version = int(program["current_version"])
    kit_dump = kit.model_dump(mode="json")
    profile_json = kit.profile.model_dump(mode="json")
    outcomes_json = [o.model_dump(mode="json") for o in kit.iter_outcomes()]

    slides_modules = {str(ref) for ref in (options.get("slides") or {}).get("modules") or []}
    if not slides_modules and kit.framework.modules:
        slides_modules = {kit.framework.modules[0].ref}  # минимум один модуль (ЗАД-30)

    # Число вопросов из запроса (tests.final_questions, напр. 10 для ТК-1):
    # распределяем по темам, минимум 2 на тему (V-COV-02).
    n_topics = max(1, len(list(kit.iter_topics())))
    requested_questions = int((options.get("tests") or {}).get("final_questions") or 0)
    per_topic_questions = max(2, -(-requested_questions // n_topics)) if requested_questions else 3
    _, reference_list = await _files_context(session, program_id)
    reference_texts = [ref["text"] for ref in reference_list if (ref.get("text") or "").strip()]

    module_programs: list[dict[str, Any]] = []
    lecture_plans: list[dict[str, Any]] = []
    slides: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []

    llm_sem = asyncio.Semaphore(settings.llm_concurrency)

    async def _topic_bundle(
        module: Module,
        module_dump: dict[str, Any],
        module_scope: str,
        s11: dict[str, Any],
        topic: Topic,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        topic_dump = topic.model_dump(mode="json")
        topic_ctx = await _seeded_context(
            program_id,
            f"{module_scope}:{topic.ref}",
            {"S11": s11},
            gateway=gateway,
            extra={"registries": registries, "kit": kit_dump},
        )
        common = {
            "kit": kit_dump,
            "topic": topic_dump,
            "module_ref": module.ref,
            "topics": [topic_dump],
            "outcomes": outcomes_json,
            "profile": profile_json,
            "registries": registries,
        }
        content_common = {**common, "outcomes": _topic_outcomes(outcomes_json, topic.outcome_refs)}
        lectures: list[dict[str, Any]] = []
        slide_blocks: list[dict[str, Any]] = []
        question_blocks: list[dict[str, Any]] = []
        task_blocks: list[dict[str, Any]] = []
        async with llm_sem:
            s12 = (await runner.run("S12", content_common, topic_ctx, progress_cb)).output
            lectures.extend(s12.get("lecture_plans") or [])
            if module.ref in slides_modules:
                s13 = (await runner.run("S13", content_common, topic_ctx, progress_cb)).output
                slide_blocks.extend(s13.get("slides") or [])
            s14 = (await runner.run("S14", {**common, "count": per_topic_questions}, topic_ctx, progress_cb)).output
            question_blocks.extend(s14.get("questions") or [])
            s15 = (await runner.run("S15", common, topic_ctx, progress_cb)).output
            task_blocks.extend(s15.get("tasks") or [])
        return lectures, slide_blocks, question_blocks, task_blocks

    for module in kit.framework.modules:
        module_dump = module.model_dump(mode="json")
        module_scope = f"kit:{version}:{module.ref}"
        module_ctx = await _seeded_context(
            program_id,
            module_scope,
            {"S04": {}, "S10": {}},
            gateway=gateway,
            extra={"registries": registries, "kit": kit_dump},
        )
        s11 = (
            await runner.run(
                "S11",
                {
                    "kit": kit_dump,
                    "module": module_dump,
                    "outcomes": outcomes_json,
                    "profile": profile_json,
                    "registries": registries,
                },
                module_ctx,
                progress_cb,
            )
        ).output
        module_programs.extend(s11.get("module_programs") or [])

        topic_results = await asyncio.gather(
            *(_topic_bundle(module, module_dump, module_scope, s11, topic) for topic in module.topics)
        )
        for lectures, slide_blocks, question_blocks, task_blocks in topic_results:
            lecture_plans.extend(lectures)
            slides.extend(slide_blocks)
            questions.extend(question_blocks)
            tasks.extend(task_blocks)

    # Итоговая аттестация (S16) и источники (S17 → S18)
    assessment_ctx = await _seeded_context(
        program_id,
        f"kit:{version}:assessment",
        {"S10": {}},
        gateway=gateway,
        extra={"registries": registries, "kit": kit_dump},
    )
    s16 = (
        await runner.run(
            "S16",
            {
                "kit": kit_dump,
                "outcomes": outcomes_json,
                "form": kit.framework.final_attestation.form,
                "kind": kit.program.kind,
                "profile": profile_json,
                "registries": registries,
            },
            assessment_ctx,
            progress_cb,
        )
    ).output

    sources_ctx = await _seeded_context(
        program_id,
        f"kit:{version}:sources",
        {"S11": {}},
        gateway=gateway,
        extra={"registries": registries, "kit": kit_dump},
    )
    s18 = (
        await runner.run(
            "S18",
            {
                "kit": kit_dump,
                "modules": [m.model_dump(mode="json") for m in kit.framework.modules],
                "topics": [t.model_dump(mode="json") for t in kit.iter_topics()],
                "outcomes": outcomes_json,
                "registries": registries,
                "allowed_normative": [a["number"] for a in registries["normative_acts"]],
            },
            sources_ctx,
            progress_cb,
        )
    ).output

    assessments = [
        assessment
        for item in [*questions, *tasks, *(s16.get("items") or [])]
        if (assessment := _assessment_from(item)) is not None
    ]
    assessments = _dedupe_assessment_refs(assessments)
    raw_sources = [Source(**source) for source in (s18.get("sources") or [])]
    kit.content = Content(
        module_programs=[ContentBlock(**block) for block in module_programs],
        lecture_plans=[ContentBlock(**block) for block in lecture_plans],
        slides=[ContentBlock(**block) for block in slides],
        sections=list(kit.content.sections),
        assessments=assessments,
        sources=apply_source_verification_flags(raw_sources),
    )

    # S19 — самопроверка комплекта (детерминированные правила, зависимости засеяны)
    validate_ctx = await _seeded_context(
        program_id,
        f"kit:{version}:validate",
        {"S18": s18, "S16": s16, "S15": {}, "S14": {}, "S13": {}},
        gateway=gateway,
        extra={"registries": registries},
    )
    s19 = (
        await runner.run(
            "S19",
            {
                "kit": kit.model_dump(mode="json"),
                "registries": registries,
                "reference_texts": reference_texts,
            },
            validate_ctx,
            progress_cb,
        )
    ).output
    report = Report.model_validate(s19["report"]) if s19.get("report") else None

    await framework_repo.save_kit(session, program_id, kit, update_header=False, solver_mode=True)
    new_version = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason="kit_generated",
        snapshot=kit.model_dump(mode="json"),
        created_by=program.get("owner_id"),
    )
    if report is not None:
        await framework_repo.save_report(session, program_id, new_version, report)
    await programs_repo.set_status(session, program_id=program_id, status="kit_review")
    await _publish(
        program_id,
        "kit_ready",
        {"version": new_version, "report": {"passed": bool(report.passed) if report else False}},
    )
    logger.info(
        "kit.saved", program_id=program_id, version=new_version,
        assessments=len(assessments), sources=len(kit.content.sources),
        report_passed=bool(report.passed) if report else False,
    )
    return {"kit": kit, "version": new_version, "report": report, "s19": s19}


# ---------------------------------------------------------------------------
# Ядро: точечная правка (S21) и выгрузка (S20)
# ---------------------------------------------------------------------------


def _hours_signature(kit: KitV1) -> tuple[tuple[str, str, int], ...]:
    """Сигнатура часов каркаса: менялась ли арифметика (для Human Gate при правке)."""
    return tuple(
        sorted(
            (topic.ref, activity, topic.workload.by_activity(activity))
            for topic in kit.iter_topics()
            for activity in ACTIVITIES
        )
    )


async def _regenerate_affected(
    session: AsyncSession,
    *,
    program_id: str,
    kit: KitV1,
    edit_id: str,
    instruction: str,
    affected: list[str],
    registries: dict[str, Any],
    gateway: Any,
    progress_cb: ProgressCallback,
    parts: set[str] | None = None,
) -> dict[str, int]:
    """Пересобрать только затронутые элементы комплекта (Д4 §5.9, таблица 4.7).

    Тема: план лекции (S12), слайды (S13, если были), вопросы (S14), задания (S15).
    Модуль (MP-Mx): рабочая программа модуля (S11). Часы, компетенции и соседние
    темы не трогаются — инструкция передаётся в промпты навыков.
    """
    affected_set = set(affected)
    runner = make_runner()
    profile_json = kit.profile.model_dump(mode="json")
    outcomes_json = [o.model_dump(mode="json") for o in kit.iter_outcomes()]
    kit_dump = kit.model_dump(mode="json")
    regenerated = {"topics": 0, "modules": 0}
    want = parts or {"module_program", "lecture_plan", "slides", "tests", "tasks"}

    # 1) Рабочие программы модулей, затронутые правкой (MP-Mx).
    for module in kit.framework.modules:
        if f"MP-{module.ref}" not in affected_set or "module_program" not in want:
            continue
        module_ctx = await _seeded_context(
            program_id,
            f"edit:{edit_id}:{module.ref}",
            {"S04": {}, "S10": {}},
            gateway=gateway,
            extra={"registries": registries, "kit": kit_dump},
        )
        s11 = (
            await runner.run(
                "S11",
                {
                    "kit": kit_dump,
                    "module": module.model_dump(mode="json"),
                    "outcomes": outcomes_json,
                    "profile": profile_json,
                    "registries": registries,
                    "instruction": instruction,
                },
                module_ctx,
                progress_cb,
            )
        ).output
        new_blocks = [ContentBlock(**block) for block in (s11.get("module_programs") or [])]
        if new_blocks:
            kept = [b for b in kit.content.module_programs if b.module_ref != module.ref]
            kit.content.module_programs = kept + new_blocks
            regenerated["modules"] += 1

    # 2) Затронутые темы.
    for topic in list(kit.iter_topics()):
        if topic.ref not in affected_set:
            continue
        module = next((m for m in kit.framework.modules if any(t.ref == topic.ref for t in m.topics)), None)
        topic_ctx = await _seeded_context(
            program_id,
            f"edit:{edit_id}:{topic.ref}",
            {"S11": {}},
            gateway=gateway,
            extra={"registries": registries, "kit": kit_dump},
        )
        common = {
            "kit": kit_dump,
            "topic": topic.model_dump(mode="json"),
            "module_ref": module.ref if module else None,
            "topics": [topic.model_dump(mode="json")],
            "outcomes": outcomes_json,
            "profile": profile_json,
            "registries": registries,
            "instruction": instruction,
        }

        if "lecture_plan" in want:
            s12 = (await runner.run("S12", common, topic_ctx, progress_cb)).output
            new_plans = [ContentBlock(**block) for block in (s12.get("lecture_plans") or [])]
            if new_plans:
                kit.content.lecture_plans = [
                    b for b in kit.content.lecture_plans if b.topic_ref != topic.ref
                ] + new_plans

        had_slides = any(b.topic_ref == topic.ref for b in kit.content.slides)
        if had_slides and "slides" in want:
            s13 = (await runner.run("S13", common, topic_ctx, progress_cb)).output
            new_slides = [ContentBlock(**block) for block in (s13.get("slides") or [])]
            if new_slides:
                kit.content.slides = [b for b in kit.content.slides if b.topic_ref != topic.ref] + new_slides

        new_questions: list[Assessment] = []
        new_tasks: list[Assessment] = []
        if "tests" in want:
            s14 = (await runner.run("S14", {**common, "count": 3}, topic_ctx, progress_cb)).output
            old_questions = [a for a in kit.content.assessments if a.topic_ref == topic.ref and a.kind == "test_question"]
            new_questions = _assessments_with_reused_refs(
                old_questions,
                [item for item in (s14.get("questions") or [])],
                prefix=f"Q-{topic.ref}",
            )
        if "tasks" in want:
            s15 = (await runner.run("S15", common, topic_ctx, progress_cb)).output
            old_tasks = [a for a in kit.content.assessments if a.topic_ref == topic.ref and a.kind == "seminar_task"]
            new_tasks = _assessments_with_reused_refs(
                old_tasks,
                [item for item in (s15.get("tasks") or [])],
                prefix=f"ST-{topic.ref}",
            )
        if new_questions or new_tasks:

            def _keep_assessment(item: Assessment) -> bool:
                if item.topic_ref != topic.ref:
                    return True
                if item.kind == "test_question":
                    return "tests" not in want
                if item.kind == "seminar_task":
                    return "tasks" not in want
                return True

            kit.content.assessments = [
                a for a in kit.content.assessments if _keep_assessment(a)
            ] + new_questions + new_tasks
        if any(p in want for p in ("lecture_plan", "slides", "tests", "tasks")):
            regenerated["topics"] += 1

    return regenerated


def _assessments_with_reused_refs(
    old_items: list[Assessment], new_items: list[dict[str, Any]], *, prefix: str
) -> list[Assessment]:
    """Пересобранные оценочные средства: refs переиспользуются, лишние получают новые.

    Стабильные ref сохраняют связи с РО и версиями; дубликаты ref недопустимы
    (UNIQUE (program_id, ref) в БД и GET /kit/items/{ref}).
    """
    old_refs = [item.ref for item in old_items]
    result: list[Assessment] = []
    for index, item in enumerate(new_items, start=1):
        payload = dict(item)
        if index <= len(old_refs):
            payload["ref"] = old_refs[index - 1]
        else:
            payload["ref"] = f"{prefix}-{index}"
        assessment = _assessment_from(payload)
        if assessment is not None:
            result.append(assessment)
    return result


async def edit_core(
    session: AsyncSession,
    program_id: str,
    edit_id: str,
    *,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """S21 + S19: пересобрать только затронутые элементы и повторить проверку."""
    program = await _load_program(session, program_id)
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise ValueError("edit: каркас не собран")
    edit_row = (
        await session.execute(
            text(
                """
                SELECT * FROM edit_request
                WHERE id = CAST(:eid AS uuid) AND program_id = CAST(:pid AS uuid)
                """
            ),
            {"eid": edit_id, "pid": program_id},
        )
    ).mappings().first()
    if edit_row is None:
        raise ValueError("edit: правка не найдена")

    registries = await _registries_for_inputs(session)
    gateway = gateway or make_gateway(program_id, str(program["org_id"]))
    runner = make_runner()
    kit_dump = kit.model_dump(mode="json")
    ctx = await _seeded_context(
        program_id,
        f"edit:{edit_id}",
        {"S20": {}},
        gateway=gateway,
        extra={"registries": registries, "kit": kit_dump},
    )
    s21 = (
        await runner.run(
            "S21",
            {
                "kit": kit_dump,
                "target_ref": edit_row["target_ref"],
                "instruction": edit_row["instruction"],
                "affected": edit_row["affected_refs"],
                "dry_run": False,
                "registries": registries,
            },
            ctx,
            progress_cb,
        )
    ).output

    patched_kit = KitV1.model_validate(s21["kit"])
    affected = [str(ref) for ref in (s21.get("affected") or edit_row["affected_refs"] or [])]
    instruction = str(edit_row["instruction"])

    # Часы изменились? Тогда каркас обязан вернуться на Human Gate: сохраняем БЕЗ
    # solver-флага, чтобы триггер workload_reopen сбросил утверждение (ЗАД-07).
    hours_changed = _hours_signature(kit) != _hours_signature(patched_kit)

    if not hours_changed:
        regenerated = await _regenerate_affected(
            session,
            program_id=program_id,
            kit=patched_kit,
            edit_id=edit_id,
            instruction=instruction,
            affected=affected,
            registries=registries,
            gateway=gateway,
            progress_cb=progress_cb,
        )
    else:
        regenerated = {"topics": 0, "modules": 0}

    await framework_repo.save_kit(
        session,
        program_id,
        patched_kit,
        update_header=False,
        solver_mode=not hours_changed,
    )
    version = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason=f"edit:{edit_id}",
        snapshot=patched_kit.model_dump(mode="json"),
        created_by=edit_row["author_id"],
    )
    validate_ctx = await _seeded_context(
        program_id,
        f"edit:{edit_id}:validate",
        {"S18": {}, "S16": {}, "S15": {}, "S14": {}, "S13": {}},
        gateway=gateway,
        extra={"registries": registries},
    )
    s19 = (
        await runner.run(
            "S19", {"kit": patched_kit.model_dump(mode="json"), "registries": registries}, validate_ctx, progress_cb
        )
    ).output
    report = Report.model_validate(s19["report"]) if s19.get("report") else None
    if report is not None:
        await framework_repo.save_report(session, program_id, version, report)
    await session.execute(
        text(
            """
            UPDATE edit_request SET status = 'applied', result_version = :version
            WHERE id = CAST(:eid AS uuid)
            """
        ),
        {"version": version, "eid": edit_id},
    )
    await _publish(
        program_id,
        "edit_applied",
        {"edit_id": edit_id, "version": version, "changed_refs": affected},
    )
    return {"kit": patched_kit, "version": version, "report": report, "s21": s21, "regenerated": regenerated}


def _resolve_regenerate_targets(kit: KitV1, target_ref: str, parts: set[str]) -> list[str]:
    """Список ref для _regenerate_affected: тема и/или MP-модуль."""
    affected: list[str] = []
    for module in kit.framework.modules:
        if module.ref == target_ref:
            if "module_program" in parts:
                affected.append(f"MP-{module.ref}")
            if parts & {"lecture_plan", "slides", "tests", "tasks"}:
                affected.extend(t.ref for t in module.topics)
            return affected
        for topic in module.topics:
            if topic.ref == target_ref:
                affected.append(topic.ref)
                return affected
    raise ValueError(f"kit:regenerate: элемент {target_ref} не найден")


async def kit_regenerate_core(
    session: AsyncSession,
    program_id: str,
    *,
    target_ref: str,
    parts: list[str],
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """Точечная пересборка частей комплекта без правки каркаса (часы не меняются)."""
    program = await _load_program(session, program_id)
    if program["status"] not in ("kit_review", "kit_updating", "framework_approved"):
        raise ValueError("kit:regenerate: комплект ещё не собран или недоступен")
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise ValueError("kit:regenerate: комплект не найден")
    allowed = {"module_program", "lecture_plan", "slides", "tests", "tasks"}
    part_set = {p for p in parts if p in allowed}
    if not part_set:
        raise ValueError("kit:regenerate: укажите parts (lecture_plan, slides, tests, tasks, …)")
    affected = _resolve_regenerate_targets(kit, target_ref, part_set)
    registries = await _registries_for_inputs(session)
    gateway = gateway or make_gateway(program_id, str(program["org_id"]))
    scope_id = programs_repo.new_uuid()
    regenerated = await _regenerate_affected(
        session,
        program_id=program_id,
        kit=kit,
        edit_id=scope_id,
        instruction="Пересобрать материал: устранить замечания качества (пустые блоки, слабые дистракторы).",
        affected=affected,
        registries=registries,
        gateway=gateway,
        progress_cb=progress_cb,
        parts=part_set,
    )
    await framework_repo.save_kit(session, program_id, kit, update_header=False, solver_mode=True)
    version = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason=f"kit_regenerate:{target_ref}",
        snapshot=kit.model_dump(mode="json"),
        created_by=program.get("owner_id"),
    )
    runner = make_runner()
    validate_ctx = await _seeded_context(
        program_id,
        f"kit_regen:{scope_id}",
        {"S18": {}, "S16": {}},
        gateway=gateway,
        extra={"registries": registries},
    )
    s19 = (
        await runner.run(
            "S19",
            {"kit": kit.model_dump(mode="json"), "registries": registries},
            validate_ctx,
            progress_cb,
        )
    ).output
    report = Report.model_validate(s19["report"]) if s19.get("report") else None
    if report is not None:
        await framework_repo.save_report(session, program_id, version, report)
    await programs_repo.set_status(session, program_id=program_id, status="kit_review")
    await _publish(program_id, "kit_regenerated", {"target_ref": target_ref, "version": version, "parts": list(part_set)})
    return {"kit": kit, "version": version, "report": report, "regenerated": regenerated}


async def _save_artifacts(
    session: AsyncSession,
    program_id: str,
    version: int,
    artifacts: dict[str, Any],
    *,
    export_id: str | None = None,
) -> dict[str, str]:
    """Записать артефакты S20 в Object Storage и таблицу artifact. Возвращает kind → s3_key."""
    import hashlib

    keys: dict[str, str] = {}
    storage_obj = storage.get_storage()
    for format_name, payload in artifacts.items():
        mapping = ARTIFACT_KIND_MAP.get(format_name)
        if mapping is None or payload is None:
            continue
        artifact_kind, extension = mapping
        data = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        s3_key = f"{program_id}/v{version}/{artifact_kind}.{extension}"
        storage_obj.put(
            settings.s3_bucket_art,
            s3_key,
            data,
            content_type=CONTENT_TYPES.get(artifact_kind, "application/octet-stream"),
        )
        await session.execute(
            text(
                """
                INSERT INTO artifact (program_id, version, kind, s3_key, size_bytes, sha256, export_id)
                VALUES (CAST(:pid AS uuid), :version, CAST(:kind AS artifact_kind), :key, :size, :hash,
                        CAST(:export_id AS uuid))
                ON CONFLICT (program_id, version, kind, s3_key) DO UPDATE
                SET size_bytes = EXCLUDED.size_bytes,
                    sha256 = EXCLUDED.sha256,
                    export_id = EXCLUDED.export_id,
                    created_at = now()
                """
            ),
            {
                "pid": program_id,
                "version": version,
                "kind": artifact_kind,
                "key": s3_key,
                "size": len(data),
                "hash": hashlib.sha256(data).digest(),
                "export_id": export_id,
            },
        )
        keys[artifact_kind] = s3_key
    return keys


async def export_core(
    session: AsyncSession,
    program_id: str,
    formats: list[str],
    *,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
    save_artifacts: bool = True,
    export_id: str | None = None,
) -> dict[str, Any]:
    """S20: сформировать артефакты выгрузки из KitV1."""
    program = await _load_program(session, program_id)
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise ValueError("export: комплект не собран")
    report = await framework_repo.load_latest_report(session, program_id)
    gateway = gateway or make_gateway(program_id=program_id, org_id=str(program["org_id"]))
    runner = make_runner()
    version = int(program["current_version"])
    ctx = await _seeded_context(
        program_id,
        f"export:{version}",
        {"S19": {"report": report.model_dump(mode="json") if report else None, "passed": bool(report and report.passed)}},
        gateway=gateway,
        extra={"kit": kit.model_dump(mode="json")},
    )
    artifacts = (
        await runner.run(
            "S20",
            {
                "kit": kit.model_dump(mode="json"),
                "formats": formats,
                "report": report.model_dump(mode="json") if report else None,
            },
            ctx,
            progress_cb,
        )
    ).output
    keys = (
        await _save_artifacts(session, program_id, version, artifacts, export_id=export_id)
        if save_artifacts
        else {}
    )
    await _publish(program_id, "export_ready", {"export_id": export_id or f"v{version}"})
    return {"artifacts": artifacts, "keys": keys, "version": version}


# ---------------------------------------------------------------------------
# Актуализация (S22), адаптация (S23), обслуживание
# ---------------------------------------------------------------------------


async def actualize_core(
    session: AsyncSession,
    program_id: str,
    *,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """S22: найти устаревшие темы и инструменты в загруженной старой программе."""
    program = await _load_program(session, program_id)
    files_text, references = await _files_context(session, program_id)
    old_texts = [ref["text"] for ref in references if ref["role"] in ("old_program", "sample_program", "reference")]
    registries = await _registries_for_inputs(session)
    gateway = gateway or make_gateway(program_id, str(program["org_id"]))
    runner = make_runner()
    ctx = await _seeded_context(program_id, "actualize", {"S04": {}}, gateway=gateway, extra={"registries": registries})
    s22 = (
        await runner.run(
            "S22",
            {
                "old_program": {"text": "\n\n".join(old_texts)[:60_000], "references": references},
                "tools": [],
                "service_catalog": registries["services"],
                "registries": registries,
            },
            ctx,
            progress_cb,
        )
    ).output
    profile_json = dict(program.get("profile") or {})
    profile_json["actualize_result"] = s22
    await programs_repo.update_program(session, program_id=program_id, fields={"profile": profile_json})
    await _publish(program_id, "progress", {"step": "S22", "label": "Актуализация завершена"})
    return {"s22": s22}


async def adapt_core(
    session: AsyncSession,
    program_id: str,
    payload: dict[str, Any],
    *,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """S23: программа-потомок под новую аудиторию/объём (снова Human Gate)."""
    parent = await _load_program(session, program_id)
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise ValueError("adapt: у исходной программы нет каркаса")
    answers = await _answers_by_slot(session, program_id)
    constraints = _constraints_dict(parent, answers)
    if payload.get("total_hours"):
        constraints["total"] = int(payload["total_hours"])

    gateway = gateway or make_gateway(program_id, str(parent["org_id"]))
    runner = make_runner()
    ctx = await _seeded_context(program_id, "adapt", {"S07": {}, "S08": {}}, gateway=gateway)
    s23 = (
        await runner.run(
            "S23",
            {
                "modules": [m.model_dump(mode="json") for m in kit.framework.modules],
                "new_constraints": constraints,
                "new_audience": payload.get("audience"),
                "outcomes": [o.model_dump(mode="json") for o in kit.iter_outcomes()],
            },
            ctx,
            progress_cb,
        )
    ).output

    child_kit = kit.model_copy(deep=True)
    child_kit.program.total_hours = int(constraints["total"])
    child_kit.program.final_attestation.hours = int(constraints["final_att"])
    child_kit.framework.final_attestation.hours = int(constraints["final_att"])
    rows = (s23.get("child") or {}).get("rows") or {}
    distance = (s23.get("child") or {}).get("distance") or {}
    for topic in child_kit.iter_topics():
        row = rows.get(topic.ref)
        if not row:
            continue
        topic.workload = Workload(
            lecture=int(row.get("lecture", 0) or 0),
            practice=int(row.get("practice", 0) or 0),
            lab=int(row.get("lab", 0) or 0),
            self_study=int(row.get("self_study", 0) or 0),
            current_control=int(row.get("current_control", 0) or 0),
            distance=int(distance.get(topic.ref, 0) or 0),
        )
    if payload.get("audience"):
        child_kit.profile.audience = str(payload["audience"])
    child_kit.framework.gaps = [*child_kit.framework.gaps, *(s23.get("assumptions") or [])]

    child_id = await programs_repo.create_program(
        session,
        org_id=str(parent["org_id"]),
        owner_id=str(parent["owner_id"]),
        title=f"{parent['title']} (адаптация)",
        profile={**(parent.get("profile") or {}), "parent_program": program_id},
    )
    await session.execute(
        text("UPDATE program SET parent_id = CAST(:pid AS uuid) WHERE id = CAST(:cid AS uuid)"),
        {"pid": program_id, "cid": child_id},
    )
    child_kit.program.title = f"{parent['title']} (адаптация)"
    await framework_repo.save_kit(session, child_id, child_kit)
    version = await programs_repo.save_version(
        session,
        program_id=child_id,
        reason="adapt:generated",
        snapshot=child_kit.model_dump(mode="json"),
        created_by=str(parent["owner_id"]),
    )
    await programs_repo.set_status(session, program_id=child_id, status="framework_review")
    await _publish(program_id, "progress", {"step": "S23", "label": "Создана программа-потомок"})
    return {"child_program_id": child_id, "version": version, "s23": s23}


async def maintenance_core(
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """Обслуживание: секции на 3 месяца вперёд, очистка кэша, чанки базы знаний."""
    created: list[str] = []
    now = datetime.now(timezone.utc)
    for month_offset in range(0, 3):
        month = (now.month - 1 + month_offset) % 12 + 1
        year = now.year + (now.month - 1 + month_offset) // 12
        start = f"{year:04d}-{month:02d}-01"
        end_month = month % 12 + 1
        end_year = year + (1 if month == 12 else 0)
        end = f"{end_year:04d}-{end_month:02d}-01"
        for table in ("llm_call", "audit_log"):
            partition = f"{table}_{year:04d}_{month:02d}"
            exists = (
                await session.execute(
                    text("SELECT to_regclass(:name) IS NOT NULL"), {"name": f"public.{partition}"}
                )
            ).scalar_one()
            if exists:
                continue
            await session.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {partition} PARTITION OF {table} "
                    f"FOR VALUES FROM ('{start}') TO ('{end}')"
                )
            )
            created.append(partition)

    purged = await usage_repo.purge_expired_cache(session)

    kb_document_id = payload.get("kb_document_id")
    chunks = 0
    if kb_document_id:
        chunks = await _index_kb_document(session, kb_document_id, gateway=gateway, progress_cb=progress_cb)
    return {"purged_cache_rows": purged, "kb_chunks": chunks, "partitions_created": created}


def _chunk_text(text_value: str, *, size: int = 1500, overlap: int = 200) -> list[tuple[str | None, str]]:
    """Чанкинг по абзацам с заголовками: (heading_path, content)."""
    chunks: list[tuple[str | None, str]] = []
    heading: str | None = None
    buffer = ""
    for paragraph in text_value.split("\n"):
        line = paragraph.strip()
        if not line:
            continue
        if line.startswith("## "):
            heading = line[3:].strip()
        buffer = f"{buffer}\n{line}".strip()
        if len(buffer) >= size:
            chunks.append((heading, buffer))
            buffer = buffer[-overlap:]
    if buffer.strip():
        chunks.append((heading, buffer.strip()))
    return chunks


async def _index_kb_document(
    session: AsyncSession,
    kb_document_id: str,
    *,
    gateway: Any = None,
    progress_cb: ProgressCallback = None,
) -> int:
    """Разобрать документ базы знаний на фрагменты с эмбеддингами (pgvector)."""
    row = (
        await session.execute(
            text(
                """
                SELECT d.id, d.org_id, d.file_id, f.extracted_text
                FROM kb_document d JOIN file_object f ON f.id = d.file_id
                WHERE d.id = CAST(:did AS uuid)
                """
            ),
            {"did": kb_document_id},
        )
    ).mappings().first()
    if row is None or not row["extracted_text"]:
        return 0
    chunks = _chunk_text(row["extracted_text"])
    if not chunks:
        return 0

    from karkas.infra.embeddings import embed_texts

    embeddings = await embed_texts([content for _, content in chunks])
    await session.execute(
        text("DELETE FROM kb_chunk WHERE file_id = CAST(:fid AS uuid)"),
        {"fid": row["file_id"]},
    )
    for ord_index, ((heading, content), embedding) in enumerate(zip(chunks, embeddings), start=1):
        vector_literal = "[" + ",".join(f"{value:.6f}" for value in embedding) + "]"
        await session.execute(
            text(
                """
                INSERT INTO kb_chunk (org_id, file_id, ord, heading_path, content, tokens, embedding)
                VALUES (:org_id, CAST(:fid AS uuid), :ord, :heading, :content, :tokens, CAST(:vec AS vector))
                """
            ),
            {
                "org_id": row["org_id"],
                "fid": row["file_id"],
                "ord": ord_index,
                "heading": heading,
                "content": content,
                "tokens": max(1, len(content) // 4),
                "vec": vector_literal,
            },
        )
    return len(chunks)


# ---------------------------------------------------------------------------
# Диспетчер задач (worker) и единый эндпоинт (agent/run)
# ---------------------------------------------------------------------------


async def dispatch_job(job: dict[str, Any], *, on_progress: ProgressFn | None = None) -> None:
    """Выполнить задачу очереди по виду (worker вызывает эту функцию)."""
    kind = job["kind"]
    job_id = str(job["id"]) if job.get("id") else None
    program_id = str(job["program_id"]) if job.get("program_id") else None
    payload = job.get("payload") or {}
    progress_cb = _progress_adapter(on_progress)
    factory = get_session_factory()

    if kind == "intake":
        if program_id is None:
            raise ValueError("intake: задача без программы")
        async with factory() as session:
            await intake_core(session, program_id, brief=payload.get("brief"), progress_cb=progress_cb)
            await session.commit()
        return

    if kind == "framework":
        if program_id is None:
            raise ValueError("framework: задача без программы")
        started = time.monotonic()
        async with factory() as session:
            if not await programs_repo.clarification_allows_framework(session, program_id):
                raise ValueError(
                    "CLARIFICATION_REQUIRED: есть неотвеченные уточнения — каркас не собираем (ТК-4)"
                )
            await framework_core(session, program_id, progress_cb=progress_cb)
            await session.commit()
        from karkas.infra.metrics import framework_seconds

        framework_seconds.observe(time.monotonic() - started)
        return

    if kind == "kit":
        if program_id is None:
            raise ValueError("kit: задача без программы")
        started = time.monotonic()
        async with factory() as session:
            await kit_core(session, program_id, payload, progress_cb=progress_cb)
            await session.commit()
        from karkas.infra.metrics import kit_seconds

        kit_seconds.observe(time.monotonic() - started)
        return

    if kind == "kit_regenerate":
        if program_id is None:
            raise ValueError("kit_regenerate: задача без программы")
        async with factory() as session:
            await kit_regenerate_core(
                session,
                program_id,
                target_ref=str(payload["target_ref"]),
                parts=list(payload.get("parts") or []),
                progress_cb=progress_cb,
            )
            await session.commit()
        return

    if kind == "edit":
        edit_id = payload.get("edit_id")
        if program_id is None or not edit_id:
            raise ValueError("edit: нужны program_id и edit_id")
        async with factory() as session:
            await edit_core(session, program_id, str(edit_id), progress_cb=progress_cb)
            await session.commit()
        return

    if kind == "export":
        if program_id is None:
            raise ValueError("export: задача без программы")
        formats = [str(name) for name in payload.get("formats") or ["docx", "json"]]
        async with factory() as session:
            await export_core(session, program_id, formats, progress_cb=progress_cb, export_id=job_id)
            await session.commit()
        return

    if kind == "actualize":
        if program_id is None:
            raise ValueError("actualize: задача без программы")
        async with factory() as session:
            await actualize_core(session, program_id, progress_cb=progress_cb)
            await session.commit()
        return

    if kind == "adapt":
        if program_id is None:
            raise ValueError("adapt: задача без программы")
        async with factory() as session:
            await adapt_core(session, program_id, payload, progress_cb=progress_cb)
            await session.commit()
        return

    if kind == "maintenance":
        async with factory() as session:
            await maintenance_core(session, payload, progress_cb=progress_cb)
            await session.commit()
        return

    raise ValueError(f"Неизвестный вид задачи: {kind}")


# --- Единый эндпоинт /agent/run ---------------------------------------------


def _url_host(url: str) -> str:
    """Хост URL (нижний регистр, без порта и userinfo) — через httpx.URL.

    Строковый парсинг обходится URL вида `http://169.254.169.254?x=@pypi.org`
    (в query есть «@»), поэтому хост определяет только библиотечный парсер.
    """
    try:
        host = httpx.URL(url).host
    except Exception:
        return ""
    return (host or "").lower()


def _host_allowed(host: str) -> bool:
    allowed = {h.strip().lower() for h in settings.egress_allowlist.split(",") if h.strip()}
    return host in allowed


async def _fetch_attachment_url(
    url: str,
    *,
    name: str = "attachment",
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    max_hops: int = 3,
) -> bytes:
    """Скачать вложение по URL с РУЧНОЙ обработкой редиректов (защита от SSRF).

    Каждый хоп повторно валидируется по EGRESS_ALLOWLIST: разрешённый хост не может
    увести запрос на внутренний сервис редиректом.
    """
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=20, follow_redirects=False))
    current = url
    for _ in range(max_hops + 1):
        host = _url_host(current)
        if not _host_allowed(host):
            raise ValueError(f"Вложение {name}: домен {host} вне allowlist (EGRESS_ALLOWLIST)")
        async with factory() as client:
            response = await client.get(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError(f"Вложение {name}: редирект без Location")
                current = str(httpx.URL(current).join(location))
                continue
            response.raise_for_status()
            return response.content
    raise ValueError(f"Вложение {name}: слишком много редиректов (>{max_hops})")


async def _ingest_attachment(
    session: AsyncSession, org_id: str, owner_id: str, attachment: dict[str, Any]
) -> tuple[str, str]:
    """Сохранить вложение автопрогона (base64 или URL) и вернуть (file_id, роль)."""
    name = str(attachment.get("name") or "attachment")
    data: bytes | None = None
    if attachment.get("content_base64"):
        try:
            data = base64.b64decode(str(attachment["content_base64"]), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(f"Вложение {name}: некорректный base64") from exc
    elif attachment.get("url"):
        data = await _fetch_attachment_url(str(attachment["url"]), name=name)
    if data is None:
        raise ValueError(f"Вложение {name}: нужен content_base64 или url")

    mime, extracted, meta = ingest.extract(name, data)
    sha = storage.content_sha256(data)
    s3_key = f"{org_id}/{sha.hex()}/{name}"
    storage.get_storage().put("karkas-src", s3_key, data, content_type=mime)
    from karkas.infra.repos import files as files_repo

    file_id = await files_repo.create_file(
        session,
        org_id=org_id,
        uploaded_by=owner_id,
        filename=name,
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha,
        s3_key=s3_key,
        extracted_text=extracted,
        extract_meta=meta,
    )
    role = "reference"
    lowered = name.lower()
    if "шаблон" in lowered or "template" in lowered:
        role = "template"
    elif "профстандарт" in lowered or lowered.startswith("пс"):
        role = "prof_standard"
    elif "стар" in lowered or "old" in lowered:
        role = "old_program"
    elif "образец" in lowered or "пример" in lowered or "sample" in lowered:
        role = "sample_program"
    return file_id, role


async def create_run(
    session: AsyncSession,
    *,
    org_id: str,
    owner_id: str,
    request_text: str,
    mode: str,
    auto_approve: bool,
    formats: list[str],
    attachments: list[dict[str, Any]],
    api_key_id: str | None,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    """Создать прогон единого эндпоинта: вложения → программа → agent_run.

    Вложения обрабатываются ДО создания программы: невалидное вложение
    (вне allowlist, битый base64) даёт ошибку без программы-сироты.
    """
    if len(attachments) > settings.files_per_program_max:
        raise ValueError(f"Не более {settings.files_per_program_max} вложений на прогон")

    from karkas.infra.repos import files as files_repo

    prepared: list[tuple[str, str]] = []
    for attachment in attachments:
        file_id, role = await _ingest_attachment(session, org_id, owner_id, attachment)
        prepared.append((file_id, role))

    program_id = await programs_repo.create_program(
        session,
        org_id=org_id,
        owner_id=owner_id,
        title=guess_title(request_text),
        profile={"brief": request_text},
    )
    for file_id, role in prepared:
        await files_repo.attach_to_program(session, program_id=program_id, file_id=file_id, role=role)

    run_id = programs_repo.new_uuid()
    await session.execute(
        text(
            """
            INSERT INTO agent_run (id, api_key_id, program_id, mode, status, request)
            VALUES (CAST(:rid AS uuid), CAST(:key AS uuid), CAST(:pid AS uuid), :mode, 'running', CAST(:request AS jsonb))
            """
        ),
        {
            "rid": run_id,
            "key": api_key_id,
            "pid": program_id,
            "mode": mode,
            "request": json.dumps(
                {
                    "request": request_text,
                    "mode": mode,
                    "auto_approve": auto_approve,
                    "formats": formats,
                    "attachments": [a.get("name") for a in attachments],
                    "idempotency_key": idempotency_key,
                },
                ensure_ascii=False,
            ),
        },
    )
    await programs_repo.audit(
        session,
        org_id=org_id,
        action="agent.run",
        program_id=program_id,
        details={"run_id": run_id, "mode": mode},
    )
    return {"run_id": run_id, "program_id": program_id}


async def find_run_by_idempotency(
    session: AsyncSession, idempotency_key: str, *, org_id: str | None = None
) -> str | None:
    """Найти прогон по Idempotency-Key (24 ч) в пределах организации."""
    sql = """
        SELECT ar.id FROM agent_run ar JOIN program p ON p.id = ar.program_id
        WHERE ar.request->>'idempotency_key' = :key
          AND ar.started_at > now() - interval '24 hours'
    """
    params: dict[str, Any] = {"key": idempotency_key}
    if org_id is not None:
        sql += " AND p.org_id = :org_id"
        params["org_id"] = org_id
    sql += " ORDER BY ar.started_at DESC LIMIT 1"
    row = (await session.execute(text(sql), params)).scalar_one_or_none()
    return str(row) if row else None


async def append_answers(
    session: AsyncSession, *, run_id: str, program_id: str, answers: dict[str, str | None]
) -> None:
    """Ответы автопрогона: ключи q1..q5 (по порядку) или имена слотов."""
    for key, value in answers.items():
        if value is None:
            continue
        match = re.fullmatch(r"q(\d)", str(key).strip().lower())
        if match:
            await session.execute(
                text(
                    """
                    UPDATE clarification SET answer = :answer, answered_at = now()
                    WHERE program_id = CAST(:pid AS uuid) AND ord = :ord
                    """
                ),
                {"answer": str(value), "pid": program_id, "ord": int(match.group(1))},
            )
        else:
            await session.execute(
                text(
                    """
                    UPDATE clarification SET answer = :answer, answered_at = now()
                    WHERE program_id = CAST(:pid AS uuid) AND slot = :slot
                    """
                ),
                {"answer": str(value), "pid": program_id, "slot": str(key)},
            )
    await session.execute(
        text("UPDATE agent_run SET status = 'running' WHERE id = CAST(:rid AS uuid)"),
        {"rid": run_id},
    )


async def execute_run(run_id: str) -> None:
    """Выполнить прогон единого эндпоинта (синхронно в процессе api/worker).

    Прогон захватывается advisory-lock-ом по run_id: параллельные вызовы
    (повторный POST, wait=true + фон) не запускают конвейер дважды.
    """
    import asyncpg

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        lock_conn = await asyncpg.connect(dsn)
    except Exception:
        # БД недоступна — выполнение всё равно упадёт ниже с понятной ошибкой.
        await _execute_run_body(run_id)
        return
    lock_key = f"agent_run:{run_id}"
    try:
        acquired = await lock_conn.fetchval("SELECT pg_try_advisory_lock(hashtext($1))", lock_key)
        if not acquired:
            logger.info("run.already_running", run_id=run_id)
            return
        try:
            await _execute_run_body(run_id)
        finally:
            await lock_conn.execute("SELECT pg_advisory_unlock(hashtext($1))", lock_key)
    finally:
        await lock_conn.close()


async def _execute_run_body(run_id: str) -> None:
    factory = get_session_factory()
    # Шлюз создаётся на каждом шаге с учётом организации (PgMeter/PgCache):
    # execute_run не держит единый gateway, чтобы учёт шёл в llm_call.
    gateway: Any = None
    progress_cb: ProgressCallback = None  # события публикуются точечно ниже

    async with factory() as session:
        run = (
            await session.execute(
                text("SELECT * FROM agent_run WHERE id = CAST(:rid AS uuid)"), {"rid": run_id}
            )
        ).mappings().first()
        if run is None:
            return
        if run["status"] == "completed":
            return
        program_id = str(run["program_id"])
        request_payload = run["request"] or {}
        mode = run["mode"]
        auto_approve = bool(request_payload.get("auto_approve", True))
        formats = [str(name) for name in request_payload.get("formats") or ["docx", "json"]]
        started = time.monotonic()
        timings: dict[str, float] = {}
        try:
            # 1. Разбор брифа и уточнения
            intake = await intake_core(session, program_id, gateway=gateway, progress_cb=progress_cb)
            await session.commit()
            if intake["questions"]:
                open_questions = await programs_repo.open_questions_count(session, program_id)
                if open_questions:
                    await session.execute(
                        text(
                            """
                            UPDATE agent_run SET status = 'needs_input', result = CAST(:result AS jsonb)
                            WHERE id = CAST(:rid AS uuid)
                            """
                        ),
                        {
                            "rid": run_id,
                            "result": json.dumps(
                                {"questions": intake["questions"]}, ensure_ascii=False
                            ),
                        },
                    )
                    await session.commit()
                    return

            # 2. Каркас
            t0 = time.monotonic()
            framework_result = await framework_core(session, program_id, gateway=gateway, progress_cb=progress_cb)
            timings["framework_s"] = round(time.monotonic() - t0, 1)
            await session.commit()

            report: Report | None = framework_result.get("report")
            hours_blocked = bool(report and report.errors)
            if mode == "framework":
                result = {
                    "version": framework_result["version"],
                    "kit": framework_result["kit"].model_dump(mode="json"),
                    "report": report.model_dump(mode="json") if report else None,
                    "timings": timings,
                }
                status = "completed"
            else:
                if not auto_approve:
                    await session.execute(
                        text(
                            """
                            UPDATE agent_run SET result = CAST(:result AS jsonb), status = 'running'
                            WHERE id = CAST(:rid AS uuid)
                            """
                        ),
                        {
                            "rid": run_id,
                            "result": json.dumps(
                                {
                                    "version": framework_result["version"],
                                    "kit": framework_result["kit"].model_dump(mode="json"),
                                    "detail": "Каркас готов и ожидает утверждения (auto_approve=false)",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    )
                    await session.commit()
                    return
                if hours_blocked:
                    detail = "Каркас не утверждён: часы не сходятся. " + "; ".join(
                        i.message for i in report.errors[:3]  # type: ignore[union-attr]
                    )
                    raise ValueError(detail)

                # 3. Human Gate (автопрогон) + комплект + выгрузки
                program = await _load_program(session, program_id)
                await programs_repo.set_status(
                    session, program_id=program_id, status="framework_approved",
                    approved_by=str(program["owner_id"]),
                )
                await programs_repo.save_version(
                    session, program_id=program_id, reason="framework_approved",
                    snapshot=framework_result["kit"].model_dump(mode="json"),
                )
                await session.commit()

                t1 = time.monotonic()
                kit_result = await kit_core(session, program_id, {}, gateway=gateway, progress_cb=progress_cb)
                timings["kit_s"] = round(time.monotonic() - t1, 1)
                await session.commit()

                export_result = await export_core(
                    session, program_id, formats, gateway=gateway, progress_cb=progress_cb, export_id=run_id
                )
                await session.commit()

                usage_row = await usage_repo.program_usage(session, program_id) or {}
                result = {
                    "version": kit_result["version"],
                    "kit": kit_result["kit"].model_dump(mode="json"),
                    "report": (
                        kit_result["report"].model_dump(mode="json") if kit_result.get("report") else None
                    ),
                    "artifacts": export_result["keys"],
                    "timings": {**timings, "total_s": round(time.monotonic() - started, 1)},
                    "usage": {
                        "tokens": int(usage_row.get("prompt_tokens") or 0)
                        + int(usage_row.get("completion_tokens") or 0),
                        "cost_rub": str(usage_row.get("cost_rub") or 0),
                        "calls": int(usage_row.get("calls") or 0),
                    },
                }
                status = "completed"

            await session.execute(
                text(
                    """
                    UPDATE agent_run SET status = :status, result = CAST(:result AS jsonb), finished_at = now()
                    WHERE id = CAST(:rid AS uuid)
                    """
                ),
                {
                    "rid": run_id,
                    "status": status,
                    "result": json.dumps(result, ensure_ascii=False, default=str),
                },
            )
            await session.commit()
            logger.info(
                "run.completed", run_id=run_id, program_id=program_id, status=status,
                framework_s=timings.get("framework_s"), kit_s=timings.get("kit_s"),
            )
        except Exception as exc:  # noqa: BLE001 — прогон не должен ронять процесс
            await session.rollback()
            await session.execute(
                text(
                    """
                    UPDATE agent_run SET status = 'failed', result = CAST(:result AS jsonb), finished_at = now()
                    WHERE id = CAST(:rid AS uuid)
                    """
                ),
                {
                    "rid": run_id,
                    "result": json.dumps({"detail": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
                },
            )
            await session.commit()
            logger.exception("run.failed", run_id=run_id, program_id=program_id)
            raise


async def run_result(session: AsyncSession, run_id: str) -> Any:
    """Собрать ответ единого эндпоинта (AgentRunOut) по строке agent_run."""
    from karkas.api import schemas

    row = (
        await session.execute(
            text("SELECT * FROM agent_run WHERE id = CAST(:rid AS uuid)"), {"rid": run_id}
        )
    ).mappings().first()
    if row is None:
        raise ValueError("Прогон не найден")
    result = row["result"] or {}
    program_id = str(row["program_id"])
    status = row["status"]

    kit_payload = result.get("kit")
    artifacts_urls: dict[str, str] = {}
    storage_obj = storage.get_storage()
    for kind, s3_key in (result.get("artifacts") or {}).items():
        artifacts_urls[kind] = storage_obj.presign(settings.s3_bucket_art, s3_key)

    return schemas.AgentRunOut(
        run_id=run_id,
        status=status if status in ("needs_input", "completed", "running", "failed") else "running",
        program_id=program_id,
        questions=result.get("questions") or [],
        version=result.get("version"),
        kit=KitV1.model_validate(kit_payload) if kit_payload else None,
        report=result.get("report"),
        artifacts=artifacts_urls,
        timings={k: float(v) for k, v in (result.get("timings") or {}).items()},
        usage=result.get("usage") or {},
        detail=result.get("detail"),
    )
