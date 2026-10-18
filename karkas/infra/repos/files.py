"""karkas.infra.repos.files — файлы (file_object) и привязка к программам.

Дедупликация по (org_id, sha256); лимит 50 МБ проверяется в API до S3-загрузки.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_file(
    session: AsyncSession,
    *,
    org_id: str,
    uploaded_by: str | None,
    filename: str,
    mime_type: str,
    size_bytes: int,
    sha256: bytes,
    s3_key: str,
    extracted_text: str | None = None,
    extract_meta: dict[str, Any] | None = None,
) -> str:
    """Создать запись файла; при дубликате (org_id, sha256) вернуть существующий id."""
    row = (
        await session.execute(
            text(
                """
                INSERT INTO file_object (org_id, uploaded_by, filename, mime_type, size_bytes,
                                         sha256, s3_key, extracted_text, extract_meta)
                VALUES (:org_id, CAST(:uploaded_by AS uuid), :filename, :mime, :size, :sha,
                        :s3_key, :text, CAST(:meta AS jsonb))
                ON CONFLICT (org_id, sha256) DO NOTHING
                RETURNING id
                """
            ),
            {
                "org_id": org_id,
                "uploaded_by": uploaded_by,
                "filename": filename,
                "mime": mime_type,
                "size": size_bytes,
                "sha": sha256,
                "s3_key": s3_key,
                "text": extracted_text,
                "meta": json.dumps(extract_meta or {}, ensure_ascii=False),
            },
        )
    ).scalar_one_or_none()
    if row is not None:
        return str(row)
    existing = (
        await session.execute(
            text("SELECT id FROM file_object WHERE org_id = :org_id AND sha256 = :sha"),
            {"org_id": org_id, "sha": sha256},
        )
    ).scalar_one()
    return str(existing)


async def get_file(session: AsyncSession, file_id: str, org_id: str | None = None) -> dict[str, Any] | None:
    sql = "SELECT * FROM file_object WHERE id = CAST(:fid AS uuid)"
    params: dict[str, Any] = {"fid": file_id}
    if org_id:
        sql += " AND org_id = :org_id"
        params["org_id"] = org_id
    row = (await session.execute(text(sql), params)).mappings().first()
    return dict(row) if row else None


async def find_by_sha(session: AsyncSession, org_id: str, sha256: bytes) -> dict[str, Any] | None:
    """Найти уже загруженный файл по содержимому (дедупликация до записи в S3)."""
    row = (
        (
            await session.execute(
                text("SELECT * FROM file_object WHERE org_id = :org_id AND sha256 = :sha"),
                {"org_id": org_id, "sha": sha256},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def attach_to_program(
    session: AsyncSession,
    *,
    program_id: str,
    file_id: str,
    role: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO program_file (program_id, file_id, role)
            VALUES (CAST(:pid AS uuid), CAST(:fid AS uuid), :role)
            ON CONFLICT (program_id, file_id) DO UPDATE SET role = EXCLUDED.role
            """
        ),
        {"pid": program_id, "fid": file_id, "role": role},
    )


async def program_files(session: AsyncSession, program_id: str) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT pf.role, fo.id, fo.filename, fo.mime_type, fo.extracted_text IS NOT NULL AS has_text
                FROM program_file pf JOIN file_object fo ON fo.id = pf.file_id
                WHERE pf.program_id = CAST(:pid AS uuid)
                ORDER BY fo.filename
                """
                ),
                {"pid": program_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def ocr_required(meta: dict[str, Any] | None) -> bool:
    """PDF без извлечённого текста → требуется OCR или предупреждение (Д4 §10)."""
    return bool(meta and meta.get("pages") and meta.get("chars", 0) == 0)
