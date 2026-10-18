"""Интеграционный тест раннера миграций (идемпотентность, учёт, sha256)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from migrations.runner import MIGRATIONS_DIR, applied_migrations, apply_migrations, migration_files

MIGRATIONS_EXIST = (
    __import__("pathlib").Path(__file__).resolve().parents[2] / "migrations" / "sql" / "001_init.sql"
).exists()


def _psql(*args: str) -> subprocess.CompletedProcess:
    psql = shutil.which("psql") or "/opt/homebrew/opt/postgresql@17/bin/psql"
    return subprocess.run(
        [psql, "-h", "127.0.0.1", "-d", "postgres", "-v", "ON_ERROR_STOP=1", *args],
        capture_output=True,
        text=True,
    )


def _postgres_ready() -> bool:
    try:
        return _psql("-c", "SELECT 1").returncode == 0
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_ready(), reason="PostgreSQL недоступен"),
    pytest.mark.skipif(not MIGRATIONS_EXIST, reason="миграции ещё не созданы"),
]


@pytest.mark.asyncio
async def test_runner_applies_and_is_idempotent() -> None:
    db = "karkas_runner_test"
    _psql("-c", f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
    assert _psql("-c", f"CREATE DATABASE {db}").returncode == 0
    dsn = f"postgresql://{__import__('os').environ.get('USER', 'postgres')}@127.0.0.1:5432/{db}"
    try:
        expected = [p.name for p in migration_files(MIGRATIONS_DIR, include_demo=False)]
        applied = await apply_migrations(dsn)
        assert applied == expected

        # повторный запуск — no-op
        assert await apply_migrations(dsn) == []

        listed = await applied_migrations(dsn)
        assert [name for name, _ in listed] == applied
    finally:
        _psql("-c", f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
