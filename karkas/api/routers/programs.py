"""karkas.api.routers.programs — программы, версии, события SSE (Д4 §6.2–6.3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api import schemas
from karkas.api.deps import CurrentPrincipal, Principal, enforce_rate_limit, parse_if_match, require_roles
from karkas.api.errors import BadRequest, Forbidden, JobInProgress, NotFound, Unauthorized, VersionConflict
from karkas.api.sse import bus, format_sse
from karkas.domain.diff import diff_snapshots
from karkas.domain.kit import KitV1
from karkas.infra.db import get_session
from karkas.infra.repos import framework as framework_repo
from karkas.infra.repos import jobs as jobs_repo
from karkas.infra.repos import programs as programs_repo
from karkas.infra.sql_dialect import isoformat_value, uses_sqlite

router = APIRouter(prefix="/programs", tags=["programs"], dependencies=[Depends(enforce_rate_limit)])


async def get_program_or_404(session: AsyncSession, program_id: str, principal: CurrentPrincipal) -> dict:
    """Программа с проверкой доступа (org-scope; сервисный ключ — любой прогон)."""
    org_id = None if principal.is_service else principal.org_id
    program = await programs_repo.get_program(session, program_id, org_id)
    if program is None:
        raise NotFound("Программа не найдена")
    return program


def assert_access(principal: CurrentPrincipal, program: dict) -> None:
    if principal.is_service:
        return
    if str(program["org_id"]) != principal.org_id:
        raise Forbidden("Программа принадлежит другой организации")


async def default_org_and_owner(session: AsyncSession) -> tuple[str, str]:
    """Для сервисных запусков: организация и методист по умолчанию (пилотная инсталляция)."""
    org_id = (
        await session.execute(text("SELECT id FROM organization ORDER BY created_at LIMIT 1"))
    ).scalar_one_or_none()
    if org_id is None:
        raise Forbidden("В инсталляции нет организации")
    owner_id = (
        await session.execute(
            text(
                """
                SELECT id FROM app_user
                WHERE org_id = :org AND role IN ('methodist', 'admin') AND is_active
                ORDER BY created_at LIMIT 1
                """
            ),
            {"org": org_id},
        )
    ).scalar_one_or_none()
    if owner_id is None:
        raise Forbidden("В организации нет активного методиста для сервисного запуска")
    return str(org_id), str(owner_id)


@router.post("", response_model=schemas.ProgramCreateOut, status_code=202)
async def create_program(
    payload: schemas.ProgramCreateIn,
    response: Response,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin", "service"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> schemas.ProgramCreateOut:
    """Создать программу из брифа и файлов, запустить разбор (S01–S03)."""
    if principal.is_service:
        org_id, owner_id = await default_org_and_owner(session)
        actor_id = None
    else:
        if not principal.org_id or not principal.user_id:
            raise Forbidden("Нет организации у пользователя")
        org_id, owner_id = principal.org_id, principal.user_id
        actor_id = principal.user_id

    # Идемпотентность POST (Д4 §6.1): повтор с тем же ключом за 24 ч возвращает
    # ту же программу и задачу, а не создаёт дубль. Advisory-lock сериализует
    # одновременные повторы с одним ключом; ключ задачи уникален на попытку
    # (program_id в ключе), поэтому просроченный (TTL) ключ не «прилипает».
    if idempotency_key:
        if not uses_sqlite():
            # Advisory-lock сериализует одновременные повторы с одним ключом.
            # В SQLite такой функции нет; там достаточно уникального индекса job.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                {"k": f"http-idem:{org_id}:{idempotency_key}"},
            )
        existing = await jobs_repo.find_by_idempotency(session, f"http:{idempotency_key}", org_id=org_id)
        if existing is not None and existing.get("program_id"):
            response.headers["Location"] = f"/api/v1/jobs/{existing['id']}"
            return schemas.ProgramCreateOut(
                program_id=str(existing["program_id"]),
                status=existing.get("program_status") or "draft",
                job_id=str(existing["id"]),
                events=f"/api/v1/programs/{existing['program_id']}/events",
            )

    # Вложения: файл обязан принадлежать организации (иначе IDOR + FK-500).
    from karkas.infra.repos import files as files_repo

    for attach in payload.file_ids:
        file_row = await files_repo.get_file(session, attach.file_id, org_id)
        if file_row is None:
            raise NotFound(f"Файл {attach.file_id} не найден в организации")

    program_id = await programs_repo.create_program(
        session, org_id=org_id, owner_id=owner_id, profile={"brief": payload.brief}
    )
    for attach in payload.file_ids:
        await files_repo.attach_to_program(session, program_id=program_id, file_id=attach.file_id, role=attach.role)

    job_id = await jobs_repo.enqueue(
        session,
        kind="intake",
        program_id=program_id,
        payload={"brief": payload.brief, "auto_questions": payload.options.get("auto_questions", True)},
        priority=1,
        # Уникальный ключ на попытку: дедупликация повторов — выше (find_by_idempotency).
        idempotency_key=(f"http:{idempotency_key}:{program_id}" if idempotency_key else f"intake:{program_id}"),
    )
    await programs_repo.audit(
        session,
        org_id=org_id,
        action="program.create",
        actor_id=actor_id,
        program_id=program_id,
        details={"job_id": job_id},
    )
    await session.commit()
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return schemas.ProgramCreateOut(
        program_id=program_id,
        status="draft",
        job_id=job_id,
        events=f"/api/v1/programs/{program_id}/events",
    )


@router.get("", response_model=schemas.ProgramListOut)
async def list_programs(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
    status: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> schemas.ProgramListOut:
    if principal.is_service or not principal.org_id:
        raise Forbidden("Список доступен пользователю организации")
    page_size = max(1, min(limit, 100))
    if cursor:
        try:
            cursor_ts, _, cursor_id = cursor.partition("|")
            datetime.fromisoformat(cursor_ts)
            uuid.UUID(cursor_id)
        except (ValueError, TypeError) as exc:
            raise BadRequest("Некорректный cursor пагинации") from exc
    try:
        rows = await programs_repo.list_programs(
            session, org_id=principal.org_id, status=status, kind=kind, limit=page_size, cursor=cursor
        )
    except ValueError as exc:
        raise BadRequest(str(exc)) from exc
    items = [
        schemas.ProgramListItem(
            id=str(r["id"]),
            title=r["title"],
            kind=r["kind"],
            total_hours=r["total_hours"],
            status=r["status"],
            updated_at=isoformat_value(r["updated_at"]),
        )
        for r in rows
    ]
    next_cursor = programs_repo.make_cursor(rows[-1]) if len(rows) == page_size else None
    return schemas.ProgramListOut(items=items, next_cursor=next_cursor)


@router.get("/{program_id}", response_model=schemas.ProgramOut)
async def get_program(
    program_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.ProgramOut:
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    return schemas.ProgramOut(
        id=str(program["id"]),
        title=program["title"],
        kind=program["kind"],
        total_hours=program["total_hours"],
        status=program["status"],
        profile=program["profile"] or {},
        constraints=program["constraints"] or {},
        lock_version=program["lock_version"],
    )


@router.patch("/{program_id}", response_model=schemas.ProgramOut)
async def patch_program(
    program_id: str,
    payload: schemas.ProgramPatchIn,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> schemas.ProgramOut:
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    parse_if_match(if_match, int(program["lock_version"]), required=not principal.is_service)

    fields = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        raise BadRequest("Нет полей для обновления")
    if payload.constraints is not None:
        fields["constraints"] = payload.constraints.model_dump()

    hours_changed = any(
        key in fields and fields[key] != program.get(key)
        for key in ("total_hours", "final_att_hours", "final_att_form")
    )

    # Атомарный CAS: правка применяется, только если версия не изменилась.
    new_lock = await programs_repo.update_program(
        session,
        program_id=program_id,
        fields=fields,
        org_id=principal.org_id,
        expected_lock_version=int(program["lock_version"]),
    )
    if new_lock is None:
        raise VersionConflict("Каркас изменил другой пользователь — обновите страницу")

    # Смена объёма/ИА у утверждённой программы возвращает каркас на Human Gate:
    # утверждение с несходящимися часами не должно доживать до комплекта (ЗАД-07).
    if hours_changed and program["status"] in ("framework_approved", "kit_review", "kit_updating"):
        await session.execute(
            text(
                """
                UPDATE program SET status = 'framework_review', approved_by = NULL, approved_at = NULL
                WHERE id = CAST(:pid AS uuid)
                """
            ),
            {"pid": program_id},
        )
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="program.patch",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"fields": sorted(fields.keys()), "hours_changed": hours_changed},
    )
    await session.commit()
    updated = await get_program_or_404(session, program_id, principal)
    return schemas.ProgramOut(
        id=str(updated["id"]),
        title=updated["title"],
        kind=updated["kind"],
        total_hours=updated["total_hours"],
        status=updated["status"],
        profile=updated["profile"] or {},
        constraints=updated["constraints"] or {},
        lock_version=updated["lock_version"],
    )


@router.delete("/{program_id}", status_code=204)
async def archive_program(
    program_id: str,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Архивировать программу (удаление данных не производится)."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    await session.execute(
        text("UPDATE program SET status = 'archived' WHERE id = CAST(:pid AS uuid)"),
        {"pid": program_id},
    )
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="program.archive",
        actor_id=principal.user_id,
        program_id=program_id,
    )
    await session.commit()


# --- Версии -------------------------------------------------------------------


@router.get("/{program_id}/versions")
async def list_versions(
    program_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    rows = await programs_repo.list_versions(session, program_id)
    return {
        "items": [
            schemas.VersionItemOut(
                version=r["version"],
                reason=r["reason"],
                created_at=isoformat_value(r["created_at"]) or "",
                created_by=str(r["created_by"]) if r["created_by"] else None,
            ).model_dump()
            for r in rows
        ]
    }


@router.get("/{program_id}/versions/{version}/diff")
async def version_diff(
    program_id: str,
    version: int,
    to: int,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    left = await programs_repo.get_version(session, program_id, version)
    right = await programs_repo.get_version(session, program_id, to)
    if left is None or right is None:
        raise NotFound("Одна из версий не найдена")
    return diff_snapshots(left["snapshot"], right["snapshot"])


@router.post("/{program_id}/versions/{version}:restore")
async def restore_version(
    program_id: str,
    version: int,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Восстановить версию как новую: снимок становится рабочей копией, каркас — на проверку."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] in ("framework_generating", "kit_generating"):
        raise JobInProgress("Дождитесь завершения генерации, затем восстанавливайте версию")
    snapshot = await programs_repo.get_version(session, program_id, version)
    if snapshot is None:
        raise NotFound("Версия не найдена")

    # Снимок → рабочие таблицы (solver_mode: триггер reopen не будим — часы те же).
    kit = KitV1.model_validate(snapshot["snapshot"])
    await framework_repo.save_kit(session, program_id, kit, update_header=True, solver_mode=True)
    new_version = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason=f"restore:{version}",
        snapshot=snapshot["snapshot"],
        created_by=principal.user_id,
    )
    # Восстановленный каркас проходит Human Gate заново (как после любой правки).
    await session.execute(
        text(
            """
            UPDATE program SET status = 'framework_review', approved_by = NULL, approved_at = NULL
            WHERE id = CAST(:pid AS uuid)
            """
        ),
        {"pid": program_id},
    )
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="version.restore",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"from": version, "to": new_version},
    )
    await session.commit()
    return {"status": "framework_review", "version": new_version, "restored_from": version}


# --- SSE -----------------------------------------------------------------------

#: SSE-роутер без общего лимитера: EventSource не ставит заголовки, токен идёт
#: query-параметром, поэтому лимит применяется внутри эндпоинта по принципалу.
sse_router = APIRouter(prefix="/programs", tags=["programs"])


@sse_router.get("/{program_id}/events")
async def events(
    program_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Query(description="access-токен для EventSource")] = None,
    last_event_id: Annotated[str | None, Query()] = None,
    authorization: Annotated[str | None, Header()] = None,
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Поток событий программы (Д4 §6.7).

    Браузерный EventSource не умеет ставить заголовки, поэтому токен допускается
    query-параметром `?token=…`; `last_event_id` принимается и query-параметром,
    и заголовком `Last-Event-ID` (авто-реконнект EventSource шлёт именно заголовок).
    """
    principal = _sse_principal(authorization, token)
    # Лимит открытых стримов на пользователя (в sse_router нет общего лимитера).
    from karkas.api.deps import check_ip_rate_limit

    check_ip_rate_limit(principal.user_id or "service", rate_per_min=20, prefix="sse")
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    raw_last_id = last_event_id or last_event_id_header
    last_id = int(raw_last_id) if raw_last_id and raw_last_id.isdigit() else None

    async def _stream():
        # Немедленный отклик: клиент видит установленное соединение до первых событий.
        yield ": connected\n\n"
        async for evt in bus.subscribe(program_id, last_id):
            yield format_sse(evt)

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _sse_principal(authorization: str | None, token: str | None) -> Principal:
    """Принципал для SSE: Bearer-заголовок или query-токен (EventSource)."""
    from karkas.api.deps import decode_token

    raw: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1]
    elif token:
        raw = token
    if not raw:
        raise Unauthorized("Нужен access-токен (заголовок Authorization или ?token=)")
    payload = decode_token(raw)
    if payload.get("typ") != "access":
        raise Unauthorized("Нужен access-токен")
    return Principal(
        user_id=payload.get("sub"),
        org_id=payload.get("org"),
        role=payload.get("role", "methodist"),
        email=payload.get("email"),
    )
