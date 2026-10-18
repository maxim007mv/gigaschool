"""Сквозной интеграционный тест API: бриф → уточнения → каркас → Human Gate → комплект.

Приложение запускается TestClient'ом, БД — живой PostgreSQL со схемой из миграций.
Пользователь и программа создаются через API; каркас — через репозиторий (эмуляция
работы навыков), чтобы тест не зависел от LLM.
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
TEST_DB = "karkas_api_test"


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
def api_env(monkeypatch):
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    assert _psql("-c", f"CREATE DATABASE {TEST_DB}").returncode == 0
    for sql_file in sorted(MIGRATIONS.glob("*.sql")):
        result = _psql("-f", str(sql_file), db=TEST_DB)
        assert result.returncode == 0, f"{sql_file.name}: {result.stderr}"


    from tests.integration.pg import pg_user

    user = pg_user()
    monkeypatch.setattr(settings, "database_url", f"postgresql+asyncpg://{user}@127.0.0.1:5432/{TEST_DB}")
    monkeypatch.setattr(settings, "db_pool_mode", "null")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-test-secret-test-secret-32")
    asyncio.run(db_module.dispose_engine())

    # Организация и методист
    _psql(
        "-c",
        """
        INSERT INTO organization (id, name) VALUES
          ('00000000-0000-0000-0000-0000000000aa', 'АЦР Тест');
        INSERT INTO app_user (id, org_id, email, display_name, role) VALUES
          ('00000000-0000-0000-0000-0000000000bb',
           '00000000-0000-0000-0000-0000000000aa',
           'api@test.local', 'API Методист', 'methodist');
        """,
        db=TEST_DB,
    )
    yield
    asyncio.run(db_module.dispose_engine())
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


def _token() -> str:
    from karkas.api.deps import create_access_token

    return create_access_token(
        "00000000-0000-0000-0000-0000000000bb",
        "00000000-0000-0000-0000-0000000000aa",
        "methodist",
        "api@test.local",
    )


def _client() -> TestClient:
    from karkas.api.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


async def _seed_kit(program_id: str, *, break_hours: bool = False) -> None:
    """Записать согласованный каркас в БД (эмуляция результата S04–S10)."""
    from karkas.infra.repos import framework as framework_repo
    from tests.integration.test_repos_roundtrip import _kit

    factory = db_module.get_session_factory()
    async with factory() as session:
        kit = _kit()
        if break_hours:
            kit.framework.modules[0].topics[0].workload.lecture = 8  # 8+9+2(ИА) = 19 ≠ 16
        await framework_repo.save_kit(session, program_id, kit)
        await session.commit()


def test_full_api_flow(api_env) -> None:
    client = _client()
    headers = _auth()

    # 1. Создание программы из брифа
    response = client.post(
        "/api/v1/programs",
        headers=headers,
        json={"brief": "Программа для школьников 8–9 классов, 16 часов, Python"},
    )
    assert response.status_code == 202, response.text
    created = response.json()
    program_id = created["program_id"]
    assert created["status"] == "draft"

    # 2. Каркас ещё не собран
    assert client.get(f"/api/v1/programs/{program_id}/framework", headers=headers).status_code == 404

    # 3. Генерация каркаса без ответов на обязательные слоты → 409
    response = client.post(f"/api/v1/programs/{program_id}/framework:generate", headers=headers)
    assert response.status_code == 409
    assert response.json()["code"] == "CLARIFICATION_REQUIRED"

    # 4. Вопросы и ответы: 5 вопросов покрывают 5 слотов, шестой (final_attestation)
    #    закрывается значением по умолчанию через API («на ваше усмотрение»).
    _psql(
        "-c",
        f"""
        INSERT INTO clarification (program_id, slot, question, options, ord, answer, is_default, answered_at) VALUES
          ('{program_id}', 'kind', 'Какой это тип программы?', '["Повышение квалификации","Общеразвивающая"]'::jsonb, 1,
           'Повышение квалификации', false, now()),
          ('{program_id}', 'total_hours', 'Сколько часов?', '["36","72","144"]'::jsonb, 2, '16', false, now()),
          ('{program_id}', 'audience', 'Кто слушатели?', '[]'::jsonb, 3, 'Школьники 8-9 классов', false, now()),
          ('{program_id}', 'entry_level', 'Входной уровень?', '[]'::jsonb, 4, 'Нулевой', false, now()),
          ('{program_id}', 'form', 'Форма обучения?', '["Очная","Очно-заочная"]'::jsonb, 5, 'Очная', false, now());
        UPDATE program
        SET profile = jsonb_set(profile, '{{slot_defaults}}', '{{"final_attestation": "Защита проекта"}}'::jsonb, true)
        WHERE id = '{program_id}';
        """,
        db=TEST_DB,
    )
    questions = client.get(f"/api/v1/programs/{program_id}/questions", headers=headers)
    assert questions.status_code == 200
    assert len(questions.json()["questions"]) <= 5

    # 5. Эмуляция собранного каркаса (навыки S04–S10)
    asyncio.run(_seed_kit(program_id))
    asyncio.run(db_module.dispose_engine())

    framework = client.get(f"/api/v1/programs/{program_id}/framework", headers=headers)
    assert framework.status_code == 200, framework.text
    body = framework.json()
    assert body["kit"]["program"]["total_hours"] == 16
    assert framework.headers.get("ETag")

    # 6. Синхронная проверка каркаса
    validate = client.post(f"/api/v1/programs/{program_id}/framework:validate", headers=headers)
    assert validate.status_code == 200
    assert "passed" in validate.json()["checks"]

    # 6.1. If-Match обязателен для пользовательских правок (Д4 §6.1)
    no_match = client.patch(
        f"/api/v1/programs/{program_id}/framework",
        headers=headers,
        json={"ops": [{"op": "set_hours", "ref": "T1.1", "activity": "lecture", "hours": 10}]},
    )
    assert no_match.status_code == 412
    assert no_match.json()["code"] == "VERSION_CONFLICT"

    # 7. Правка часов ломает сумму → 409 при утверждении
    etag = framework.headers["ETag"]
    patch = client.patch(
        f"/api/v1/programs/{program_id}/framework",
        headers={**headers, "If-Match": etag},
        json={"ops": [{"op": "set_hours", "ref": "T1.1", "activity": "lecture", "hours": 10}]},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["checks"]["passed"] is False
    assert any(i["rule_code"] == "V-HRS-01" for i in patch.json()["checks"]["issues"])

    etag = client.get(f"/api/v1/programs/{program_id}/framework", headers=headers).headers["ETag"]
    approve = client.post(
        f"/api/v1/programs/{program_id}/framework:approve",
        headers={**headers, "If-Match": etag},
        json={"comment": "пробуем"},
    )
    assert approve.status_code == 409
    assert approve.json()["code"] == "HOURS_MISMATCH"
    assert approve.json()["issues"], "в ответе должен быть список нарушений"

    # 8. Rebalance возвращает часы к объёму (остальные правила минимального каркаса могут
    #    давать замечания по шаблону — проверяем именно часы).
    rebalance = client.post(
        f"/api/v1/programs/{program_id}/framework:rebalance", headers=headers, json={"keep_locked": True}
    )
    assert rebalance.status_code == 200, rebalance.text
    hours_issues = [issue for issue in rebalance.json()["checks"]["issues"] if issue["rule_code"].startswith("V-HRS")]
    assert hours_issues == [], f"часы должны сойтись после rebalance: {hours_issues}"

    # 9. Утверждение каркаса (Human Gate) и запуск комплекта
    etag = client.get(f"/api/v1/programs/{program_id}/framework", headers=headers).headers["ETag"]
    approve = client.post(
        f"/api/v1/programs/{program_id}/framework:approve",
        headers={**headers, "If-Match": etag},
        json={},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "framework_approved"

    kit_generate = client.post(f"/api/v1/programs/{program_id}/kit:generate", headers=headers, json={})
    assert kit_generate.status_code == 202, kit_generate.text
    job_id = kit_generate.json()["job_id"]

    job = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert job.status_code == 200
    assert job.json()["kind"] == "kit"

    # 10. Версии: утверждение и правки создали снимки
    versions = client.get(f"/api/v1/programs/{program_id}/versions", headers=headers)
    assert versions.status_code == 200
    reasons = [item["reason"] for item in versions.json()["items"]]
    assert "framework_approved" in reasons

    # 11. Отчёт самопроверки доступен (минимальный каркас может иметь замечания
    #     по полноте шаблона — отчёт всё равно формируется и содержит сводку).
    report = client.get(f"/api/v1/programs/{program_id}/report", headers=headers)
    assert report.status_code == 200
    body = report.json()
    assert "passed" in body and "summary" in body

    # 12. Восстановление версии действительно возвращает снимок в рабочую копию
    #     (в v1 — правка lecture=10) и снова отправляет каркас на Human Gate.
    #     Сначала имитируем завершение генерации комплекта (иначе restore запрещён).
    _psql(
        "-c",
        f"""
        UPDATE job SET status = 'succeeded', finished_at = now() WHERE id = '{job_id}';
        UPDATE program SET status = 'kit_review' WHERE id = '{program_id}';
        """,
        db=TEST_DB,
    )
    versions = client.get(f"/api/v1/programs/{program_id}/versions", headers=headers).json()["items"]
    assert any(v["reason"] == "edit:framework" for v in versions)
    restore = client.post(f"/api/v1/programs/{program_id}/versions/1:restore", headers=headers)
    assert restore.status_code == 200, restore.text
    assert restore.json()["status"] == "framework_review"
    restored = client.get(f"/api/v1/programs/{program_id}/framework", headers=headers)
    assert restored.status_code == 200
    restored_topic = restored.json()["kit"]["framework"]["modules"][0]["topics"][0]
    assert restored_topic["workload"]["lecture"] == 10, "снимок v1 должен вернуться в рабочую копию"


def test_gate_blocks_kit_before_approval(api_env) -> None:
    client = _client()
    headers = _auth()
    response = client.post("/api/v1/programs", headers=headers, json={"brief": "Курс по кибербезопасности, 72 часа"})
    program_id = response.json()["program_id"]
    asyncio.run(_seed_kit(program_id))
    asyncio.run(db_module.dispose_engine())

    gate = client.post(f"/api/v1/programs/{program_id}/kit:generate", headers=headers, json={})
    assert gate.status_code == 409
    assert gate.json()["code"] == "GATE_NOT_PASSED"


def test_edit_dry_run_returns_impact_plan(api_env) -> None:
    client = _client()
    headers = _auth()
    response = client.post("/api/v1/programs", headers=headers, json={"brief": "Курс, 16 часов"})
    program_id = response.json()["program_id"]
    asyncio.run(_seed_kit(program_id))
    asyncio.run(db_module.dispose_engine())

    edit = client.post(
        f"/api/v1/programs/{program_id}/edits",
        headers=headers,
        json={"target_ref": "T1.1", "instruction": "Переименуй тему во «Введение в Python»", "dry_run": True},
    )
    assert edit.status_code == 200, edit.text
    body = edit.json()
    assert "T1.1" in body["affected"]
    assert "MP-M1" in body["affected"]
    assert body["status"] == "planned"
