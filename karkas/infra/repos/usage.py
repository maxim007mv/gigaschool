"""karkas.infra.repos.usage — учёт токенов, кэш и расчёт эффекта (Д4 §5.13)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.infra.sql_dialect import cache_hit_pct_expr, json_param, run_after_hours, uses_sqlite, uuid_param


async def record_llm_call(
    session: AsyncSession,
    *,
    org_id: str,
    skill: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    ok: bool,
    program_id: str | None = None,
    job_id: str | None = None,
    cost_rub: Decimal = Decimal("0"),
    cache_hit: bool = False,
) -> None:
    pid = uuid_param("program_id")
    jid = uuid_param("job_id")
    await session.execute(
        text(
            f"""
            INSERT INTO llm_call (org_id, program_id, job_id, skill, model, prompt_tokens,
                                  completion_tokens, latency_ms, cost_rub, cache_hit, ok)
            VALUES (:org_id, {pid}, {jid}, :skill, :model,
                    :pt, :ct, :latency, :cost, :cache_hit, :ok)
            """
        ),
        {
            "org_id": org_id,
            "program_id": program_id,
            "job_id": job_id,
            "skill": skill,
            "model": model,
            "pt": prompt_tokens,
            "ct": completion_tokens,
            "latency": latency_ms,
            # sqlite3 не умеет Decimal — в lite пишем float, в PostgreSQL оставляем Decimal.
            "cost": float(cost_rub) if uses_sqlite() else cost_rub,
            "cache_hit": (1 if cache_hit else 0) if uses_sqlite() else bool(cache_hit),
            "ok": (1 if ok else 0) if uses_sqlite() else bool(ok),
        },
    )


async def org_spent_today(session: AsyncSession, org_id: str) -> Decimal:
    """Сумма cost_rub по организации за текущие сутки (сброс по МСК, как у хаба)."""
    if uses_sqlite():
        sql = """
            SELECT coalesce(sum(cost_rub), 0) FROM llm_call
            WHERE org_id = :org
              AND date(created_at, '+3 hours') = date('now', '+3 hours')
        """
        params: dict[str, Any] = {"org": org_id}
    else:
        sql = """
            SELECT coalesce(sum(cost_rub), 0) FROM llm_call
            WHERE org_id = CAST(:org AS uuid)
              AND created_at >= date_trunc('day', now() AT TIME ZONE 'Europe/Moscow') AT TIME ZONE 'Europe/Moscow'
        """
        params = {"org": org_id}
    row = (await session.execute(text(sql), params)).scalar_one_or_none()
    return Decimal(str(row or 0))


async def program_usage(session: AsyncSession, program_id: str) -> dict[str, Any] | None:
    if uses_sqlite():
        row = (
            (
                await session.execute(
                    text(
                        f"""
                    SELECT :pid AS program_id, count(*) AS calls,
                           sum(prompt_tokens) AS prompt_tokens,
                           sum(completion_tokens) AS completion_tokens,
                           sum(cost_rub) AS cost_rub,
                           {cache_hit_pct_expr()} AS cache_hit_pct,
                           NULL AS p95_latency_ms
                    FROM llm_call WHERE program_id = :pid
                    """
                    ),
                    {"pid": program_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None or int(row["calls"] or 0) == 0:
            return None
        return dict(row)
    pid = uuid_param("pid")
    row = (
        (
            await session.execute(
                text(f"SELECT * FROM v_program_usage WHERE program_id = {pid}"),
                {"pid": program_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def compute_savings_hours(
    *,
    manual_weeks: float = 2.0,
    utilization: float = 0.5,
    active_hours: float = 0.0,
    hours_per_week: float = 40.0,
) -> float:
    """экономия_ч = T_ручн − T_проверки (Д4 §5.13). Параметры настраиваются организацией."""
    manual_hours = manual_weeks * hours_per_week * utilization
    return round(max(0.0, manual_hours - active_hours), 1)


# --- Кэш ответов моделей (llm_cache) ----------------------------------------


def cache_key(model: str, prompt_version: str, messages: list[dict[str, Any]], params: dict[str, Any]) -> bytes:
    """sha256(model|prompt_version|messages|params) — Д1 §7."""
    payload = json.dumps(
        {"model": model, "prompt_version": prompt_version, "messages": messages, "params": params},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).digest()


async def cache_get(session: AsyncSession, key: bytes) -> dict[str, Any] | None:
    now = "datetime('now')" if uses_sqlite() else "now()"
    row = (
        await session.execute(
            text(
                f"""
                UPDATE llm_cache SET hits = hits + 1
                WHERE key_hash = :key AND expires_at > {now}
                RETURNING response
                """
            ),
            {"key": key},
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if isinstance(row, str):
        return json.loads(row)
    return dict(row) if isinstance(row, dict) else json.loads(str(row))


async def cache_put(
    session: AsyncSession,
    *,
    key: bytes,
    model: str,
    response: dict[str, Any],
    ttl_hours: int,
) -> None:
    resp = json_param("response")
    expires = run_after_hours()
    await session.execute(
        text(
            f"""
            INSERT INTO llm_cache (key_hash, model, response, expires_at)
            VALUES (:key, :model, {resp}, {expires})
            ON CONFLICT (key_hash) DO UPDATE
            SET response = excluded.response, expires_at = excluded.expires_at
            """
        ),
        {"key": key, "model": model, "response": json.dumps(response, ensure_ascii=False), "ttl": ttl_hours},
    )


async def purge_expired_cache(session: AsyncSession) -> int:
    now = "datetime('now')" if uses_sqlite() else "now()"
    result = await session.execute(text(f"DELETE FROM llm_cache WHERE expires_at <= {now}"))
    return int(getattr(result, "rowcount", 0) or 0)


def utcnow() -> datetime:
    return datetime.now(UTC)
