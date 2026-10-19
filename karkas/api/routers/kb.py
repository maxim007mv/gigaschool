"""karkas.api.routers.kb — база знаний организации для RAG (Д4 §6.2, Д2 §5.1).

Документы (локальные акты, шаблоны, ФГОС) привязываются к file_object и
разбираются на фрагменты (kb_chunk) фоновой задачей. Область применения —
виды программ (dpp_pk/dop) или NULL = все.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api.deps import CurrentPrincipal, enforce_rate_limit, require_roles
from karkas.api.errors import Forbidden, NotFound
from karkas.infra.db import get_session
from karkas.infra.repos import files as files_repo
from karkas.infra.repos import jobs as jobs_repo
from karkas.infra.sql_dialect import isoformat_value, uses_sqlite

router = APIRouter(prefix="/kb", tags=["kb"], dependencies=[Depends(enforce_rate_limit)])

DocRole = Literal["template", "sample_program", "local_act", "prof_standard", "fgos", "other"]


class KbDocumentIn(BaseModel):
    file_id: str
    title: str = Field(min_length=1, max_length=500)
    doc_role: DocRole
    applies_to: list[Literal["dpp_pk", "dop"]] | None = None


@router.post("/documents", status_code=201)
async def add_document(
    payload: KbDocumentIn,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Добавить документ в базу знаний организации и запустить разбор на фрагменты."""
    if uses_sqlite():
        raise Forbidden("База знаний доступна только при подключённом PostgreSQL (не в lite-режиме)")
    if principal.is_service or not principal.org_id:
        raise Forbidden("База знаний доступна пользователю организации")
    file_row = await files_repo.get_file(session, payload.file_id, principal.org_id)
    if file_row is None:
        raise NotFound("Файл не найден в организации")

    doc_id = (
        await session.execute(
            text(
                """
                INSERT INTO kb_document (org_id, file_id, title, doc_role, applies_to)
                VALUES (:org_id, CAST(:fid AS uuid), :title, :role, CAST(:applies AS program_kind[]))
                RETURNING id
                """
            ),
            {
                "org_id": principal.org_id,
                "fid": payload.file_id,
                "title": payload.title,
                "role": payload.doc_role,
                "applies": payload.applies_to,
            },
        )
    ).scalar_one()
    job_id = await jobs_repo.enqueue(
        session,
        kind="maintenance",
        program_id=None,
        priority=9,
        payload={"kb_document_id": str(doc_id), "org_id": principal.org_id},
    )
    await session.commit()
    return {"doc_id": str(doc_id), "job_id": job_id, "status": "chunking_queued"}


@router.get("/documents")
async def list_documents(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if uses_sqlite():
        raise Forbidden("База знаний доступна только при подключённом PostgreSQL (не в lite-режиме)")
    if principal.is_service or not principal.org_id:
        raise Forbidden("База знаний доступна пользователю организации")
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT d.id, d.title, d.doc_role, d.applies_to, d.is_active, d.created_at,
                       f.filename, f.size_bytes,
                       (SELECT count(*) FROM kb_chunk c WHERE c.file_id = d.file_id) AS chunks
                FROM kb_document d JOIN file_object f ON f.id = d.file_id
                WHERE d.org_id = :org_id
                ORDER BY d.created_at DESC
                """
                ),
                {"org_id": principal.org_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        "items": [
            {
                "doc_id": str(r["id"]),
                "title": r["title"],
                "doc_role": r["doc_role"],
                "applies_to": r["applies_to"],
                "is_active": r["is_active"],
                "filename": r["filename"],
                "size_bytes": r["size_bytes"],
                "chunks": r["chunks"],
                "created_at": isoformat_value(r["created_at"]) or "",
            }
            for r in rows
        ]
    }


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: str,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Удалить документ базы знаний (только администратор организации)."""
    if uses_sqlite():
        raise Forbidden("База знаний доступна только при подключённом PostgreSQL (не в lite-режиме)")
    if principal.is_service or not principal.org_id:
        raise Forbidden("База знаний доступна администратору организации")
    file_id = (
        await session.execute(
            text("SELECT file_id FROM kb_document WHERE id = CAST(:did AS uuid) AND org_id = :org_id"),
            {"did": doc_id, "org_id": principal.org_id},
        )
    ).scalar_one_or_none()
    if file_id is None:
        raise NotFound("Документ не найден")
    # Чанки документа (RAG) удаляем вместе с записью — иначе остаются сироты.
    await session.execute(
        text("DELETE FROM kb_chunk WHERE file_id = CAST(:fid AS uuid)"),
        {"fid": file_id},
    )
    await session.execute(
        text("DELETE FROM kb_document WHERE id = CAST(:did AS uuid) AND org_id = :org_id"),
        {"did": doc_id, "org_id": principal.org_id},
    )
    await session.commit()
