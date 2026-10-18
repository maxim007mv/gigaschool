"""karkas.infra.storage — объектное хранилище (S3 Cloud.ru; локально — каталог).

В БД хранятся только метаданные и ключи; файлы — в Object Storage.
Presigned-ссылки живут 15 минут (settings.s3_presign_ttl_s).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from karkas.settings import settings


class ObjectStorage(Protocol):
    def put(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...
    def get(self, bucket: str, key: str) -> bytes: ...
    def presign(self, bucket: str, key: str, ttl_s: int = 900) -> str: ...


def local_presign_signature(bucket: str, key: str, exp: int) -> str:
    """HMAC-подпись для локального HTTP-presign (без boto3)."""
    secret = (settings.jwt_secret or "dev").encode("utf-8")
    payload = f"{bucket}\n{key}\n{exp}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def verify_local_presign(bucket: str, key: str, exp: int, signature: str) -> bool:
    """Проверить срок и подпись локальной ссылки."""
    if exp < int(time.time()):
        return False
    expected = local_presign_signature(bucket, key, exp)
    return hmac.compare_digest(expected, signature or "")


class LocalStorage:
    """Локальное хранилище для разработки и тестов (MinIO/S3 — на стенде)."""

    def __init__(self, root: str | None = None) -> None:
        # Абсолютный корень: иначе пути и раздача через API ломаются на cwd.
        self.root = Path(root or settings.storage_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, key: str) -> Path:
        safe = key.replace("..", "_").lstrip("/")
        path = self.root / bucket / safe
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._path(bucket, key).write_bytes(data)
        return key

    def get(self, bucket: str, key: str) -> bytes:
        return self._path(bucket, key).read_bytes()

    def presign(self, bucket: str, key: str, ttl_s: int = 900) -> str:
        """HTTP-ссылка на /api/v1/local-storage/... (кликабельна в UI, как S3)."""
        exp = int(time.time()) + max(1, int(ttl_s))
        sig = local_presign_signature(bucket, key, exp)
        base = (settings.public_api_base or "http://127.0.0.1:8000").rstrip("/")
        return (
            f"{base}/api/v1/local-storage/{quote(bucket, safe='')}/"
            f"{quote(key, safe='/')}?exp={exp}&sig={sig}"
        )


class S3Storage:
    """S3-совместимое хранилище Cloud.ru (boto3 импортируется лениво)."""

    def __init__(self) -> None:
        import boto3  # type: ignore[import-untyped]

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

    def put(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        return key

    def get(self, bucket: str, key: str) -> bytes:
        return self._client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def presign(self, bucket: str, key: str, ttl_s: int = 900) -> str:
        return self._client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl_s
        )


def get_storage() -> ObjectStorage:
    """S3, если заданы ключи; иначе локальный каталог (dev/тесты).

    Ошибка инициализации S3 в проде — фатальная (файлы не должны молча уезжать
    на диск контейнера); в dev — предупреждение и локальный каталог.
    LocalStorage не кэшируется: корень берётся из настроек (тесты его подменяют).
    """
    global _s3_singleton
    if settings.s3_access_key and settings.s3_secret_key:
        if _s3_singleton is None:
            try:
                _s3_singleton = S3Storage()
            except Exception:
                from karkas.logging_setup import get_logger

                get_logger("karkas.storage").exception("storage.s3_init_failed")
                if settings.environment == "prod":
                    raise
                return LocalStorage()
        return _s3_singleton
    return LocalStorage()


_s3_singleton: S3Storage | None = None


def content_sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()
