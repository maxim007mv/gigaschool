"""Интеграционные тесты защиты API: идемпотентность, IDOR, восстановление статусов.

Покрывают дефекты, найденные независимой проверкой: залипание статусов после
провала задачи, повторная генерация после завершённой, доступ к чужим файлам
и прогонам, обязательность If-Match, авторизация SSE.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from karkas.infra import db as db_module
from karkas.settings import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "migrations" / "sql"
TEST_DB = "karkas_hardening_test"

ORG_A = "00000000-0000-0000-0000-0000000000a1"
USER_A = "00000000-0000-0000-0000-0000000000a2"
ORG_B = "00000000-0000-0000-0000-0000000000b1"
USER_B = "00000000-0000-0000-0000-0000000000b2"
FILE_A = "00000000-0000-0000-0000-0000000000f1"


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
def hardened(monkeypatch):
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    assert _psql("-c", f"CREATE DATABASE {TEST_DB}").returncode == 0
    for sql_file in sorted(MIGRATIONS.glob("*.sql")):
        result = _psql("-f", str(sql_file), db=TEST_DB)
        assert result.returncode == 0, f"{sql_file.name}: {result.stderr}"

    import os

    from tests.integration.pg import pg_user

    user = pg_user()
    monkeypatch.setattr(settings, "database_url", f"postgresql+asyncpg://{user}@127.0.0.1:5432/{TEST_DB}")
    monkeypatch.setattr(settings, "db_pool_mode", "null")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-test-secret-test-secret-32")
    asyncio.run(db_module.dispose_engine())

    _psql(
        "-c",
        f"""
        INSERT INTO organization (id, name) VALUES ('{ORG_A}', 'Орг А'), ('{ORG_B}', 'Орг Б');
        INSERT INTO app_user (id, org_id, email, display_name, role) VALUES
          ('{USER_A}', '{ORG_A}', 'a@test.local', 'Методист А', 'methodist'),
          ('{USER_B}', '{ORG_B}', 'b@test.local', 'Методист Б', 'methodist');
        INSERT INTO file_object (id, org_id, uploaded_by, filename, mime_type, size_bytes, sha256, s3_key, extracted_text)
        VALUES ('{FILE_A}', '{ORG_A}', '{USER_A}', 'secret.txt', 'text/plain', 5, '\\x00'::bytea, 'a/secret',
                'КОНФИДЕНЦИАЛЬНЫЙ ТЕКСТ ОРГАНИЗАЦИИ А');
        """,
        db=TEST_DB,
    )
    yield
    asyncio.run(db_module.dispose_engine())
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


def _client() -> TestClient:
    from karkas.api.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


def _token(user_id: str, org_id: str) -> str:
    from karkas.api.deps import create_access_token

    return create_access_token(user_id, org_id, "methodist")


def _headers(user_id: str = USER_A, org_id: str = ORG_A) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id, org_id)}"}


def _seed_program(org_id: str = ORG_A, owner_id: str = USER_A, status: str = "draft") -> str:
    import uuid as uuid_module

    program_id = str(uuid_module.uuid4())
    _psql(
        "-c",
        f"""
        INSERT INTO program (id, org_id, owner_id, title, kind, form, total_hours, final_att_hours, status)
        VALUES ('{program_id}', '{org_id}', '{owner_id}', 'Тест', 'dop', 'full_time', 16, 2, '{status}');
        """,
        db=TEST_DB,
    )
    return program_id


def test_foreign_file_cannot_be_attached(hardened) -> None:
    """IDOR: файл чужой организации нельзя привязать к своей программе."""
    client = _client()
    response = client.post(
        "/api/v1/programs",
        headers=_headers(USER_B, ORG_B),
        json={
            "brief": "Курс на 16 часов для проверки доступа",
            "file_ids": [{"file_id": FILE_A, "role": "reference"}],
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_foreign_run_cannot_be_continued(hardened) -> None:
    """IDOR: продолжение чужого автопрогона запрещено."""
    program_a = _seed_program(ORG_A, USER_A)
    run_id = "00000000-0000-0000-0000-0000000000r1".replace("r", "e")
    _psql(
        "-c",
        f"""
        INSERT INTO agent_run (id, program_id, mode, status, request)
        VALUES ('{run_id}', '{program_a}', 'full', 'needs_input', '{{}}'::jsonb);
        """,
        db=TEST_DB,
    )
    client = _client()
    response = client.post(
        "/api/v1/agent/run",
        headers=_headers(USER_B, ORG_B),
        json={"run_id": run_id, "answers": {"q1": "Общеразвивающая"}, "wait": False},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_regenerate_after_completed_job_creates_new_task(hardened) -> None:
    """Повторная генерация после успешной задачи не залипает (новый job_id)."""
    program_id = _seed_program()
    _psql(
        "-c",
        f"""
        INSERT INTO clarification (program_id, slot, question, options, ord, answer, answered_at) VALUES
          ('{program_id}', 'kind', 'Тип?', '[]'::jsonb, 1, 'Общеразвивающая', now()),
          ('{program_id}', 'total_hours', 'Часы?', '[]'::jsonb, 2, '16', now()),
          ('{program_id}', 'audience', 'Кто?', '[]'::jsonb, 3, 'Школьники', now()),
          ('{program_id}', 'entry_level', 'Уровень?', '[]'::jsonb, 4, 'Нулевой', now()),
          ('{program_id}', 'form', 'Форма?', '[]'::jsonb, 5, 'Очная', now());
        UPDATE program SET profile = jsonb_set(profile, '{{slot_defaults}}', '{{"final_attestation": "Зачёт"}}'::jsonb, true)
        WHERE id = '{program_id}';
        """,
        db=TEST_DB,
    )
    client = _client()
    headers = _headers()

    first = client.post(f"/api/v1/programs/{program_id}/framework:generate", headers=headers)
    assert first.status_code == 202, first.text
    job1 = first.json()["job_id"]

    # Имитируем успешное выполнение задачи воркером
    _psql(
        "-c",
        f"""
        UPDATE job SET status = 'succeeded', finished_at = now() WHERE id = '{job1}';
        UPDATE program SET status = 'framework_review' WHERE id = '{program_id}';
        """,
        db=TEST_DB,
    )

    second = client.post(f"/api/v1/programs/{program_id}/framework:generate", headers=headers)
    assert second.status_code == 202, second.text
    assert second.json()["job_id"] != job1, "повторная генерация должна создать новую задачу"


def test_worker_failure_restores_program_status(hardened, monkeypatch) -> None:
    """Провал задачи возвращает программу из framework_generating (нет dead-end)."""
    program_id = _seed_program(status="framework_generating")

    async def seed_job() -> str:
        from karkas.infra.repos import jobs as jobs_repo

        factory = db_module.get_session_factory()
        async with factory() as session:
            job_id = await jobs_repo.enqueue(
                session,
                kind="framework",
                program_id=program_id,
                priority=1,
                payload={"prev_status": "framework_review"},
                idempotency_key=f"framework:{program_id}:test",
            )
            await session.commit()
        return job_id

    job_id = asyncio.run(seed_job())
    asyncio.run(db_module.dispose_engine())

    async def broken(job, on_progress):
        raise ValueError("LLM вернул мусор")

    monkeypatch.setattr("karkas.worker._dispatch", broken)
    from karkas.worker import process_one

    assert asyncio.run(process_one("worker-hardening")) is True

    status = _psql(
        "-c",
        f"SELECT status FROM program WHERE id = '{program_id}';",
        db=TEST_DB,
    )
    assert "framework_review" in status.stdout, status.stdout
    job_status = _psql("-c", f"SELECT status FROM job WHERE id = '{job_id}';", db=TEST_DB)
    assert "failed" in job_status.stdout


def test_program_update_allowed_while_kit_generating(hardened) -> None:
    """Обновление программы в статусе kit_generating (снимок версии воркером) не падает."""
    program_id = _seed_program(status="draft")
    from tests.integration.test_repos_roundtrip import _kit

    async def run() -> int:
        from karkas.infra.repos import framework as framework_repo
        from karkas.infra.repos import programs as programs_repo

        factory = db_module.get_session_factory()
        async with factory() as session:
            await framework_repo.save_kit(session, program_id, _kit())
            await programs_repo.set_status(session, program_id=program_id, status="framework_review")
            await session.commit()
            await programs_repo.set_status(
                session, program_id=program_id, status="framework_approved", approved_by=USER_A
            )
            await session.commit()
            await programs_repo.set_status(session, program_id=program_id, status="kit_generating")
            await session.commit()
            # сохранение снимка воркером в статусе kit_generating (раньше падало GATE_NOT_PASSED)
            version = await programs_repo.save_version(
                session,
                program_id=program_id,
                reason="kit_generated",
                snapshot={"schema_version": "kit.v1"},
            )
            await session.commit()
            await programs_repo.set_status(session, program_id=program_id, status="kit_review")
            await session.commit()
            return version

    version = asyncio.run(run())
    asyncio.run(db_module.dispose_engine())
    assert version == 1

    check = _psql("-c", f"SELECT status FROM program WHERE id = '{program_id}';", db=TEST_DB)
    assert "kit_review" in check.stdout


def test_pagination_cursor_works(hardened) -> None:
    """Курсорная пагинация: next_cursor ведёт на вторую страницу (а не в 500)."""
    for _index in range(3):
        _seed_program(ORG_A, USER_A)
    client = _client()
    headers = _headers()

    first = client.get("/api/v1/programs", headers=headers, params={"limit": 2})
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"]

    second = client.get("/api/v1/programs", headers=headers, params={"limit": 2, "cursor": body["next_cursor"]})
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) >= 1

    bad = client.get("/api/v1/programs", headers=headers, params={"cursor": "не-курсор"})
    assert bad.status_code == 400
    assert bad.json()["code"] == "BAD_REQUEST"


def test_cancel_restores_program_status(hardened) -> None:
    """Отмена задачи возвращает программу из framework_generating (нет dead-end)."""
    program_id = _seed_program(status="framework_generating")

    async def seed_job() -> str:
        from karkas.infra.repos import jobs as jobs_repo

        factory = db_module.get_session_factory()
        async with factory() as session:
            job_id = await jobs_repo.enqueue(
                session,
                kind="framework",
                program_id=program_id,
                priority=1,
                payload={"prev_status": "framework_review"},
                idempotency_key=f"framework:{program_id}:cancel-test",
            )
            await session.commit()
        return job_id

    job_id = asyncio.run(seed_job())
    asyncio.run(db_module.dispose_engine())

    client = _client()
    response = client.post(f"/api/v1/jobs/{job_id}:cancel", headers=_headers())
    assert response.status_code == 202, response.text

    check = _psql("-c", f"SELECT status FROM program WHERE id = '{program_id}';", db=TEST_DB)
    assert "framework_review" in check.stdout


def test_agent_run_idempotency(hardened, monkeypatch) -> None:
    """Idempotency-Key на POST /agent/run не создаёт дубли прогонов."""
    import karkas.api.routers.agent as agent_router

    async def noop_dispatch(session, run_id: str, program_id: str, *, wait: bool) -> None:
        return None

    monkeypatch.setattr(agent_router, "_dispatch_agent_run", noop_dispatch)

    client = _client()
    headers = {**_headers(), "Idempotency-Key": "run-key-1"}
    payload = {"request": "Курс для школьников: первые шаги в Python, 16 часов", "wait": True}

    first = client.post("/api/v1/agent/run", headers=headers, json=payload)
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/agent/run", headers=headers, json=payload)
    assert second.status_code == 200, second.text
    assert first.json()["run_id"] == second.json()["run_id"]

    third = client.post(
        "/api/v1/agent/run",
        headers={**_headers(), "Idempotency-Key": "run-key-2"},
        json=payload,
    )
    assert third.status_code == 200
    assert third.json()["run_id"] != first.json()["run_id"]


def test_unhandled_error_is_problem_json(hardened, monkeypatch) -> None:
    """Непредвиденная ошибка — 500 в формате problem+json (RFC 9457)."""
    import karkas.api.routers.programs as programs_router

    async def boom(*args, **kwargs):
        raise RuntimeError("неожиданный сбой")

    monkeypatch.setattr(programs_router.programs_repo, "list_programs", boom)
    client = _client()
    response = client.get("/api/v1/programs", headers=_headers())
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_sse_requires_token_and_scopes_org(hardened) -> None:
    """SSE: без токена — 401; с токеном чужой организации — 404 (не раскрываем чужое)."""
    program_a = _seed_program(ORG_A, USER_A)
    client = _client()

    unauthorized = client.get(f"/api/v1/programs/{program_a}/events")
    assert unauthorized.status_code == 401

    foreign = client.get(f"/api/v1/programs/{program_a}/events", params={"token": _token(USER_B, ORG_B)})
    assert foreign.status_code == 404  # не раскрываем существование чужой программы
