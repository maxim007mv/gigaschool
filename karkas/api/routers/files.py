"""karkas.api.routers.files — загрузка референсов и метаданные (Д4 §6.2).

Лимит 50 МБ, .docx/.pdf/.txt/.md, проверка сигнатуры, извлечение текста в ingest.
"""

from __future__ import annotations

import mimetypes
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api.deps import CurrentPrincipal, enforce_rate_limit, require_roles
from karkas.api.errors import FileTooLarge, Forbidden, NotFound, UnsupportedFile
from karkas.infra import ingest, storage
from karkas.infra.db import get_session
from karkas.infra.repos import files as files_repo
from karkas.infra.storage import LocalStorage, verify_local_presign
from karkas.settings import settings

router = APIRouter(tags=["files"], dependencies=[Depends(enforce_rate_limit)])

# Без JWT: доступ только по HMAC-подписи (как S3 presigned). Нужно для <a href> в UI.
local_storage_router = APIRouter(tags=["files"])


@local_storage_router.get("/local-storage/{bucket}/{key:path}")
async def download_local_storage(
    bucket: str,
    key: str,
    exp: Annotated[int, Query()],
    sig: Annotated[str, Query()],
) -> Response:
    """Скачать файл локального хранилища по подписанной ссылке (dev / LocalStorage)."""
    allowed = {settings.s3_bucket_art, settings.s3_bucket_src}
    if bucket not in allowed:
        raise NotFound("Файл не найден")
    if not verify_local_presign(bucket, key, exp, sig):
        raise Forbidden("Ссылка на файл недействительна или истекла")
    store = storage.get_storage()
    if not isinstance(store, LocalStorage):
        raise NotFound("Локальная раздача недоступна")
    path = store._path(bucket, key)
    if not path.is_file():
        raise NotFound("Файл не найден")
    # Не выходим за корень хранилища (защита от подмены key).
    try:
        path.resolve().relative_to(store.root.resolve())
    except ValueError as exc:
        raise Forbidden("Недопустимый путь") from exc
    data = path.read_bytes()
    mime, _ = mimetypes.guess_type(path.name)
    safe_name = path.name.replace('"', "").replace("\r", "").replace("\n", "") or "download"
    return Response(
        content=data,
        media_type=mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.post("/files", status_code=201)
async def upload_file(
    file: Annotated[UploadFile, File()],
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "expert", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Загрузить референс: валидация типа/размера, ingest, S3, дедупликация по sha256."""
    # Ограничение буферизации: читаем не больше лимита + 1 байт (раньше тело
    # читалось целиком до проверки размера — OOM-вектор на больших файлах).
    data = await file.read(settings.file_max_bytes + 1)
    raw_name = file.filename or "file"
    path = PurePath(raw_name)
    if ".." in path.parts:
        raise UnsupportedFile("Недопустимое имя файла")
    filename = path.name
    if not filename or filename in {".", ".."}:
        raise UnsupportedFile("Недопустимое имя файла")
    try:
        mime, text, meta = ingest.extract(filename, data)
    except (UnsupportedFile, FileTooLarge):
        raise
    except Exception as exc:  # повреждённый docx/pdf с валидной сигнатурой
        raise UnsupportedFile(f"Файл «{filename}» повреждён или имеет неверный формат") from exc

    if principal.is_service or not principal.org_id:
        raise NotFound("Загрузка доступна пользователю организации")

    sha = storage.content_sha256(data)
    # Дедупликация ДО записи в хранилище: повторная загрузка того же файла
    # не оставляет осиротевший объект в S3.
    existing = await files_repo.find_by_sha(session, principal.org_id, sha)
    if existing is not None:
        return {
            "file_id": str(existing["id"]),
            "filename": existing["filename"],
            "mime_type": existing["mime_type"],
            "size_bytes": existing["size_bytes"],
            "extract_meta": existing["extract_meta"],
            "text_preview": (existing["extracted_text"] or "")[:500],
            "deduplicated": True,
        }

    s3_key = f"{principal.org_id}/{sha.hex()}/{filename}"
    storage.get_storage().put("karkas-src", s3_key, data, content_type=mime)
    file_id = await files_repo.create_file(
        session,
        org_id=principal.org_id,
        uploaded_by=principal.user_id,
        filename=filename,
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha,
        s3_key=s3_key,
        extracted_text=text,
        extract_meta=meta,
    )
    await session.commit()
    return {
        "file_id": file_id,
        "filename": filename,
        "mime_type": mime,
        "size_bytes": len(data),
        "extract_meta": meta,
        "text_preview": text[:500],
    }


@router.get("/files/{file_id}")
async def get_file_meta(
    file_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Метаданные файла и результат извлечения (без полного текста)."""
    row = await files_repo.get_file(
        session, file_id, None if principal.is_service else principal.org_id
    )
    if row is None:
        raise NotFound("Файл не найден")
    return {
        "id": str(row["id"]),
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"],
        "extract_meta": row["extract_meta"],
        "s3_key": row["s3_key"],
        "url": storage.get_storage().presign("karkas-src", row["s3_key"]),
    }
