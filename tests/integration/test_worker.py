"""Интеграционные тесты воркера: захват задачи, успех, ретрай, провал, прогресс.

Используют живой PostgreSQL и подменяют пайплайн навыков (dispatch) — сама
оркестрация навыков проверяется отдельно в тестах агента.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from karkas.infra import db as db_module
from karkas.infra.repos import jobs as jobs_repo
from karkas.infra.repos import programs as programs_repo
from karkas.settings import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "migrations" / "sql"
TEST_DB = "karkas_worker_test"


def _psql(*args: str, db: str = "postgres") -> subprocess.CompletedProcess:
    psql = shutil.which("psql") or "/opt/homebrew/opt/postgresql@17/bin/psql"
    return subprocess.run(
        [psql, "-h", "127.0.0.1", "-v", "ON_ERROR_STOP=1", "-d", db, *args],
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
    pytest.mark.skipif(not (MIGRATIONS / "001_init.sql").exists(), reason="миграции ещё не созданы"),
]


@pytest.fixture()
def worker_db(monkeypatch):
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    assert _psql("-c", f"CREATE DATABASE {TEST_DB}").returncode == 0
    for sql_file in sorted(MIGRATIONS.glob("*.sql")):
        result = _psql("-f", str(sql_file), db=TEST_DB)
        assert result.returncode == 0, f"{sql_file.name}: {result.stderr}"

    import os

    user = os.environ.get("USER", "postgres")
    url = f"postgresql+asyncpg://{user}@127.0.0.1:5432/{TEST_DB}"
    monkeypatch.setattr(settings, "database_url", url)

    yield url

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(db_module.dispose_engine())
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


async def _seed_program() -> tuple[str, str]:
    factory = db_module.get_session_factory()
    async with factory() as session:
        org_id = (
            await session.execute(
                __import__("sqlalchemy").text(
                    "INSERT INTO organization (name) VALUES ('Тест-воркер') RETURNING id"
                )
            )
        ).scalar_one()
        user_id = (
            await session.execute(
                __import__("sqlalchemy").text(
                    """
                    INSERT INTO app_user (org_id, email, display_name, role)
                    VALUES (:org, 'w@test.local', 'Воркер', 'methodist') RETURNING id
                    """
                ),
                {"org": org_id},
            )
        ).scalar_one()
        program_id = await programs_repo.create_program(
            session, org_id=str(org_id), owner_id=str(user_id)
        )
        await session.commit()
    return str(program_id), str(org_id)


async def test_worker_success_path(worker_db, monkeypatch) -> None:
    await db_module.dispose_engine()
    program_id, _ = await _seed_program()

    calls: list[str] = []

    async def fake_dispatch(job, on_progress):
        calls.append(str(job["id"]))
        await on_progress({"step": "S08", "done": 1, "total": 3, "label": "Считаем часы"})

    monkeypatch.setattr("karkas.worker._dispatch", fake_dispatch)

    from karkas.worker import process_one

    factory = db_module.get_session_factory()
    async with factory() as session:
        job_id = await jobs_repo.enqueue(session, kind="framework", program_id=program_id, priority=1)
        await session.commit()

    assert await process_one("worker-test") is True
    assert calls == [job_id]

    async with factory() as session:
        job = await jobs_repo.get_job(session, job_id)
        assert job["status"] == "succeeded"
        assert job["progress"]["step"] == "S08"
        # очередь пуста
    assert await process_one("worker-test") is False
    await db_module.dispose_engine()


async def test_worker_transient_retry_then_fail(worker_db, monkeypatch) -> None:
    await db_module.dispose_engine()
    program_id, _ = await _seed_program()

    from karkas.agent.llm_gateway import TransientError

    async def flaky(job, on_progress):
        raise TransientError("модель временно недоступна")

    monkeypatch.setattr("karkas.worker._dispatch", flaky)

    from karkas.worker import process_one

    factory = db_module.get_session_factory()
    async with factory() as session:
        job_id = await jobs_repo.enqueue(
            session, kind="framework", program_id=program_id, priority=1
        )
        # max_attempts=2: первый прогон → retry_wait, второй → failed
        await session.execute(
            __import__("sqlalchemy").text(
                "UPDATE job SET max_attempts = 2, run_after = now() WHERE id = CAST(:jid AS uuid)"
            ),
            {"jid": job_id},
        )
        await session.commit()

    assert await process_one("worker-test") is True
    async with factory() as session:
        job = await jobs_repo.get_job(session, job_id)
        assert job["status"] == "retry_wait"
        assert job["attempts"] == 1
        # вернуть в очередь немедленно для теста
        await session.execute(
            __import__("sqlalchemy").text("UPDATE job SET run_after = now() WHERE id = CAST(:jid AS uuid)"),
            {"jid": job_id},
        )
        await session.commit()

    assert await process_one("worker-test") is True
    async with factory() as session:
        job = await jobs_repo.get_job(session, job_id)
        assert job["status"] == "failed"
        assert job["error"]["code"] == "TransientError"
    await db_module.dispose_engine()


async def test_worker_permanent_failure_fails_immediately(worker_db, monkeypatch) -> None:
    await db_module.dispose_engine()
    program_id, _ = await _seed_program()

    async def broken(job, on_progress):
        raise ValueError("схема невалидна")

    monkeypatch.setattr("karkas.worker._dispatch", broken)

    from karkas.worker import process_one

    factory = db_module.get_session_factory()
    async with factory() as session:
        job_id = await jobs_repo.enqueue(session, kind="edit", program_id=program_id)
        await session.commit()

    assert await process_one("worker-test") is True
    async with factory() as session:
        job = await jobs_repo.get_job(session, job_id)
        assert job["status"] == "failed"
        assert job["error"]["transient"] is False
    await db_module.dispose_engine()
