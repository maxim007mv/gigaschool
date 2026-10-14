"""karkas.api.routers.jobs — статус и отмена фоновых задач (Д4 §6.2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api import schemas
from karkas.api.deps import CurrentPrincipal, enforce_rate_limit
from karkas.api.errors import Forbidden, NotFound
from karkas.infra.db import get_session
from karkas.infra.repos import jobs as jobs_repo

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(enforce_rate_limit)])


async def _get_job_or_404(session: AsyncSession, job_id: str, principal: CurrentPrincipal) -> dict:
    job = await jobs_repo.get_job(session, job_id)
    if job is None:
        raise NotFound("Задача не найдена")
    if principal.is_service:
        return job
    if job.get("program_org_id") is None:
        # Служебные задачи без программы (maintenance и т. п.) — только сервисным ключам.
        raise Forbidden("Задача недоступна пользователям")
    if str(job["program_org_id"]) != principal.org_id:
        raise Forbidden("Задача другой организации")
    return job


@router.get("/{job_id}", response_model=schemas.JobOut)
async def get_job(
    job_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.JobOut:
    """Статус, прогресс и ошибки фоновой задачи."""
    job = await _get_job_or_404(session, job_id, principal)
    return schemas.JobOut(
        id=str(job["id"]),
        kind=job["kind"],
        status=job["status"],
        progress=job["progress"] or {},
        attempts=job["attempts"],
        error=job["error"],
    )


@router.post("/{job_id}:cancel", status_code=202)
async def cancel_job(
    job_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Отменить задачу. Если она держала программу в *_generating — статус откатывается."""
    job = await _get_job_or_404(session, job_id, principal)
    cancelled = await jobs_repo.cancel(session, job_id)
    if not cancelled:
        raise Forbidden(f"Задачу из статуса {job['status']} отменить нельзя")

    # Выход из dead-end: отменённая генерация не оставляет программу залипшей.
    payload = job.get("payload") or {}
    expected = {
        "framework": ("framework_generating",),
        "kit": ("kit_generating",),
    }.get(job["kind"])
    if expected and payload.get("prev_status") and job.get("program_id"):
        await jobs_repo.restore_program_status(
            session,
            program_id=str(job["program_id"]),
            prev_status=str(payload["prev_status"]),
            expected_current=expected,
        )
    await session.commit()
    return {"job_id": job_id, "status": "cancelled"}
