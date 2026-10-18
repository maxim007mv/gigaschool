"""karkas.api.routers.registry — реестры НПА и профстандартов (Д4 §6.2).

Код или номер попадает в программу только из этих реестров (AD-4).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api.deps import CurrentPrincipal, enforce_rate_limit
from karkas.api.errors import NotFound
from karkas.infra.db import get_session
from karkas.infra.repos import registry as registry_repo

router = APIRouter(prefix="/registry", tags=["registry"], dependencies=[Depends(enforce_rate_limit)])


@router.get("/prof-standards")
async def search_prof_standards(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=2, max_length=200)] = "",
    limit: int = 10,
) -> dict:
    """Поиск действующих профстандартов по названию или коду."""
    items = await registry_repo.search_prof_standards(session, q, limit=min(limit, 50))
    return {"items": items}


@router.get("/prof-standards/{code}/labor-functions")
async def get_labor_functions(
    code: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Трудовые функции профстандарта (код вида C/14.6)."""
    standard = await registry_repo.get_prof_standard(session, code)
    if standard is None:
        raise NotFound(f"Профстандарт {code} не найден в реестре")
    functions = await registry_repo.labor_functions(session, code)
    return {
        "code": code,
        "title": standard["title"],
        "status": standard["status"],
        "labor_functions": functions,
    }


@router.get("/normative-acts")
async def list_normative_acts(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
    kind: Annotated[str | None, Query(pattern="^(dpp_pk|dop)$")] = None,
    on_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> dict:
    """Действующие НПА на дату (по умолчанию — сегодня)."""
    items = await registry_repo.normative_acts(session, program_kind=kind, on_date=on_date)
    return {"items": items, "on_date": on_date}
