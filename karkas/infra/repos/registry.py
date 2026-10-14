"""karkas.infra.repos.registry — поиск по реестрам (НПА, профстандарты, ТФ, сервисы).

Код или номер попадает в программу только из этих реестров (AD-4, ЗАД-22).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def search_prof_standards(session: AsyncSession, q: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Поиск действующих профстандартов: pg_trgm по названию + код."""
    rows = (
        await session.execute(
            text(
                """
                SELECT code, title, order_number, order_date, reg_number,
                       round(similarity(title_trgm, lower(:q))::numeric, 2) AS sim
                FROM prof_standard
                WHERE status = 'active'
                  AND (title_trgm % lower(:q) OR code ILIKE :q_like OR lower(title) LIKE :q_like)
                ORDER BY sim DESC NULLS LAST, code
                LIMIT :limit
                """
            ),
            {"q": q, "q_like": f"%{q}%", "limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_prof_standard(session: AsyncSession, code: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT * FROM prof_standard WHERE code = :code"),
            {"code": code},
        )
    ).mappings().first()
    return dict(row) if row else None


async def labor_functions(session: AsyncSession, prof_standard_code: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT lf.code, lf.title, lf.otf_code, lf.qual_level, lf.actions, lf.skills, lf.knowledge
                FROM labor_function lf
                JOIN prof_standard ps ON ps.id = lf.prof_standard_id
                WHERE ps.code = :code
                ORDER BY lf.code
                """
            ),
            {"code": prof_standard_code},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def normative_acts(
    session: AsyncSession,
    *,
    program_kind: str | None = None,
    on_date: str | date | None = None,
) -> list[dict[str, Any]]:
    """Действующие НПА на дату (по умолчанию — сегодня), опционально по виду программы."""
    from datetime import date as date_type

    parsed_date = date_type.fromisoformat(on_date) if isinstance(on_date, str) else on_date
    sql = """
        SELECT id, kind, issuer, number, signed_on, title, valid_from, valid_to, official_url, applies_to
        FROM normative_act
        WHERE coalesce(valid_from, '-infinity'::date) <= coalesce(CAST(:on_date AS date), CURRENT_DATE)
          AND coalesce(valid_to, 'infinity'::date) >= coalesce(CAST(:on_date AS date), CURRENT_DATE)
    """
    params: dict[str, Any] = {"on_date": parsed_date}
    if program_kind:
        sql += " AND :kind = ANY(applies_to)"
        params["kind"] = program_kind
    sql += " ORDER BY signed_on DESC"
    rows = (await session.execute(text(sql), params)).mappings().all()
    return [dict(r) for r in rows]


async def get_labor_function_id(
    session: AsyncSession, *, prof_standard_code: str, lf_code: str
) -> str | None:
    row = (
        await session.execute(
            text(
                """
                SELECT lf.id FROM labor_function lf
                JOIN prof_standard ps ON ps.id = lf.prof_standard_id
                WHERE ps.code = :ps AND lf.code = :lf LIMIT 1
                """
            ),
            {"ps": prof_standard_code, "lf": lf_code},
        )
    ).scalar_one_or_none()
    return str(row) if row else None


async def search_services(session: AsyncSession, q: str, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT name, category, available_ru, lifecycle, latest_version, checked_on, evidence_url
                FROM service_catalog
                WHERE name ILIKE :q_like
                ORDER BY name LIMIT :limit
                """
            ),
            {"q_like": f"%{q}%", "limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
