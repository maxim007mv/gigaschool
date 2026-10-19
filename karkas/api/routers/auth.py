"""karkas.api.routers.auth — вход, refresh, выход, профиль (Д4 §6.2, §8).

JWT: access 15 минут, refresh 14 дней; пароль — Argon2id.
"""

from __future__ import annotations

import time
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api.deps import (
    CurrentPrincipal,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from karkas.api.errors import Unauthorized
from karkas.infra.db import get_session

router = APIRouter(prefix="/auth", tags=["auth"])

#: Отозванные refresh-токены (jti → exp): in-process, на пилоте — таблица отзыва.
_REVOKED_REFRESH: dict[str, float] = {}


def _revoke(jti: str, expires_at: float) -> None:
    now = time.time()
    # Периодическая уборка, чтобы словарь не рос бесконечно.
    if len(_REVOKED_REFRESH) > 10_000:
        for key, exp in list(_REVOKED_REFRESH.items()):
            if exp < now:
                _REVOKED_REFRESH.pop(key, None)
    _REVOKED_REFRESH[jti] = expires_at


def _is_revoked(jti: str) -> bool:
    exp = _REVOKED_REFRESH.get(jti)
    if exp is None:
        return False
    if exp < time.time():
        _REVOKED_REFRESH.pop(jti, None)
        return False
    return True


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class MeOut(BaseModel):
    user_id: str | None
    org_id: str | None
    role: str
    email: str | None


def _hash_verify(password: str, password_hash: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    ph = PasswordHasher()
    try:
        return ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError, ValueError):
        return False


def _dummy_verify(password: str) -> None:
    """Выровнять время ответа для несуществующего пользователя (анти-энумерация)."""
    from argon2 import PasswordHasher

    # Хэш фиктивного пароля: считается один раз на процесс.
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = PasswordHasher().hash("dummy-password-for-timing")
    _hash_verify(password, _DUMMY_HASH)


_DUMMY_HASH: str | None = None


@router.post("/login", response_model=TokenOut)
async def login(
    payload: LoginIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenOut:
    """Вход по e-mail и паролю (с лимитом попыток по IP)."""
    from karkas.api.deps import check_ip_rate_limit

    client_ip = request.client.host if request.client else "unknown"
    check_ip_rate_limit(client_ip, rate_per_min=10, prefix="login")
    row = (
        (
            await session.execute(
                text(
                    """
                SELECT id, org_id, email, role, password_hash, is_active
                FROM app_user WHERE lower(email) = lower(:email)
                ORDER BY created_at LIMIT 1
                """
                ),
                {"email": payload.email},
            )
        )
        .mappings()
        .first()
    )
    if row is None or not row["is_active"] or not row["password_hash"]:
        _dummy_verify(payload.password)  # выравнивание времени ответа (анти-энумерация)
        raise Unauthorized("Неверный e-mail или пароль")
    if not _hash_verify(payload.password, row["password_hash"]):
        raise Unauthorized("Неверный e-mail или пароль")
    return TokenOut(
        access_token=create_access_token(str(row["id"]), str(row["org_id"]), row["role"], row["email"]),
        refresh_token=create_refresh_token(str(row["id"]), str(row["org_id"]), row["role"]),
        expires_in=15 * 60,
    )


@router.post("/refresh", response_model=TokenOut)
async def refresh(payload: RefreshIn) -> TokenOut:
    """Обновление access-токена по refresh-токену с ротацией.

    Старый refresh-токен отзывается (jti → revoked до истечения срока): повторное
    использование украденного токена не пройдёт. Хранилище — in-process; на пилоте
    заменяется таблицей отзыва без смены контракта.
    """
    claims = decode_token(payload.refresh_token)
    if claims.get("typ") != "refresh":
        raise Unauthorized("Нужен refresh-токен")
    jti = str(claims.get("jti") or "")
    if jti and _is_revoked(jti):
        raise Unauthorized("Refresh-токен отозван — войдите заново")
    if jti:
        _revoke(jti, float(claims.get("exp") or 0))
    return TokenOut(
        access_token=create_access_token(claims["sub"], claims["org"], claims["role"]),
        refresh_token=create_refresh_token(claims["sub"], claims["org"], claims["role"]),
        expires_in=15 * 60,
    )


class LogoutIn(BaseModel):
    refresh_token: str | None = None


@router.post("/logout", status_code=204)
async def logout(payload: LogoutIn | None = None) -> None:
    """Отзыв refresh-токена (jti попадает в in-process список отозванных)."""
    token = payload.refresh_token if payload else None
    if token:
        try:
            claims = decode_token(token)
            jti = str(claims.get("jti") or "")
            if jti:
                _revoke(jti, float(claims.get("exp") or 0))
        except (jwt.PyJWTError, ValueError, TypeError):
            pass  # logout идемпотентен: невалидный токен просто не отзывается
    return None


#: Отдельный роутер для GET /api/v1/me (путь без префикса /auth, Д4 §6.2).
me_router = APIRouter(tags=["auth"])


@me_router.get("/me", response_model=MeOut)
async def me(principal: CurrentPrincipal) -> MeOut:
    return MeOut(
        user_id=principal.user_id,
        org_id=principal.org_id,
        role=principal.role,
        email=principal.email,
    )
