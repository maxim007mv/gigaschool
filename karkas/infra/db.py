"""karkas.infra.db — доступ к PostgreSQL (SQLAlchemy 2.0 Core + asyncpg).

Единая СУБД: данные + очередь job + кэш llm_cache + векторы kb_chunk (AD-6).
Движок создаётся лениво; в тестах можно подменить через KARKAS_DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from karkas.settings import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Ленивый singleton движка.

    db_pool_mode="null" (тесты, разные event loop) отключает пул соединений:
    каждое соединение живёт внутри своего цикла и не переиспользуется между ними.
    """
    global _engine
    if _engine is None:
        if settings.db_pool_mode == "null":
            from sqlalchemy.pool import NullPool

            _engine = create_async_engine(settings.database_url, poolclass=NullPool)
        else:
            _engine = create_async_engine(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=10,
                pool_pre_ping=True,
            )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Сессия БД как async-генератор (FastAPI dependency)."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def ping() -> bool:
    """Проверка соединения с БД (для /readyz)."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def dispose_engine() -> None:
    """Закрыть пул и выполнить shutdown-хуки верхних слоёв (тесты, graceful shutdown)."""
    from karkas.infra.lifecycle import run_shutdown_hooks

    await run_shutdown_hooks()
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
