"""karkas.api.routers.framework — каркас и Human Gate (Д4 §6.4).

Ключевые инварианты:
- framework:generate невозможен, пока не заполнены обязательные слоты (409 CLARIFICATION_REQUIRED);
- утверждение с несходящимися часами блокируется (409 HOURS_MISMATCH) — и API, и триггером БД;
- правка часов возвращает каркас на переутверждение (триггер workload_reopen);
- каждая правка сохраняет неизменяемый снимок program_version.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api import schemas, services
from karkas.api.deps import CurrentPrincipal, enforce_rate_limit, parse_if_match, require_roles
from karkas.api.errors import (
    BadRequest,
    ClarificationRequired,
    Forbidden,
    GateNotPassed,
    HoursMismatch,
    InfeasibleConstraints,
    JobInProgress,
    NotFound,
    VersionConflict,
)
from karkas.api.routers.programs import assert_access, get_program_or_404
from karkas.domain.framework_ops import OpError, apply_ops
from karkas.domain.hours import HoursInfeasible, rebalance
from karkas.domain.kit import ACTIVITIES, KitV1
from karkas.infra.db import get_session
from karkas.infra.repos import framework as framework_repo
from karkas.infra.repos import jobs as jobs_repo
from karkas.infra.repos import programs as programs_repo
from karkas.infra.repos.framework import LockVersionConflict

router = APIRouter(prefix="/programs", tags=["framework"], dependencies=[Depends(enforce_rate_limit)])


async def _load_kit_or_404(session: AsyncSession, program_id: str) -> KitV1:
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None or not kit.framework.modules:
        raise NotFound("Каркас ещё не собран")
    return kit


@router.post("/{program_id}/framework:generate", status_code=202)
async def generate_framework(
    program_id: str,
    response: Response,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Собрать каркас (S04–S10) — фоновая задача с приоритетом 1."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)

    if program["status"] in ("framework_generating",):
        raise JobInProgress("Каркас уже собирается")
    if program["status"] in ("kit_generating", "kit_review", "kit_updating"):
        raise Forbidden("Комплект уже сгенерирован; верните каркас на доработку для пересборки")

    if not await programs_repo.clarification_allows_framework(session, program_id):
        raise ClarificationRequired()
    if await jobs_repo.has_active(session, program_id=program_id, kind="framework"):
        raise JobInProgress("Задача сборки каркаса уже в очереди")

    # Ключ идемпотентности меняется вместе с lock_version: двойной клик дедуплицируется,
    # повторная генерация после завершения/провала создаёт новую задачу.
    job_id = await jobs_repo.enqueue(
        session,
        kind="framework",
        program_id=program_id,
        priority=1,
        payload={"prev_status": program["status"]},
        idempotency_key=f"framework:{program_id}:{program['lock_version']}",
    )
    await programs_repo.set_status(session, program_id=program_id, status="framework_generating")
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="framework.generate",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"job_id": job_id},
    )
    await session.commit()
    response.headers["Location"] = f"/api/v1/jobs/{job_id}"
    return {
        "job_id": job_id,
        "status": "framework_generating",
        "events": f"/api/v1/programs/{program_id}/events",
    }


@router.get("/{program_id}/framework", response_model=schemas.FrameworkOut)
async def get_framework(
    program_id: str,
    response: Response,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.FrameworkOut:
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    kit = await _load_kit_or_404(session, program_id)
    version = int(program["current_version"])
    lock_version = int(program["lock_version"])
    response.headers["ETag"] = f'"v{version}-{lock_version}"'
    return schemas.FrameworkOut(version=version, status=program["status"], kit=kit)


@router.patch("/{program_id}/framework", response_model=schemas.FrameworkPatchOut)
async def patch_framework(
    program_id: str,
    payload: schemas.FrameworkPatchIn,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> schemas.FrameworkPatchOut:
    """Правки каркаса набором операций; каждая правка → снимок версии и проверка."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] in ("kit_generating",):
        raise Forbidden("Идёт сборка комплекта — правки временно недоступны")
    parse_if_match(if_match, int(program["lock_version"]), required=not principal.is_service)

    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise NotFound("Каркас ещё не собран")
    try:
        new_kit, changes = apply_ops(kit, [op.model_dump() for op in payload.ops])
    except OpError as exc:
        raise NotFound(str(exc)) from exc
    if new_kit.program.final_attestation.hours >= new_kit.program.total_hours:
        raise BadRequest("Часы итоговой аттестации должны быть меньше объёма программы")

    try:
        await framework_repo.save_kit(session, program_id, new_kit, expected_lock_version=int(program["lock_version"]))
    except LockVersionConflict as exc:
        raise VersionConflict(str(exc)) from exc
    version = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason="edit:framework",
        snapshot=new_kit.model_dump(mode="json"),
        created_by=principal.user_id,
    )
    report = await services.run_full_validation(session, kit=new_kit, scope="framework")
    await framework_repo.save_report(session, program_id, version, report)
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="framework.patch",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"ops": len(payload.ops), "changed": len(changes)},
    )
    await session.commit()
    return schemas.FrameworkPatchOut(version=version, checks=services.checks_payload(report), changed=changes)


@router.post("/{program_id}/framework:validate", response_model=schemas.ValidateOut)
async def validate_framework(
    program_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.ValidateOut:
    """Синхронная проверка каркаса (бюджет < 300 мс по чистым правилам)."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise NotFound("Каркас ещё не собран")
    report = await services.run_full_validation(session, kit=kit, scope="framework")
    return schemas.ValidateOut(version=int(program["current_version"]), checks=services.checks_payload(report))


@router.post("/{program_id}/framework:rebalance", response_model=schemas.RebalanceOut)
async def rebalance_framework(
    program_id: str,
    payload: schemas.RebalanceIn,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.RebalanceOut:
    """Пересчёт часов солвером с закреплёнными ячейками (scope — модуль или вся программа)."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    kit = await framework_repo.load_kit(session, program_id)
    if kit is None:
        raise NotFound("Каркас ещё не собран")

    modules, constraints = services.kit_to_module_inputs(kit)
    locked = services.locked_cells_from_kit(kit) if payload.keep_locked else {}

    # scope: пересчитываем только модуль, остальные темы закрепляем на текущих
    # часах — иначе скрытая мутация вне запрошенной области (ревью API S5).
    scope_refs: set[str] | None = None
    if payload.scope:
        module = next((m for m in kit.framework.modules if m.ref == payload.scope), None)
        if module is None:
            raise NotFound(f"Модуль {payload.scope} не найден")
        scope_refs = {t.ref for t in module.topics}
        for topic in kit.iter_topics():
            if topic.ref in scope_refs:
                continue
            cells = locked.setdefault(topic.ref, {})
            for activity in ACTIVITIES:
                cells[activity] = topic.workload.by_activity(activity)

    try:
        plan = rebalance(modules, constraints, locked)
    except HoursInfeasible as exc:
        raise InfeasibleConstraints(str(exc)) from exc

    changed = services.apply_plan_to_kit(kit, plan)
    if scope_refs is not None:
        changed = [c for c in changed if c.get("ref") in scope_refs]

    await framework_repo.save_kit(session, program_id, kit)
    version = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason="rebalance",
        snapshot=kit.model_dump(mode="json"),
        created_by=principal.user_id,
    )
    report = await services.run_full_validation(session, kit=kit, scope="framework")
    await framework_repo.save_report(session, program_id, version, report)
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="framework.rebalance",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"changed": len(changed)},
    )
    await session.commit()
    return schemas.RebalanceOut(version=version, changed=changed, checks=services.checks_payload(report))


@router.post("/{program_id}/framework:approve", response_model=schemas.ApproveOut)
async def approve_framework(
    program_id: str,
    payload: schemas.ApproveIn,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "head"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> schemas.ApproveOut:
    """Human Gate: утвердить каркас. Несходящиеся часы → 409 HOURS_MISMATCH."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] not in ("framework_review", "draft"):
        raise Forbidden(f"Утвердить каркас нельзя из статуса {program['status']}")
    parse_if_match(if_match, int(program["lock_version"]), required=not principal.is_service)

    issues = await programs_repo.hours_issues(session, program_id)
    if issues:
        raise HoursMismatch(issues)

    lock_updated = await programs_repo.set_status(
        session,
        program_id=program_id,
        status="framework_approved",
        approved_by=principal.user_id,
        expected_lock_version=int(program["lock_version"]),
    )
    if lock_updated is None:
        raise VersionConflict("Каркас изменил другой пользователь — обновите страницу и утвердите заново")
    kit = await framework_repo.load_kit(session, program_id)
    version = int(program["current_version"])
    if kit is not None:
        version = await programs_repo.save_version(
            session,
            program_id=program_id,
            reason="framework_approved",
            snapshot=kit.model_dump(mode="json"),
            created_by=principal.user_id,
        )
    approved_at = (
        await session.execute(
            text("SELECT approved_at FROM program WHERE id = CAST(:pid AS uuid)"),
            {"pid": program_id},
        )
    ).scalar_one_or_none()
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="framework.approve",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"comment": payload.comment or ""},
    )
    await session.commit()
    return schemas.ApproveOut(
        status="framework_approved",
        version=version,
        approved_by=principal.user_id,
        approved_at=approved_at.isoformat() if approved_at else None,
    )


@router.post("/{program_id}/framework:reopen", response_model=schemas.ApproveOut)
async def reopen_framework(
    program_id: str,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "head"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.ApproveOut:
    """Вернуть каркас на доработку (запрет генерации комплекта снова действует)."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] not in ("framework_approved", "kit_review", "kit_updating"):
        raise GateNotPassed("Каркас и так не утверждён")
    await programs_repo.reopen(session, program_id=program_id)
    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="framework.reopen",
        actor_id=principal.user_id,
        program_id=program_id,
    )
    await session.commit()
    return schemas.ApproveOut(
        status="framework_review",
        version=int(program["current_version"]),
        approved_by=None,
        approved_at=None,
    )
