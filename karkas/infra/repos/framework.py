"""karkas.infra.repos.framework — загрузка/сохранение KitV1 в нормализованные таблицы.

Единственный источник истины по часам — topic_workload; при сохранении часы пишутся
только туда, при загрузке — собираются обратно в Workload (расстояние разносится
по видам работ: lecture → practice → lab).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
    LegalBasis,
    Module,
    Outcome,
    Placeholders,
    ProfStandardRef,
    ProgramConstraints,
    ProgramHeader,
    ProgramProfile,
    Report,
    ReportIssue,
    Source,
    Topic,
    Workload,
)
from karkas.infra.sql_dialect import json_param, uses_sqlite

CONTACT = ("lecture", "practice", "lab")


def _enum_param(name: str, sql_type: str) -> str:
    """Плейсхолдер enum-колонки.

    В SQLite ``CAST('practice' AS activity_type)`` даёт NUMERIC affinity и
    превращает любую нечисловую строку в ``0`` — все виды работ схлопывались
    в одно значение и падали на PK ``topic_workload``. В lite-режиме enum
    хранится текстом, поэтому CAST не нужен.
    """
    return f":{name}" if uses_sqlite() else f"CAST(:{name} AS {sql_type})"


def _json_dict(value: Any) -> dict[str, Any]:
    """JSON-колонка: PostgreSQL отдаёт dict, SQLite — строку."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "{}")
        except ValueError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _json_list(value: Any) -> list[Any]:
    """JSON-список: PostgreSQL отдаёт list, SQLite — строку."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value or "[]")
        except ValueError:
            return []
        return list(parsed) if isinstance(parsed, list) else []
    return []


class LockVersionConflict(RuntimeError):
    """CAS-версия не совпала: каркас изменил другой пользователь (→ 412)."""


def _sha256_json(payload: Any) -> bytes:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).digest()


def _split_distance(w: Workload) -> dict[tuple[str, str], int]:
    """Разнести «из них дистанционно» по контактным видам работ (lecture → practice → lab)."""
    cells: dict[tuple[str, str], int] = {}
    for activity in ACTIVITIES:
        hours = w.by_activity(activity)
        if hours:
            cells[(activity, "in_person")] = hours
    remaining = min(w.distance, sum(cells.get((a, "in_person"), 0) for a in CONTACT))
    for activity in CONTACT:
        if remaining <= 0:
            break
        take = min(remaining, cells.get((activity, "in_person"), 0))
        if not take:
            continue
        cells[(activity, "in_person")] -= take
        if cells[(activity, "in_person")] == 0:
            del cells[(activity, "in_person")]
        cells[(activity, "distance")] = cells.get((activity, "distance"), 0) + take
        remaining -= take
    return cells


# ---------------------------------------------------------------------------
# Загрузка
# ---------------------------------------------------------------------------


async def load_kit(session: AsyncSession, program_id: str) -> KitV1 | None:
    """Собрать KitV1 из нормализованных таблиц (или None, если программы нет)."""
    program = (
        (await session.execute(text("SELECT * FROM program WHERE id = :pid"), {"pid": program_id})).mappings().first()
    )
    if program is None:
        return None

    competencies_rows = (
        (
            await session.execute(
                text("SELECT * FROM competency WHERE program_id = :pid ORDER BY ord, ref"),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    outcomes_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT lo.*, lo.competency_id AS comp_id FROM learning_outcome lo
                WHERE lo.program_id = :pid ORDER BY lo.ord, lo.ref
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    lf_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT c.id AS competency_id, lf.code AS lf_code, lf.title AS lf_title, lf.otf_code,
                       ps.code AS ps_code, ps.title AS ps_title, ps.status AS ps_status, ps.order_number
                FROM competency c
                LEFT JOIN labor_function lf ON lf.id = c.labor_function_id
                LEFT JOIN prof_standard ps ON ps.id = lf.prof_standard_id
                WHERE c.program_id = :pid
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )

    outcomes_by_comp: dict[str, list[Outcome]] = {}
    outcome_ref_by_id: dict[str, str] = {}
    for r in outcomes_rows:
        outcomes_by_comp.setdefault(str(r["comp_id"]), []).append(
            Outcome(ref=r["ref"], type=r["type"], text=r["text"], bloom_level=r["bloom_level"])
        )
        outcome_ref_by_id[str(r["id"])] = r["ref"]

    lf_by_comp: dict[str, list[LaborFunctionRef]] = {}
    ps_by_comp: dict[str, ProfStandardRef | None] = {}
    for r in lf_rows:
        comp_id = str(r["competency_id"])
        if r["ps_code"]:
            ps_by_comp[comp_id] = ProfStandardRef(
                code=r["ps_code"],
                title=r["ps_title"] or "",
                status=r["ps_status"] or "active",
                order_number=r["order_number"],
            )
        else:
            ps_by_comp.setdefault(comp_id, None)
        if r["lf_code"]:
            lf_by_comp.setdefault(comp_id, []).append(
                LaborFunctionRef(code=r["lf_code"], title=r["lf_title"] or "", otf_code=r["otf_code"])
            )

    competencies = [
        Competency(
            ref=r["ref"],
            title=r["title"],
            activity_kind=r["activity_kind"],
            prof_standard=ps_by_comp.get(str(r["id"])),
            labor_functions=lf_by_comp.get(str(r["id"]), []),
            outcomes=outcomes_by_comp.get(str(r["id"]), []),
        )
        for r in competencies_rows
    ]

    module_rows = (
        (
            await session.execute(
                text("SELECT * FROM module WHERE program_id = :pid ORDER BY number"), {"pid": program_id}
            )
        )
        .mappings()
        .all()
    )
    topic_rows = (
        (
            await session.execute(
                text("SELECT * FROM topic WHERE program_id = :pid ORDER BY module_id, number"),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    workload_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT w.* FROM topic_workload w JOIN topic t ON t.id = w.topic_id
                WHERE t.program_id = :pid
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    topic_outcome_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT tl.topic_id, tl.outcome_id FROM topic_outcome tl
                JOIN topic t ON t.id = tl.topic_id WHERE t.program_id = :pid
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )

    workload_by_topic: dict[str, dict[str, int]] = {}
    for r in workload_rows:
        cell = workload_by_topic.setdefault(str(r["topic_id"]), {a: 0 for a in ACTIVITIES})
        cell[r["activity"]] = cell.get(r["activity"], 0) + int(r["hours"])
        if r["activity"] in CONTACT and r["mode"] == "distance":
            cell["distance"] = cell.get("distance", 0) + int(r["hours"])

    outcomes_by_topic: dict[str, list[str]] = {}
    for r in topic_outcome_rows:
        ref = outcome_ref_by_id.get(str(r["outcome_id"]))
        if ref:
            outcomes_by_topic.setdefault(str(r["topic_id"]), []).append(ref)

    topics_by_module: dict[str, list[Topic]] = {}
    for r in topic_rows:
        cells = workload_by_topic.get(str(r["id"]), {a: 0 for a in ACTIVITIES})
        topics_by_module.setdefault(str(r["module_id"]), []).append(
            Topic(
                ref=r["ref"],
                title=r["title"],
                summary=r["summary"],
                workload=Workload(
                    lecture=cells.get("lecture", 0),
                    practice=cells.get("practice", 0),
                    lab=cells.get("lab", 0),
                    self_study=cells.get("self_study", 0),
                    current_control=cells.get("current_control", 0),
                    distance=cells.get("distance", 0),
                ),
                outcome_refs=sorted(outcomes_by_topic.get(str(r["id"]), [])),
                control_form=r["control_form"],
                complexity=r["complexity"],
                practicality=float(r["practicality"]),
                weight=float(r["weight"]),
                locked=_json_list(r.get("locked")),
            )
        )

    modules = [
        Module(
            ref=r["ref"],
            number=r["number"],
            title=r["title"],
            weight=float(r["weight"]),
            att_form=r["att_form"],
            topics=topics_by_module.get(str(r["id"]), []),
        )
        for r in module_rows
    ]

    profile_json = _json_dict(program["profile"])
    constraints_json = _json_dict(program["constraints"])
    program_constraints = ProgramConstraints(
        **{k: v for k, v in constraints_json.items() if k in ProgramConstraints.model_fields}
    )

    calendar = await _load_calendar(session, program_id, program_constraints)
    content = await _load_content(session, program_id, outcome_ref_by_id)
    report = await _load_report(session, program_id, int(program["current_version"]))

    profile = ProgramProfile(
        audience=profile_json.get("audience"),
        entry_level=profile_json.get("entry_level"),
        schedule=profile_json.get("schedule"),
        duration_hint=profile_json.get("duration_hint"),
        notes=profile_json.get("notes"),
        glossary=profile_json.get("glossary") or {},
        constraints=program_constraints,
    )

    header = ProgramHeader(
        kind=program["kind"] or "dop",
        title=program["title"],
        form=program["form"] or "full_time",
        total_hours=int(program["total_hours"] or 1),
        final_attestation=FinalAttestation(
            form=program["final_att_form"] or "итоговая аттестация",
            hours=int(program["final_att_hours"] or 0),
        ),
        document=profile_json.get("document", ""),
        legal_basis=[LegalBasis(**lb) for lb in profile_json.get("legal_basis", [])],
        organization=profile_json.get("organization"),
        city=profile_json.get("city"),
        year=profile_json.get("year"),
    )

    return KitV1(
        program=header,
        profile=profile,
        placeholders=Placeholders(),
        framework=Framework(
            goal=program["goal"] or "",
            tasks=profile_json.get("tasks", []),
            competencies=competencies,
            modules=modules,
            final_attestation=FinalAttestation(
                form=program["final_att_form"] or "итоговая аттестация",
                hours=int(program["final_att_hours"] or 0),
            ),
            calendar=calendar,
            gaps=profile_json.get("gaps", []),
        ),
        content=content,
        report=report,
    )


async def _load_calendar(session: AsyncSession, program_id: str, constraints: ProgramConstraints) -> Calendar | None:
    """Календарь из БД. days_per_week/max_hours_per_day восстанавливаем из
    ограничений программы: в calendar_session они не хранятся, и без этого
    reload давал ложный V-CAL-01 (например, ТК-5: 64 дня / 10 недель)."""
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT cs.*, t.ref AS topic_ref FROM calendar_session cs
                LEFT JOIN topic t ON t.id = cs.topic_id
                WHERE cs.program_id = :pid ORDER BY cs.seq
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return None
    sessions = [
        CalendarSession(
            seq=r["seq"],
            week=r["week_no"],
            day=r["day_no"],
            topic_ref=r["topic_ref"],
            activity=r["activity"],
            mode=r["mode"],
            hours=r["hours"],
        )
        for r in rows
    ]
    return Calendar(
        weeks=max(r["week_no"] for r in rows),
        days=max(r["day_no"] for r in rows),
        days_per_week=int(constraints.days_per_week or 5),
        max_hours_per_day=int(constraints.max_hours_per_day or 8),
        sessions=sessions,
    )


async def _load_content(session: AsyncSession, program_id: str, outcome_ref_by_id: dict[str, str]) -> Content:
    block_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT cb.*, m.ref AS module_ref, t.ref AS topic_ref FROM content_block cb
                LEFT JOIN module m ON m.id = cb.module_id
                LEFT JOIN topic t ON t.id = cb.topic_id
                WHERE cb.program_id = :pid ORDER BY cb.ref
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    blocks = [
        ContentBlock(
            ref=r["ref"],
            kind=r["kind"],
            module_ref=r["module_ref"],
            topic_ref=r["topic_ref"],
            body=_json_dict(r["body"]),
            generated_by=r["generated_by"],
            stale=r["stale"],
        )
        for r in block_rows
    ]

    assessment_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT ai.*, t.ref AS topic_ref, m.ref AS module_ref FROM assessment_item ai
                LEFT JOIN topic t ON t.id = ai.topic_id
                LEFT JOIN module m ON m.id = ai.module_id
                WHERE ai.program_id = :pid ORDER BY ai.ref
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    ao_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT ao.item_id, ao.outcome_id FROM assessment_outcome ao
                JOIN assessment_item ai ON ai.id = ao.item_id WHERE ai.program_id = :pid
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    outcome_refs_by_item: dict[str, list[str]] = {}
    for r in ao_rows:
        ref = outcome_ref_by_id.get(str(r["outcome_id"]))
        if ref:
            outcome_refs_by_item.setdefault(str(r["item_id"]), []).append(ref)

    assessments = []
    for r in assessment_rows:
        item_refs = sorted(outcome_refs_by_item.get(str(r["id"]), []))
        if not item_refs:
            continue  # оценочное средство без РО недопустимо (V-COV-04)
        options = [AssessmentOption(**o) for o in _json_list(r["options"])]
        answer_key = AnswerKey(**_json_dict(r["answer_key"])) if r["answer_key"] else None
        rubric = [Criterion(**c) for c in _json_list(r["rubric"])]
        assessments.append(
            Assessment(
                ref=r["ref"],
                kind=r["kind"],
                topic_ref=r["topic_ref"],
                module_ref=r["module_ref"],
                stem=r["stem"],
                qtype=r["qtype"],
                options=options,
                answer_key=answer_key,
                rubric=rubric,
                outcome_refs=item_refs,
                difficulty=r["difficulty"],
            )
        )

    source_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT s.*, na.number AS act_number FROM source s
                LEFT JOIN normative_act na ON na.id = s.normative_act_id
                WHERE s.program_id = :pid ORDER BY s.ref
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    usage_rows = (
        (
            await session.execute(
                text(
                    """
                SELECT su.source_id, t.ref AS topic_ref FROM source_usage su
                JOIN source s ON s.id = su.source_id
                JOIN topic t ON t.id = su.topic_id
                WHERE s.program_id = :pid
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    topics_by_source: dict[str, list[str]] = {}
    for r in usage_rows:
        topics_by_source.setdefault(str(r["source_id"]), []).append(r["topic_ref"])

    sources = [
        Source(
            ref=r["ref"],
            section=r["section"],
            citation=r["citation"],
            url=r["url"],
            isbn=r["isbn"],
            normative_act_ref=r["act_number"],
            status=r["status"],
            evidence=_json_dict(r["evidence"]),
            topic_refs=sorted(topics_by_source.get(str(r["id"]), [])),
        )
        for r in source_rows
    ]

    return Content(
        module_programs=[b for b in blocks if b.kind == "module_program"],
        lecture_plans=[b for b in blocks if b.kind == "lecture_plan"],
        slides=[b for b in blocks if b.kind == "slides"],
        sections=[b for b in blocks if b.kind in ("template_section", "annotation")],
        assessments=assessments,
        sources=sources,
    )


async def _load_report(session: AsyncSession, program_id: str, version: int) -> Report | None:
    run = (
        (
            await session.execute(
                text(
                    """
                SELECT * FROM validation_run
                WHERE program_id = :pid ORDER BY created_at DESC LIMIT 1
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .first()
    )
    if run is None:
        return None
    issues_rows = (
        (
            await session.execute(
                text("SELECT * FROM validation_issue WHERE run_id = :rid ORDER BY severity, rule_code"),
                {"rid": run["id"]},
            )
        )
        .mappings()
        .all()
    )
    summary = _json_dict(run["summary"])
    return Report(
        passed=run["passed"],
        version=run["version"],
        duration_ms=run["duration_ms"],
        summary=summary,
        issues=[
            ReportIssue(
                rule_code=r["rule_code"],
                severity=r["severity"],
                entity_ref=r["entity_ref"],
                message=r["message"],
                fix_hint=_json_dict(r["fix_hint"]),
            )
            for r in issues_rows
        ],
        gaps=summary.get("gaps", []),
        sample_findings=summary.get("sample_findings", []),
        assumptions=summary.get("assumptions", []),
    )


async def load_latest_report(session: AsyncSession, program_id: str) -> Report | None:
    """Последний отчёт самопроверки программы (для GET /report)."""
    return await _load_report(session, program_id, 0)


# ---------------------------------------------------------------------------
# Сохранение
# ---------------------------------------------------------------------------


async def save_kit(
    session: AsyncSession,
    program_id: str,
    kit: KitV1,
    *,
    update_header: bool = True,
    solver_mode: bool = False,
    expected_lock_version: int | None = None,
) -> None:
    """Полная транзакционная замена каркаса и содержания программы.

    ``solver_mode=True`` ставит сессионный флаг ``karkas.solver`` — триггер
    ``workload_reopen`` не переоткрывает утверждённый каркас, когда внутренняя
    пересборка переписывает ТЕ ЖЕ часы (генерация комплекта, точечная правка
    содержания). Пользовательские правки часов (PATCH/rebalance через API)
    идут без флага — каркас возвращается на Human Gate, как требует ЗАД-07.

    ``expected_lock_version`` — атомарный CAS: правка применяется, только если
    версия не изменилась (иначе LockVersionConflict → 412), поэтому конкурентные
    PATCH не теряют изменения молча.
    """
    if solver_mode and not uses_sqlite():
        await session.execute(text("SET LOCAL karkas.solver = 'on'"))
    if update_header:
        sql = f"""
                UPDATE program SET
                    title = :title,
                    kind = {_enum_param("kind", "program_kind")},
                    form = {_enum_param("form", "program_form")},
                    total_hours = :total_hours,
                    final_att_hours = :final_att_hours,
                    final_att_form = :final_att_form,
                    goal = :goal,
                    profile = {json_param("profile")},
                    constraints = {json_param("constraints")}
                WHERE id = :pid
        """
        params: dict[str, Any] = {
            "pid": program_id,
            "title": kit.program.title,
            "kind": kit.program.kind,
            "form": kit.program.form,
            "total_hours": kit.program.total_hours,
            "final_att_hours": kit.program.final_attestation.hours,
            "final_att_form": kit.program.final_attestation.form,
            "goal": kit.framework.goal,
            "profile": json.dumps(
                {
                    "audience": kit.profile.audience,
                    "entry_level": kit.profile.entry_level,
                    "schedule": kit.profile.schedule,
                    "duration_hint": kit.profile.duration_hint,
                    "notes": kit.profile.notes,
                    "glossary": kit.profile.glossary,
                    "document": kit.program.document,
                    "legal_basis": [lb.model_dump(mode="json") for lb in kit.program.legal_basis],
                    "organization": kit.program.organization,
                    "city": kit.program.city,
                    "year": kit.program.year,
                    "tasks": kit.framework.tasks,
                    "gaps": kit.framework.gaps,
                },
                ensure_ascii=False,
            ),
            "constraints": kit.profile.constraints.model_dump_json(),
        }
        if expected_lock_version is not None:
            sql += " AND lock_version = :expected_lock_version"
            params["expected_lock_version"] = expected_lock_version
        sql += " RETURNING id"
        updated = (await session.execute(text(sql), params)).scalar_one_or_none()
        if updated is None:
            raise LockVersionConflict(f"Каркас изменил другой пользователь (ожидалась версия {expected_lock_version})")

    # Полная замена дочерних строк (черновик; история — в program_version).
    for table in (
        "assessment_item",
        "content_block",
        "source",
        "calendar_session",
        "topic",
        "module",
        "learning_outcome",
        "competency",
    ):
        await session.execute(text(f"DELETE FROM {table} WHERE program_id = :pid"), {"pid": program_id})

    # --- Компетенции и РО ---
    outcome_ids: dict[str, str] = {}
    for c_ord, comp in enumerate(kit.framework.competencies, start=1):
        lf_id = None
        if comp.labor_functions and comp.prof_standard is not None:
            lf_id = (
                await session.execute(
                    text(
                        """
                        SELECT lf.id FROM labor_function lf
                        JOIN prof_standard ps ON ps.id = lf.prof_standard_id
                        WHERE ps.code = :ps AND lf.code = :lf
                        LIMIT 1
                        """
                    ),
                    {"ps": comp.prof_standard.code, "lf": comp.labor_functions[0].code},
                )
            ).scalar_one_or_none()
        comp_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO competency (id, program_id, ref, title, activity_kind, labor_function_id, ord)
                    VALUES (:cid, :pid, :ref, :title, :activity_kind, :lf_id, :ord)
                    RETURNING id
                    """
                ),
                {
                    "cid": str(uuid.uuid4()),
                    "pid": program_id,
                    "ref": comp.ref,
                    "title": comp.title,
                    "activity_kind": comp.activity_kind,
                    "lf_id": lf_id,
                    "ord": c_ord,
                },
            )
        ).scalar_one()
        for o_ord, outcome in enumerate(comp.outcomes, start=1):
            oid = (
                await session.execute(
                    text(
                        f"""
                        INSERT INTO learning_outcome (id, program_id, competency_id, ref, type, text, bloom_level, ord)
                        VALUES (:oid, :pid, :cid, :ref, {_enum_param("type", "outcome_type")}, :text, :bloom, :ord)
                        RETURNING id
                        """
                    ),
                    {
                        "oid": str(uuid.uuid4()),
                        "pid": program_id,
                        "cid": comp_id,
                        "ref": outcome.ref,
                        "type": outcome.type,
                        "text": outcome.text,
                        "bloom": outcome.bloom_level,
                        "ord": o_ord,
                    },
                )
            ).scalar_one()
            outcome_ids[outcome.ref] = str(oid)

    # --- Модули, темы, часы ---
    topic_ids: dict[str, str] = {}
    for module in kit.framework.modules:
        module_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO module (id, program_id, ref, number, title, weight, att_form)
                    VALUES (:mid, :pid, :ref, :number, :title, :weight, :att_form)
                    RETURNING id
                    """
                ),
                {
                    "mid": str(uuid.uuid4()),
                    "pid": program_id,
                    "ref": module.ref,
                    "number": module.number,
                    "title": module.title,
                    "weight": module.weight,
                    "att_form": module.att_form,
                },
            )
        ).scalar_one()
        for t_number, topic in enumerate(module.topics, start=1):
            # locked есть и в PostgreSQL (text[]), и в SQLite (TEXT с JSON):
            # иначе повторный save_kit терял закреплённые ячейки.
            topic_sql = """
                INSERT INTO topic (id, program_id, module_id, ref, number, title, summary, weight, practicality, complexity, control_form, locked)
                VALUES (:tid, :pid, :mid, :ref, :number, :title, :summary, :weight, :practicality, :complexity, :control_form, :locked)
                RETURNING id
            """
            topic_params: dict[str, Any] = {
                "tid": str(uuid.uuid4()),
                "pid": program_id,
                "mid": module_id,
                "ref": topic.ref,
                "number": t_number,
                "title": topic.title,
                "summary": topic.summary,
                "weight": topic.weight,
                "practicality": topic.practicality,
                "complexity": topic.complexity,
                "control_form": topic.control_form,
                "locked": (json.dumps(list(topic.locked), ensure_ascii=False) if uses_sqlite() else list(topic.locked)),
            }
            topic_id = (await session.execute(text(topic_sql), topic_params)).scalar_one()
            topic_ids[topic.ref] = str(topic_id)
            for (activity, mode), hours in _split_distance(topic.workload).items():
                await session.execute(
                    text(
                        f"""
                        INSERT INTO topic_workload (topic_id, activity, mode, hours)
                        VALUES (:tid, {_enum_param("activity", "activity_type")}, {_enum_param("mode", "delivery_mode")}, :hours)
                        """
                    ),
                    {"tid": topic_id, "activity": activity, "mode": mode, "hours": hours},
                )
            for lo_ref in topic.outcome_refs:
                if lo_ref not in outcome_ids:
                    continue
                await session.execute(
                    text("INSERT INTO topic_outcome (topic_id, outcome_id) VALUES (:tid, :oid)"),
                    {"tid": topic_id, "oid": outcome_ids[lo_ref]},
                )

    # --- Календарь ---
    calendar = kit.framework.calendar
    if calendar:
        for session_row in calendar.sessions:
            await session.execute(
                text(
                    f"""
                    INSERT INTO calendar_session (id, program_id, seq, week_no, day_no, topic_id, activity, mode, hours)
                    VALUES (:sid, :pid, :seq, :week, :day, :topic_id, :activity, {_enum_param("mode", "delivery_mode")}, :hours)
                    """
                ),
                {
                    "sid": str(uuid.uuid4()),
                    "pid": program_id,
                    "seq": session_row.seq,
                    "week": session_row.week,
                    "day": session_row.day,
                    "topic_id": topic_ids.get(session_row.topic_ref or ""),
                    "activity": session_row.activity,
                    "mode": session_row.mode,
                    "hours": session_row.hours,
                },
            )

    # --- Содержание: блоки ---
    for block in kit.content.module_programs + kit.content.lecture_plans + kit.content.slides + kit.content.sections:
        await session.execute(
            text(
                f"""
                INSERT INTO content_block (id, program_id, ref, kind, module_id, topic_id, body, stale, generated_by)
                VALUES (:bid, :pid, :ref, :kind, :module_id, :topic_id, {json_param("body")}, :stale, :generated_by)
                """
            ),
            {
                "bid": str(uuid.uuid4()),
                "pid": program_id,
                "ref": block.ref,
                "kind": block.kind,
                "module_id": None,
                "topic_id": topic_ids.get(block.topic_ref or ""),
                "body": json.dumps(block.body, ensure_ascii=False),
                "stale": block.stale,
                "generated_by": block.generated_by,
            },
        )
    # module_ref для блоков рабочих программ
    for block in kit.content.module_programs:
        if block.module_ref:
            await session.execute(
                text(
                    """
                    UPDATE content_block SET module_id = (SELECT id FROM module WHERE program_id = :pid AND ref = :mref)
                    WHERE program_id = :pid AND ref = :bref
                    """
                ),
                {"pid": program_id, "mref": block.module_ref, "bref": block.ref},
            )

    # --- Оценочные средства ---
    for item in kit.content.assessments:
        content_hash = hashlib.sha256(" ".join(item.stem.lower().split()).encode("utf-8")).digest()
        item_id = (
            await session.execute(
                text(
                    f"""
                    INSERT INTO assessment_item
                        (id, program_id, ref, kind, topic_id, module_id, stem, qtype, options, answer_key, rubric, difficulty, content_hash)
                    VALUES
                        (:aid, :pid, :ref, {_enum_param("kind", "assessment_kind")}, :topic_id,
                         (SELECT id FROM module WHERE program_id = :pid AND ref = :mref),
                         :stem, :qtype, {json_param("options")}, {json_param("answer_key")},
                         {json_param("rubric")}, :difficulty, :hash)
                    RETURNING id
                    """
                ),
                {
                    "aid": str(uuid.uuid4()),
                    "pid": program_id,
                    "ref": item.ref,
                    "kind": item.kind,
                    "topic_id": topic_ids.get(item.topic_ref or ""),
                    "mref": item.module_ref,
                    "stem": item.stem,
                    "qtype": item.qtype,
                    "options": json.dumps([o.model_dump() for o in item.options], ensure_ascii=False)
                    if item.options
                    else None,
                    "answer_key": item.answer_key.model_dump_json() if item.answer_key else None,
                    "rubric": json.dumps([c.model_dump() for c in item.rubric], ensure_ascii=False)
                    if item.rubric
                    else None,
                    "difficulty": item.difficulty,
                    "hash": content_hash,
                },
            )
        ).scalar_one()
        for lo_ref in item.outcome_refs:
            if lo_ref in outcome_ids:
                await session.execute(
                    text("INSERT INTO assessment_outcome (item_id, outcome_id) VALUES (:iid, :oid)"),
                    {"iid": item_id, "oid": outcome_ids[lo_ref]},
                )

    # --- Источники ---
    for src in kit.content.sources:
        act_id = None
        if src.normative_act_ref:
            act_id = (
                await session.execute(
                    text("SELECT id FROM normative_act WHERE number = :num LIMIT 1"),
                    {"num": src.normative_act_ref},
                )
            ).scalar_one_or_none()
        source_id = (
            await session.execute(
                text(
                    f"""
                    INSERT INTO source (id, program_id, ref, section, citation, url, isbn, normative_act_id, status, evidence)
                    VALUES (:srcid, :pid, :ref, :section, :citation, :url, :isbn, :act_id,
                            {_enum_param("status", "verify_status")}, {json_param("evidence")})
                    RETURNING id
                    """
                ),
                {
                    "srcid": str(uuid.uuid4()),
                    "pid": program_id,
                    "ref": src.ref,
                    "section": src.section,
                    "citation": src.citation,
                    "url": src.url,
                    "isbn": src.isbn,
                    "act_id": act_id,
                    "status": src.status,
                    "evidence": json.dumps(src.evidence, ensure_ascii=False),
                },
            )
        ).scalar_one()
        for topic_ref in src.topic_refs:
            topic_id = topic_ids.get(topic_ref)
            if topic_id is None:
                continue
            await session.execute(
                text("INSERT INTO source_usage (source_id, topic_id) VALUES (:sid, :tid)"),
                {"sid": source_id, "tid": topic_id},
            )


async def save_report(session: AsyncSession, program_id: str, version: int, report: Report) -> str:
    """Сохранить прогон самопроверки (validation_run + validation_issue)."""
    summary = dict(report.summary)
    summary.setdefault("gaps", report.gaps)
    summary.setdefault("sample_findings", report.sample_findings)
    summary.setdefault("assumptions", report.assumptions)
    run_id = (
        await session.execute(
            text(
                f"""
                INSERT INTO validation_run (id, program_id, version, scope, passed, summary, duration_ms)
                VALUES (:runid, :pid, :version, :scope, :passed, {json_param("summary")}, :duration)
                RETURNING id
                """
            ),
            {
                "runid": str(uuid.uuid4()),
                "pid": program_id,
                "version": version,
                "scope": "kit" if report.summary.get("scope") == "kit" else "framework",
                "passed": report.passed,
                "summary": json.dumps(summary, ensure_ascii=False),
                "duration": report.duration_ms,
            },
        )
    ).scalar_one()
    for issue in report.issues:
        await session.execute(
            text(
                f"""
                INSERT INTO validation_issue (run_id, rule_code, severity, entity_ref, message, fix_hint)
                VALUES (:rid, :rule, {_enum_param("severity", "issue_severity")}, :ref, :message, {json_param("fix")})
                """
            ),
            {
                "rid": run_id,
                "rule": issue.rule_code,
                "severity": issue.severity,
                "ref": issue.entity_ref,
                "message": issue.message,
                "fix": json.dumps(issue.fix_hint, ensure_ascii=False) if issue.fix_hint else None,
            },
        )
    return str(run_id)
