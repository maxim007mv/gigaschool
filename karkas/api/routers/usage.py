"""karkas.api.routers.usage — расход токенов, стоимость и эффект (Д4 §5.13).

экономия_ч = T_ручн − T_проверки; T_проверки — активное время методиста
(audit_log от создания до выгрузки минус длительность автосборки).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api import schemas
from karkas.api.deps import CurrentPrincipal, enforce_rate_limit
from karkas.api.routers.programs import assert_access, get_program_or_404
from karkas.infra.db import get_session
from karkas.infra.repos import usage as usage_repo
from karkas.infra.sql_dialect import uses_sqlite, uuid_param

router = APIRouter(
    prefix="/programs", tags=["usage"], dependencies=[Depends(enforce_rate_limit)]
)


async def _active_hours(session: AsyncSession, program_id: str) -> float:
    """Активное время методиста: от первого события до последнего минус автосборка."""
    if uses_sqlite():
        row = (
            await session.execute(
                text(
                    """
                    SELECT
                        (julianday(max(created_at)) - julianday(min(created_at))) * 24.0 AS span_h,
                        COALESCE((
                            SELECT sum(
                                (julianday(COALESCE(finished_at, datetime('now')))
                                 - julianday(created_at)) * 24.0
                            )
                            FROM job WHERE program_id = :pid AND status = 'succeeded'
                        ), 0) AS generation_h
                    FROM audit_log
                    WHERE program_id = :pid
                    """
                ),
                {"pid": program_id},
            )
        ).mappings().first()
    else:
        pid = uuid_param("pid")
        row = (
            await session.execute(
                text(
                    f"""
                    SELECT
                        EXTRACT(EPOCH FROM (max(created_at) - min(created_at))) / 3600.0 AS span_h,
                        COALESCE((
                            SELECT sum(EXTRACT(EPOCH FROM (COALESCE(finished_at, now()) - created_at))) / 3600.0
                            FROM job WHERE program_id = {pid} AND status = 'succeeded'
                        ), 0) AS generation_h
                    FROM audit_log
                    WHERE program_id = {pid}
                    """
                ),
                {"pid": program_id},
            )
        ).mappings().first()
    if row is None or row["span_h"] is None:
        return 0.0
    return max(0.0, float(row["span_h"]) - float(row["generation_h"] or 0))


async def _first_time_framework_approval(session: AsyncSession, program_id: str) -> bool | None:
    """True, если каркас утверждён с первой попытки (без framework.reopen)."""
    pid_sql = ":pid" if uses_sqlite() else uuid_param("pid")
    rows = (
        await session.execute(
            text(
                f"""
                SELECT action FROM audit_log
                WHERE program_id = {pid_sql}
                  AND action IN ('framework.approve', 'framework.reopen')
                """
            ),
            {"pid": program_id},
        )
    ).scalars().all()
    if not rows:
        return None
    if "framework.approve" not in rows:
        return None
    return rows.count("framework.approve") == 1 and "framework.reopen" not in rows


@router.get("/{program_id}/usage", response_model=schemas.UsageOut)
async def get_usage(
    program_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.UsageOut:
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    active_hours = await _active_hours(session, program_id)
    baseline = 2.0 * 40.0 * 0.5
    savings = usage_repo.compute_savings_hours(active_hours=active_hours)
    ftar = await _first_time_framework_approval(session, program_id)
    usage = await usage_repo.program_usage(session, program_id)
    common = {
        "program_id": program_id,
        "savings_hours": savings,
        "methodologist_active_hours": round(active_hours, 2),
        "manual_baseline_hours": baseline,
        "first_time_framework_approval": ftar,
    }
    if usage is None:
        return schemas.UsageOut(**common)

    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return schemas.UsageOut(
        **common,
        calls=int(usage.get("calls") or 0),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tokens=prompt_tokens + completion_tokens,
        cost_rub=Decimal(str(usage.get("cost_rub") or 0)),
        cache_hit_pct=float(usage.get("cache_hit_pct") or 0),
        p95_latency_ms=float(usage["p95_latency_ms"]) if usage.get("p95_latency_ms") is not None else None,
    )
