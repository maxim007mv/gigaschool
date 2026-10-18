"""karkas.api.routers.agent — единый эндпоинт автопрогонов (Д4 §6.6).

POST /api/v1/agent/run: бриф → (уточняющие вопросы) → каркас → Human Gate
(auto_approve для автопрогона) → комплект → выгрузки. Синхронный режим (wait=true,
до 20 минут) или асинхронный (202 + run_id). Эндпоинт использует те же навыки
S01–S23, что и UI (AD-7).
"""

from __future__ import annotations

import contextlib
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api import schemas
from karkas.api.deps import CurrentPrincipal, enforce_rate_limit, require_roles
from karkas.api.errors import Forbidden, NotFound
from karkas.api.routers.programs import default_org_and_owner
from karkas.infra.db import get_session

router = APIRouter(prefix="/agent", tags=["agent"], dependencies=[Depends(enforce_rate_limit)])


async def _enqueue_agent_run(session: AsyncSession, run_id: str, program_id: str) -> str:
    from karkas.agent.pipeline import enqueue_agent_run

    return await enqueue_agent_run(session, run_id=run_id, program_id=program_id)


async def _enqueue_agent_run_background(run_id: str, program_id: str) -> None:
    """Фоновая постановка прогона и исполнение в том же процессе, если воркер не запущен."""
    from karkas.agent.pipeline import wait_agent_run
    from karkas.infra.db import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        job_id = await _enqueue_agent_run(session, run_id, program_id)
        await session.commit()
    async with factory() as session:
        try:
            await wait_agent_run(session, run_id, job_id)
        except TimeoutError:
            return


async def _dispatch_agent_run(session: AsyncSession, run_id: str, program_id: str, *, wait: bool) -> None:
    """Запуск прогона через очередь воркера (wait=true ждёт завершения job)."""
    from karkas.agent.pipeline import wait_agent_run

    job_id = await _enqueue_agent_run(session, run_id, program_id)
    await session.commit()
    if wait:
        with contextlib.suppress(TimeoutError):
            await wait_agent_run(session, run_id, job_id)


@router.post("/run", response_model=schemas.AgentRunOut)
async def agent_run(
    payload: schemas.AgentRunIn,
    background: BackgroundTasks,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("service", "methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> schemas.AgentRunOut:
    """Запуск агента на бриф или продолжение прогона (run_id + answers)."""
    from karkas.agent.pipeline import (
        append_answers,
        create_run,
        find_run_by_idempotency,
        run_result,
    )

    if payload.run_id:
        # Продолжение: ответы на уточняющие вопросы (проверяем принадлежность прогона).
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT ar.*, p.org_id AS program_org_id FROM agent_run ar
                    JOIN program p ON p.id = ar.program_id
                    WHERE ar.id = CAST(:rid AS uuid)
                    """
                    ),
                    {"rid": payload.run_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise NotFound("Прогон не найден")
        if not principal.is_service and str(row["program_org_id"]) != principal.org_id:
            raise Forbidden("Прогон другой организации")
        if row["status"] not in ("needs_input", "running"):
            return schemas.AgentRunOut(
                run_id=payload.run_id,
                status=row["status"],
                program_id=str(row["program_id"]),
                detail="Прогон уже завершён",
            )
        if payload.answers:
            await append_answers(
                session, run_id=payload.run_id, program_id=str(row["program_id"]), answers=payload.answers
            )
        await session.commit()
        if payload.wait:
            await _dispatch_agent_run(session, payload.run_id, str(row["program_id"]), wait=True)
            return await run_result(session, payload.run_id)
        await _enqueue_agent_run(session, payload.run_id, str(row["program_id"]))
        await session.commit()
        return schemas.AgentRunOut(run_id=payload.run_id, status="running", program_id=str(row["program_id"]))

    # Новый прогон.
    if not payload.request or len(payload.request.strip()) < 10:
        raise Forbidden("Нужен текст запроса (минимум 10 символов)")
    if payload.auto_approve and not principal.is_service:
        # Human Gate в UI всегда ручной: автоутверждение — только для сервисных
        # автопрогонов тестовой платформы (Д4 §6.6).
        raise Forbidden("auto_approve доступен только сервисным ключам автопрогонов")

    if principal.is_service:
        org_id, owner_id = await default_org_and_owner(session)
    else:
        if not principal.org_id or not principal.user_id:
            raise Forbidden("Нет организации у пользователя")
        org_id, owner_id = principal.org_id, principal.user_id

    # Идемпотентность автопрогонов (Д1 §14): повтор с тем же ключом не создаёт дубль.
    if idempotency_key:
        existing_run_id = await find_run_by_idempotency(session, idempotency_key, org_id=org_id)
        if existing_run_id:
            return await run_result(session, existing_run_id)

    run = await create_run(
        session,
        org_id=org_id,
        owner_id=owner_id,
        request_text=payload.request,
        mode=payload.mode,
        auto_approve=payload.auto_approve,
        formats=payload.formats,
        attachments=payload.attachments,
        api_key_id=None,
        idempotency_key=idempotency_key,
    )
    await session.commit()

    if payload.wait:
        await _dispatch_agent_run(session, run["run_id"], run["program_id"], wait=True)
        return await run_result(session, run["run_id"])
    background.add_task(_enqueue_agent_run_background, run["run_id"], run["program_id"])
    return schemas.AgentRunOut(run_id=run["run_id"], status="running", program_id=run["program_id"])


@router.get("/runs/{run_id}", response_model=schemas.AgentRunOut)
async def get_run(
    run_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.AgentRunOut:
    """Результат запуска (для асинхронного режима)."""
    from karkas.agent.pipeline import run_result

    row = (
        (
            await session.execute(
                text(
                    """
                SELECT ar.*, p.org_id AS program_org_id FROM agent_run ar
                JOIN program p ON p.id = ar.program_id
                WHERE ar.id = CAST(:rid AS uuid)
                """
                ),
                {"rid": run_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFound("Прогон не найден")
    if not principal.is_service and str(row["program_org_id"]) != principal.org_id:
        raise Forbidden("Прогон другой организации")
    return await run_result(session, run_id)
