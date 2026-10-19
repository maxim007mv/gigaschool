"""karkas.api.routers.kit — комплект, правки, отчёт, выгрузка (Д4 §6.5)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api import schemas
from karkas.api.deps import CurrentPrincipal, enforce_rate_limit, require_roles
from karkas.api.errors import BadRequest, Forbidden, GateNotPassed, JobInProgress, NotFound
from karkas.api.routers.programs import assert_access, get_program_or_404
from karkas.domain.dependency_graph import closure, unchanged
from karkas.infra import storage
from karkas.infra.db import get_session
from karkas.infra.repos import framework as framework_repo
from karkas.infra.repos import jobs as jobs_repo
from karkas.infra.repos import programs as programs_repo
from karkas.settings import settings

router = APIRouter(prefix="/programs", tags=["kit"], dependencies=[Depends(enforce_rate_limit)])

KIT_OK_STATUSES = ("framework_approved", "kit_review", "kit_updating")


@router.post("/{program_id}/kit:generate", response_model=schemas.KitGenerateOut, status_code=202)
async def generate_kit(
    program_id: str,
    payload: schemas.KitGenerateIn,
    response: Response,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.KitGenerateOut:
    """Сгенерировать комплект (S11–S20). До утверждения каркаса — 409 GATE_NOT_PASSED."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] not in KIT_OK_STATUSES:
        raise GateNotPassed()
    if await jobs_repo.has_active(session, program_id=program_id, kind="kit"):
        raise JobInProgress("Сборка комплекта уже выполняется")

    job_id = await jobs_repo.enqueue(
        session,
        kind="kit",
        program_id=program_id,
        priority=5,
        payload={
            "slides": payload.slides,
            "tests": payload.tests,
            "lms_formats": payload.lms_formats,
            "prev_status": program["status"],
        },
        # Ключ меняется вместе с lock_version: повтор после сбоя — новая задача,
        # двойной клик — дедупликация (плюс проверка has_active выше).
        idempotency_key=f"kit:{program_id}:{program['lock_version']}",
    )
    await programs_repo.set_status(session, program_id=program_id, status="kit_generating")
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="kit.generate",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"job_id": job_id},
    )
    await session.commit()
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return schemas.KitGenerateOut(job_id=job_id, estimate_minutes=12)


@router.get("/{program_id}/kit", response_model=None)
async def get_kit(
    program_id: str,
    response: Response,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> dict | Response:
    """Комплект целиком (KitV1) с ETag снимка версии."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] not in KIT_OK_STATUSES:
        raise GateNotPassed()
    if program["status"] == "framework_approved":
        # Каркас утверждён, но комплект ещё не генерировали. UI по 404
        # показывает кнопку «Сгенерировать комплект».
        raise NotFound("Комплект ещё не собран")
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise NotFound("Комплект ещё не собран")
    etag = f'"v{program["current_version"]}-{program["lock_version"]}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return kit.model_dump(mode="json")


@router.get("/{program_id}/kit/items/{ref}", response_model=schemas.KitItemOut)
async def get_kit_item(
    program_id: str,
    ref: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.KitItemOut:
    """Один элемент комплекта и его связи (для ленивой загрузки на фронте)."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] not in KIT_OK_STATUSES:
        raise GateNotPassed()
    if program["status"] == "framework_approved":
        raise NotFound("Комплект ещё не собран")
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise NotFound("Комплект ещё не собран")

    payload: dict | None = None
    kind = "unknown"
    links: dict = {}

    for m in kit.framework.modules:
        if m.ref == ref:
            payload, kind = m.model_dump(mode="json"), "module"
            links = {"topics": [t.ref for t in m.topics]}
            break
        for t in m.topics:
            if t.ref == ref:
                payload, kind = t.model_dump(mode="json"), "topic"
                links = {
                    "outcomes": t.outcome_refs,
                    "assessments": [a.ref for a in kit.content.assessments if a.topic_ref == ref],
                }
                break
    if payload is None:
        for comp in kit.framework.competencies:
            if comp.ref == ref:
                payload, kind = comp.model_dump(mode="json"), "competency"
                break
            for outcome in comp.outcomes:
                if outcome.ref == ref:
                    payload, kind = outcome.model_dump(mode="json"), "outcome"
                    links = {
                        "topics": [t.ref for t in kit.iter_topics() if ref in t.outcome_refs],
                        "assessments": [a.ref for a in kit.content.assessments if ref in a.outcome_refs],
                    }
                    break
    if payload is None:
        for a in kit.content.assessments:
            if a.ref == ref:
                payload, kind = a.model_dump(mode="json"), "assessment"
                links = {"outcomes": a.outcome_refs}
                break
    if payload is None:
        for s in kit.content.sources:
            if s.ref == ref:
                payload, kind = s.model_dump(mode="json"), "source"
                break
    if payload is None:
        for block in (
            kit.content.module_programs + kit.content.lecture_plans + kit.content.slides + kit.content.sections
        ):
            if block.ref == ref:
                payload, kind = block.model_dump(mode="json"), "content_block"
                break
    if payload is None:
        raise NotFound(f"Элемент {ref} не найден в комплекте")
    return schemas.KitItemOut(ref=ref, kind=kind, payload=payload, links=links)


@router.get("/{program_id}/report", response_model=schemas.ReportOut)
async def get_report(
    program_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.ReportOut:
    """Отчёт автопроверки последней версии."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    report = await framework_repo.load_latest_report(session, program_id)
    if report is None:
        raise NotFound("Отчёт ещё не сформирован")
    return schemas.ReportOut(**report.model_dump())


@router.post("/{program_id}/kit:regenerate", response_model=schemas.KitRegenerateOut, status_code=202)
async def regenerate_kit_part(
    program_id: str,
    payload: schemas.KitRegenerateIn,
    response: Response,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.KitRegenerateOut:
    """Пересобрать выбранные части комплекта (тема/модуль) без изменения утверждённого каркаса."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] not in KIT_OK_STATUSES:
        raise GateNotPassed()
    if await jobs_repo.has_active(session, program_id=program_id, kind="kit_regenerate"):
        raise JobInProgress("Пересборка комплекта уже выполняется")
    job_id = await jobs_repo.enqueue(
        session,
        kind="kit_regenerate",
        program_id=program_id,
        priority=4,
        payload={"target_ref": payload.target_ref, "parts": payload.parts},
        idempotency_key=f"kit_regen:{program_id}:{payload.target_ref}:{':'.join(payload.parts)}:{program['lock_version']}",
    )
    if program["status"] == "kit_review":
        await programs_repo.set_status(session, program_id=program_id, status="kit_updating")
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="kit.regenerate",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"job_id": job_id, "target_ref": payload.target_ref, "parts": payload.parts},
    )
    await session.commit()
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return schemas.KitRegenerateOut(job_id=job_id)


# --- Точечные правки -----------------------------------------------------------


@router.post("/{program_id}/edits", response_model=schemas.EditOut)
async def create_edit(
    program_id: str,
    payload: schemas.EditIn,
    response: Response,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "expert"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.EditOut:
    """Точечная правка: dry_run → план влияния; иначе — фоновая задача."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise NotFound("Каркас ещё не собран")

    try:
        affected = closure(kit, payload.target_ref)
        untouched = unchanged(kit, payload.target_ref)
    except ValueError as exc:
        from karkas.api.errors import EditTargetNotFound

        raise EditTargetNotFound(str(exc)) from exc

    edit_id = programs_repo.new_uuid()
    base_version = int(program["current_version"])
    await session.execute(
        text(
            """
            INSERT INTO edit_request (
                id, program_id, author_id, target_ref, instruction, affected_refs, status, base_version
            )
            VALUES (CAST(:eid AS uuid), CAST(:pid AS uuid), CAST(:author AS uuid), :target, :instruction,
                    :affected, :status, :base)
            """
        ),
        {
            "eid": edit_id,
            "pid": program_id,
            "author": principal.user_id,
            "target": payload.target_ref,
            "instruction": payload.instruction,
            "affected": affected,
            "status": "planned" if payload.dry_run else "running",
            "base": base_version,
        },
    )

    job_id: str | None = None
    if not payload.dry_run:
        job_id = await jobs_repo.enqueue(
            session,
            kind="edit",
            program_id=program_id,
            priority=3,
            payload={
                "edit_id": edit_id,
                "target_ref": payload.target_ref,
                "instruction": payload.instruction,
            },
        )
    await session.commit()
    if job_id:
        response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return schemas.EditOut(
        edit_id=edit_id,
        status="planned" if payload.dry_run else "running",
        affected=affected,
        unchanged=untouched,
        job_id=job_id,
    )


@router.get("/{program_id}/edits/{edit_id}")
async def get_edit(
    program_id: str,
    edit_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT * FROM edit_request
                WHERE id = CAST(:eid AS uuid) AND program_id = CAST(:pid AS uuid)
                """
                ),
                {"eid": edit_id, "pid": program_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFound("Правка не найдена")
    return {
        "edit_id": str(row["id"]),
        "status": row["status"],
        "target_ref": row["target_ref"],
        "affected_refs": row["affected_refs"],
        "base_version": row["base_version"],
        "result_version": row["result_version"],
    }


# --- Выгрузка ------------------------------------------------------------------


@router.post("/{program_id}/exports", status_code=202)
async def create_export(
    program_id: str,
    payload: schemas.ExportIn,
    response: Response,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Формирование выгрузки (S20): docx/pptx/gift/moodle_xml/csv/json/report."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] not in ("kit_review", "kit_updating", "framework_approved"):
        raise GateNotPassed("Выгрузка доступна после сборки комплекта")
    job_id = await jobs_repo.enqueue(
        session,
        kind="export",
        program_id=program_id,
        priority=4,
        payload={"formats": payload.formats},
    )
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="export.create",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"formats": payload.formats, "job_id": job_id},
    )
    await session.commit()
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return {"export_id": job_id, "status": "queued"}


async def _export_status(
    export_id: str,
    principal: CurrentPrincipal,
    session: AsyncSession,
) -> schemas.ExportOut:
    """Статус выгрузки и presigned-ссылки (15 минут)."""
    job = await jobs_repo.get_job(session, export_id)
    if job is None:
        raise NotFound("Выгрузка не найдена")
    if not principal.is_service and job.get("program_org_id") and str(job["program_org_id"]) != principal.org_id:
        raise Forbidden("Выгрузка другой организации")

    if job["status"] != "succeeded":
        return schemas.ExportOut(export_id=export_id, status=job["status"])

    # Файлы ИМЕННО этой выгрузки (artifact.export_id), а не последние по программе.
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT a.kind, a.s3_key, a.version FROM artifact a
                WHERE a.export_id = CAST(:eid AS uuid)
                ORDER BY a.created_at DESC LIMIT 20
                """
                ),
                {"eid": export_id},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        # Совместимость: выгрузки, сделанные до миграции 004 (без export_id).
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT a.kind, a.s3_key, a.version FROM artifact a
                    WHERE a.program_id = CAST(:pid AS uuid)
                    ORDER BY a.created_at DESC LIMIT 20
                    """
                    ),
                    {"pid": job["program_id"]},
                )
            )
            .mappings()
            .all()
        )

    storage_obj = storage.get_storage()
    files = [
        schemas.ExportFileOut(
            kind=r["kind"],
            name=r["s3_key"].rsplit("/", 1)[-1],
            url=storage_obj.presign(settings.s3_bucket_art, r["s3_key"], ttl_s=settings.s3_presign_ttl_s),
            expires_in=settings.s3_presign_ttl_s,
        )
        for r in rows
    ]
    version = rows[0]["version"] if rows else None
    return schemas.ExportOut(export_id=export_id, status="ready", version=version, files=files)


#: Роутер выгрузок с путём /exports/{id} (Д4 §6.2).
exports_router = APIRouter(prefix="/exports", tags=["kit"], dependencies=[Depends(enforce_rate_limit)])


@exports_router.get("/{export_id}", response_model=schemas.ExportOut)
async def get_export_by_id(
    export_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.ExportOut:
    """GET /api/v1/exports/{export_id} — статус выгрузки и ссылки на файлы."""
    return await _export_status(export_id, principal, session)


# --- Актуализация и адаптация (сверх плана, Д4 §5.10–5.11) ----------------------


@router.post("/{program_id}:actualize", status_code=202)
async def actualize_program(
    program_id: str,
    response: Response,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: schemas.ActualizeIn | None = None,
) -> dict:
    """Актуализация старой программы (S22): найти устаревшие темы и инструменты.

    В теле можно передать file_ids ранее загруженных файлов (роль old_program) —
    они прикрепляются к программе до постановки задачи.
    """
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if await jobs_repo.has_active(session, program_id=program_id, kind="actualize"):
        raise JobInProgress("Актуализация уже выполняется")

    file_ids = list(payload.file_ids) if payload else []
    if len(file_ids) > settings.files_per_program_max:
        raise BadRequest(f"Не более {settings.files_per_program_max} файлов на программу")
    from karkas.infra.repos import files as files_repo

    for file_id in file_ids:
        file_row = await files_repo.get_file(session, file_id, program["org_id"])
        if file_row is None:
            raise NotFound(f"Файл {file_id} не найден в организации")
        await files_repo.attach_to_program(session, program_id=program_id, file_id=file_id, role="old_program")

    job_id = await jobs_repo.enqueue(
        session,
        kind="actualize",
        program_id=program_id,
        priority=5,
        payload={"old_program_files": file_ids},
    )
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="program.actualize",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"job_id": job_id},
    )
    await session.commit()
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return {"job_id": job_id, "status": "queued"}


@router.post("/{program_id}:adapt", status_code=202)
async def adapt_program(
    program_id: str,
    payload: dict,
    response: Response,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Адаптация под другую аудиторию или объём (S23) — создаётся программа-потомок."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    target_hours = payload.get("total_hours")
    if target_hours is not None:
        try:
            target_hours = int(target_hours)
        except (TypeError, ValueError) as exc:
            raise BadRequest("Объём часов должен быть целым числом") from exc
        if not (1 <= target_hours <= settings.total_hours_max):
            raise BadRequest(f"Объём должен быть от 1 до {settings.total_hours_max} часов")
    if await jobs_repo.has_active(session, program_id=program_id, kind="adapt"):
        raise JobInProgress("Адаптация уже выполняется")
    job_id = await jobs_repo.enqueue(
        session,
        kind="adapt",
        program_id=program_id,
        priority=5,
        payload={
            "audience": payload.get("audience"),
            "total_hours": int(target_hours) if target_hours else None,
            "form": payload.get("form"),
        },
    )
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="program.adapt",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"job_id": job_id},
    )
    await session.commit()
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return {"job_id": job_id, "status": "queued"}


async def _program_file_ids(session: AsyncSession, program_id: str) -> list[dict]:
    from karkas.infra.repos import files as files_repo

    return await files_repo.program_files(session, program_id)
