"""karkas.infra.repos.usage — учёт токенов, кэш и расчёт эффекта (Д4 §5.13)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
    await session.execute(
        text(
            """
            INSERT INTO llm_call (org_id, program_id, job_id, skill, model, prompt_tokens,
                                  completion_tokens, latency_ms, cost_rub, cache_hit, ok)
            VALUES (:org_id, CAST(:program_id AS uuid), CAST(:job_id AS uuid), :skill, :model,
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
            "cost": cost_rub,
            "cache_hit": cache_hit,
            "ok": ok,
        },
    )


async def program_usage(session: AsyncSession, program_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT * FROM v_program_usage WHERE program_id = CAST(:pid AS uuid)"),
            {"pid": program_id},
        )
    ).mappings().first()
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
    row = (
        await session.execute(
            text(
                """
                UPDATE llm_cache SET hits = hits + 1
                WHERE key_hash = :key AND expires_at > now()
                RETURNING response
                """
            ),
            {"key": key},
        )
    ).scalar_one_or_none()
    return dict(row) if row else None


async def cache_put(
    session: AsyncSession,
    *,
    key: bytes,
    model: str,
    response: dict[str, Any],
    ttl_hours: int,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO llm_cache (key_hash, model, response, expires_at)
            VALUES (:key, :model, CAST(:response AS jsonb), now() + make_interval(hours => :ttl))
            ON CONFLICT (key_hash) DO UPDATE
            SET response = EXCLUDED.response, expires_at = EXCLUDED.expires_at
            """
        ),
        {"key": key, "model": model, "response": json.dumps(response, ensure_ascii=False), "ttl": ttl_hours},
    )


async def purge_expired_cache(session: AsyncSession) -> int:
    result = await session.execute(text("DELETE FROM llm_cache WHERE expires_at <= now()"))
    return int(result.rowcount or 0)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
