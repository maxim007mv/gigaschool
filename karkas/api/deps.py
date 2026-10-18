"""karkas.api.deps — аутентификация, авторизация, org-scope, лимиты (Д4 §8).

Правила:
- пользователи: Authorization: Bearer <JWT> (access 15 мин);
- тестовая платформа: X-Api-Key (хэш sha256 в настройках; сравнение — constant-time);
- каждый запрос ограничен org_id принципала; роли: methodist/expert/head/admin/service.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated, Literal

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api.errors import Forbidden, RateLimited, Unauthorized
from karkas.infra.db import get_session
from karkas.settings import settings

Role = Literal["methodist", "expert", "head", "admin", "service"]

ALL_ROLES: tuple[Role, ...] = ("methodist", "expert", "head", "admin", "service")

bearer_scheme = HTTPBearer(auto_error=False)

JWT_ALGORITHM = "HS256"


@dataclass(frozen=True)
class Principal:
    """Текущий пользователь или сервисный ключ."""

    user_id: str | None
    org_id: str | None
    role: Role
    email: str | None = None
    is_service: bool = False

    def require(self, *roles: Role) -> None:
        if self.role not in roles:
            raise Forbidden(f"Действие доступно ролям: {', '.join(roles)}")


# --- JWT --------------------------------------------------------------------


def create_access_token(user_id: str, org_id: str, role: Role, email: str | None = None) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "org": org_id,
        "role": role,
        "email": email,
        "typ": "access",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + settings.jwt_access_ttl_min * 60,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, org_id: str, role: Role) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "org": org_id,
        "role": role,
        "typ": "refresh",
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + settings.jwt_refresh_ttl_days * 86_400,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Срок действия токена истёк") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Невалидный токен") from exc


def _agent_key_hashes() -> tuple[bytes, ...]:
    from functools import lru_cache

    @lru_cache(maxsize=1)
    def _cached(raw_value: str) -> tuple[bytes, ...]:
        hashes = []
        for raw in raw_value.split(","):
            raw = raw.strip().lower()
            if len(raw) == 64:
                try:
                    hashes.append(bytes.fromhex(raw))
                except ValueError:
                    continue
        return tuple(hashes)

    return _cached(settings.agent_api_keys_sha256)


def verify_api_key(api_key: str) -> bool:
    """Constant-time проверка X-Api-Key по sha256-хэшам из настроек."""
    digest = hashlib.sha256(api_key.encode("utf-8")).digest()
    return any(hmac.compare_digest(digest, known) for known in _agent_key_hashes())


# --- Зависимости -------------------------------------------------------------


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


DatabaseDep = Annotated[AsyncSession, Depends(get_db)]


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
) -> Principal:
    """Принципал из JWT или X-Api-Key. Порядок: API-ключ (service), затем JWT."""
    if x_api_key:
        if not verify_api_key(x_api_key):
            raise Unauthorized("Неверный API-ключ")
        principal = Principal(user_id=None, org_id=None, role="service", is_service=True)
        request.state.principal = principal
        return principal

    if credentials is None or not credentials.credentials:
        raise Unauthorized()

    payload = decode_token(credentials.credentials)
    if payload.get("typ") != "access":
        raise Unauthorized("Нужен access-токен")
    principal = Principal(
        user_id=payload.get("sub"),
        org_id=payload.get("org"),
        role=payload.get("role", "methodist"),
        email=payload.get("email"),
    )
    request.state.principal = principal
    return principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require_roles(*roles: Role) -> Callable[[Principal], Principal]:
    """Фабрика зависимостей «только для ролей …»."""

    async def _checker(principal: CurrentPrincipal) -> Principal:
        principal.require(*roles)
        return principal

    return _checker  # type: ignore[return-value]


MethodistOnly = Depends(require_roles("methodist", "admin"))
MethodistOrHead = Depends(require_roles("methodist", "head"))
MethodistOrExpert = Depends(require_roles("methodist", "expert"))


# --- Лимиты ------------------------------------------------------------------


class _TokenBucket:
    """Простой in-process лимитер: N запросов в минуту на ключ (Д4 §6.1)."""

    CLEANUP_EVERY = 512  # ключей между уборками (защита от роста словаря)

    def __init__(self) -> None:
        self._state: dict[str, tuple[float, float]] = {}  # key → (tokens, last_ts)
        self._calls = 0

    def _cleanup(self, now: float) -> None:
        stale = [key for key, (_tokens, last) in self._state.items() if now - last > 3600]
        for key in stale:
            self._state.pop(key, None)

    def allow(self, key: str, rate_per_min: int) -> bool:
        now = time.monotonic()
        self._calls += 1
        if self._calls % self.CLEANUP_EVERY == 0:
            self._cleanup(now)
        tokens, last = self._state.get(key, (float(rate_per_min), now))
        refill = (now - last) * (rate_per_min / 60.0)
        tokens = min(float(rate_per_min), tokens + refill)
        if tokens < 1.0:
            self._state[key] = (tokens, now)
            return False
        self._state[key] = (tokens - 1.0, now)
        return True


_bucket = _TokenBucket()


def check_ip_rate_limit(ip: str, *, rate_per_min: int, prefix: str = "ip") -> None:
    """Лимит по IP для неаутентифицированных эндпоинтов (например, /auth/login)."""
    if not _bucket.allow(f"{prefix}:{ip}", rate_per_min):
        raise RateLimited(retry_after_s=60)


async def enforce_rate_limit(principal: CurrentPrincipal) -> None:
    if principal.is_service:
        rate = settings.rate_per_min_api_key
        key = f"svc:{principal.user_id or 'agent'}"
    else:
        rate = settings.rate_per_min_user
        key = f"user:{principal.user_id}"
    if not _bucket.allow(key, rate):
        raise RateLimited(retry_after_s=60)


RateLimit = Depends(enforce_rate_limit)


# --- If-Match ----------------------------------------------------------------


def parse_if_match(if_match: str | None, current_lock_version: int, *, required: bool = False) -> None:
    """Проверка оптимистической блокировки по ETag/lock_version.

    Поддерживаются форматы: `"v<current_version>-<lock_version>"` (как выдаёт
    GET framework), `"v<lock_version>"` и просто `"<lock_version>"` — сравнивается
    всегда lock_version. Для пользовательских правок заголовок обязателен (Д4 §6.1).
    """
    from karkas.api.errors import VersionConflict

    if not if_match:
        if required:
            raise VersionConflict(
                "Нужен заголовок If-Match с ETag из GET framework (защита от одновременного редактирования)"
            )
        return
    cleaned = if_match.strip().strip('"').lstrip("W/").strip('"')
    parts = cleaned.split("-", 1)
    version_part = parts[0].lstrip("v")
    lock_part = parts[1] if len(parts) > 1 else parts[0]
    try:
        lock_version = int(lock_part.lstrip("v"))
    except ValueError:
        try:
            lock_version = int(version_part)
        except ValueError as exc:
            raise VersionConflict("Некорректный заголовок If-Match") from exc
    if lock_version != current_lock_version:
        raise VersionConflict(
            f"Версия каркаса на сервере — {current_lock_version}, у вас — {lock_version}. Обновите страницу."
        )
