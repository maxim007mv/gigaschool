"""migrations.runner — применение SQL-миграций КАРКАС.

Контракт как у `alembic upgrade head`, но выполнение идёт через asyncpg
(simple query protocol), потому что SQL-файлы содержат несколько инструкций,
а asyncpg/SQLAlchemy в prepared-режиме их не принимает.

Учёт применённых файлов — таблица `schema_migrations` (filename, sha256, applied_at).
Изменённый после применения файл считается ошибкой (миграции неизменяемы).

Использование:
    python -m migrations.runner                 # продакшн-цепочка (без демо-данных)
    python -m migrations.runner --demo          # + 900_demo_sample248.sql (демо/стенд)
    python -m migrations.runner --db-url postgresql://user@host:5432/karkas
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "sql"

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename text PRIMARY KEY,
    sha256 bytea NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def dsn_from_settings(database_url: str) -> str:
    """postgresql+asyncpg://… → postgresql://… для прямого asyncpg."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def migration_files(migrations_dir: Path, include_demo: bool = False) -> list[Path]:
    files = sorted(p for p in migrations_dir.glob("*.sql"))
    if not include_demo:
        files = [p for p in files if not p.name.startswith("9")]
    return files


async def apply_migrations(
    dsn: str,
    migrations_dir: Path = MIGRATIONS_DIR,
    *,
    include_demo: bool = False,
) -> list[str]:
    """Применить недостающие миграции. Возвращает список применённых файлов.

    Advisory-lock не даёт двум раннерам (деплой + CI) применять DDL одновременно.
    """
    conn = await asyncpg.connect(dsn)
    applied: list[str] = []
    try:
        await conn.execute(SCHEMA_MIGRATIONS_DDL)
        # Блокировка на время применения всех миграций (ключ — стабильная константа).
        await conn.execute("SELECT pg_advisory_lock(727_274_727)")
        try:
            for path in migration_files(migrations_dir, include_demo):
                content = path.read_text(encoding="utf-8")
                digest = hashlib.sha256(content.encode("utf-8")).digest()
                row = await conn.fetchrow(
                    "SELECT sha256 FROM schema_migrations WHERE filename = $1", path.name
                )
                if row is not None:
                    if bytes(row["sha256"]) != digest:
                        raise RuntimeError(
                            f"Миграция {path.name} изменена после применения — так нельзя. "
                            "Добавьте новую миграцию вместо правки применённой."
                        )
                    continue
                async with conn.transaction():
                    await conn.execute(content)  # без параметров → simple protocol, multi-statement
                    await conn.execute(
                        "INSERT INTO schema_migrations (filename, sha256) VALUES ($1, $2)",
                        path.name,
                        digest,
                    )
                applied.append(path.name)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(727_274_727)")
    finally:
        await conn.close()
    return applied


async def applied_migrations(dsn: str) -> list[tuple[str, str]]:
    """Список применённых миграций (filename, applied_at ISO)."""
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(SCHEMA_MIGRATIONS_DDL)
        rows = await conn.fetch("SELECT filename, applied_at FROM schema_migrations ORDER BY filename")
        return [(r["filename"], r["applied_at"].isoformat()) for r in rows]
    finally:
        await conn.close()


def main() -> None:
    from karkas.settings import settings

    parser = argparse.ArgumentParser(description="КАРКАС: применение SQL-миграций")
    parser.add_argument("--db-url", default=None, help="postgresql://… (по умолчанию DATABASE_URL)")
    parser.add_argument("--demo", action="store_true", help="включить демо-данные (900_*.sql)")
    args = parser.parse_args()

    if settings.database_url.startswith("sqlite"):
        from migrations.lite import apply_lite

        applied = asyncio.run(apply_lite(settings.database_url, include_demo=args.demo))
    else:
        dsn = args.db_url or dsn_from_settings(settings.database_url)
        applied = asyncio.run(apply_migrations(dsn, include_demo=args.demo))
    if applied:
        print("Применены миграции:", ", ".join(applied))
    else:
        print("Схема уже актуальна")


if __name__ == "__main__":
    main()
