"""Интеграционные тесты исправлений по итогам ревью (API + конвейер + БД).

Покрывают: атомарный CAS (If-Match), валидацию PATCH, problem+json для 422/404,
идемпотентность в разрезе организаций, логин и ротацию refresh, персистентность
закреплений/календаря, recover_stuck по видам задач, диспетчер очереди и цикл
уточнений (ответы не теряются, вид программы берётся из ответа).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from karkas.infra import db as db_module
from karkas.settings import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "migrations" / "sql"
TEST_DB = "karkas_review_fixes_test"

ORG_A = "00000000-0000-0000-0000-0000000000c1"
USER_A = "00000000-0000-0000-0000-0000000000c2"
ORG_B = "00000000-0000-0000-0000-0000000000d1"
USER_B = "00000000-0000-0000-0000-0000000000d2"


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
def env(monkeypatch, tmp_path):
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    assert _psql("-c", f"CREATE DATABASE {TEST_DB}").returncode == 0
    for sql_file in sorted(MIGRATIONS.glob("*.sql")):
        result = _psql("-f", str(sql_file), db=TEST_DB)
        assert result.returncode == 0, f"{sql_file.name}: {result.stderr}"

    from tests.integration.pg import pg_user

    user = pg_user()
    monkeypatch.setattr(settings, "database_url", f"postgresql+asyncpg://{user}@127.0.0.1:5432/{TEST_DB}")
    monkeypatch.setattr(settings, "db_pool_mode", "null")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-test-secret-test-secret-32")
    asyncio.run(db_module.dispose_engine())

    _psql(
        "-c",
        f"""
        INSERT INTO organization (id, name) VALUES ('{ORG_A}', 'Орг А'), ('{ORG_B}', 'Орг Б');
        INSERT INTO app_user (id, org_id, email, display_name, role) VALUES
          ('{USER_A}', '{ORG_A}', 'a@fix.local', 'Методист А', 'methodist'),
          ('{USER_B}', '{ORG_B}', 'b@fix.local', 'Методист Б', 'methodist');
        """,
        db=TEST_DB,
    )
    yield
    asyncio.run(db_module.dispose_engine())
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


def _client() -> TestClient:
    from karkas.api.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


def _headers(user_id: str = USER_A, org_id: str = ORG_A) -> dict[str, str]:
    from karkas.api.deps import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user_id, org_id, 'methodist')}"}


async def _seed_kit(program_id: str) -> None:
    from karkas.infra.repos import framework as framework_repo
    from tests.integration.test_repos_roundtrip import _kit

    factory = db_module.get_session_factory()
    async with factory() as session:
        await framework_repo.save_kit(session, program_id, _kit())
        await session.commit()


def _seed_program(org_id: str = ORG_A, owner_id: str = USER_A, *, status: str = "draft") -> str:
    import uuid as uuid_module

    program_id = str(uuid_module.uuid4())
    approved = status in ("framework_approved", "kit_generating", "kit_review", "kit_updating")
    approved_by = f"'{owner_id}'" if approved else "NULL"
    approved_at = "now()" if approved else "NULL"
    _psql(
        "-c",
        f"""
        INSERT INTO program (id, org_id, owner_id, title, kind, form, total_hours, final_att_hours,
                             status, approved_by, approved_at, profile)
        VALUES ('{program_id}', '{org_id}', '{owner_id}', 'Новая программа', 'dop', 'full_time', 16, 2,
                '{status}', {approved_by}, {approved_at},
                '{{"brief": "Программа для школьников 8–9 классов: первые шаги в Python, 16 часов."}}'::jsonb);
        """,
        db=TEST_DB,
    )
    return program_id


# ---------------------------------------------------------------------------
# API: CAS, валидация, problem+json, идемпотентность
# ---------------------------------------------------------------------------


def test_if_match_is_atomic_cas(env) -> None:
    """Два PATCH с одним ETag: первый 200, второй 412 (правки не теряются молча)."""
    program_id = _seed_program()
    asyncio.run(_seed_kit(program_id))
    asyncio.run(db_module.dispose_engine())
    client = _client()
    headers = _headers()

    etag = client.get(f"/api/v1/programs/{program_id}/framework", headers=headers).headers["ETag"]
    first = client.patch(
        f"/api/v1/programs/{program_id}/framework",
        headers={**headers, "If-Match": etag},
        json={"ops": [{"op": "rename", "ref": "T1.1", "title": "Тема X"}]},
    )
    assert first.status_code == 200, first.text
    second = client.patch(
        f"/api/v1/programs/{program_id}/framework",
        headers={**headers, "If-Match": etag},  # устаревший ETag
        json={"ops": [{"op": "rename", "ref": "T1.1", "title": "Тема Y"}]},
    )
    assert second.status_code == 412
    assert second.json()["code"] == "VERSION_CONFLICT"
    # Первая правка не затёрта
    framework = client.get(f"/api/v1/programs/{program_id}/framework", headers=headers).json()
    assert framework["kit"]["framework"]["modules"][0]["topics"][0]["title"] == "Тема X"


def test_patch_program_validates_payload(env) -> None:
    """PATCH /programs: типизированные поля (мусорный constraints → 422, объём > 2000 → 422)."""
    program_id = _seed_program()
    client = _client()
    headers = _headers()
    client.get(f"/api/v1/programs/{program_id}", headers=headers).headers.get("ETag")
    # ETag карточки программы API не отдаёт — правки идут без If-Match только сервису,
    # поэтому берём lock_version из карточки и формируем If-Match вручную.
    lock_version = client.get(f"/api/v1/programs/{program_id}", headers=headers).json()["lock_version"]
    patch_headers = {**headers, "If-Match": f'"v{lock_version}"'}

    bad_constraints = client.patch(
        f"/api/v1/programs/{program_id}",
        headers=patch_headers,
        json={"constraints": "oops"},
    )
    assert bad_constraints.status_code == 422
    assert bad_constraints.headers["content-type"].startswith("application/problem+json")
    assert bad_constraints.json()["code"] == "VALIDATION_ERROR"

    bad_hours = client.patch(
        f"/api/v1/programs/{program_id}",
        headers=patch_headers,
        json={"total_hours": 2001},
    )
    assert bad_hours.status_code == 422


def test_problem_json_for_404_and_422(env) -> None:
    client = _client()
    not_found = client.get("/api/v1/nope")
    assert not_found.status_code == 404
    assert not_found.headers["content-type"].startswith("application/problem+json")
    assert not_found.json()["code"] == "NOT_FOUND"

    invalid_body = client.post("/api/v1/programs", headers=_headers(), json={"brief": ""})
    assert invalid_body.status_code == 422
    assert invalid_body.json()["code"] == "VALIDATION_ERROR"


def test_idempotency_key_is_org_scoped(env) -> None:
    """Чужой Idempotency-Key не раскрывает программу другой организации."""
    client = _client()
    key = "same-key-123"
    first = client.post(
        "/api/v1/programs",
        headers={**_headers(), "Idempotency-Key": key},
        json={"brief": "Курс на 16 часов для школьников, Python"},
    )
    assert first.status_code == 202
    program_a = first.json()["program_id"]

    second = client.post(
        "/api/v1/programs",
        headers={**_headers(USER_B, ORG_B), "Idempotency-Key": key},
        json={"brief": "Другой курс на 16 часов, Excel"},
    )
    assert second.status_code == 202
    assert second.json()["program_id"] != program_a  # своя программа, не чужая


def test_login_and_refresh_rotation(env) -> None:
    """Поведенческий тест входа: неверный пароль 401, верный 200, refresh ротируется."""
    from argon2 import PasswordHasher

    password_hash = PasswordHasher().hash("secret-pass")
    _psql(
        "-c",
        f"UPDATE app_user SET password_hash = '{password_hash}' WHERE id = '{USER_A}';",
        db=TEST_DB,
    )
    client = _client()

    wrong = client.post("/api/v1/auth/login", json={"email": "a@fix.local", "password": "nope"})
    assert wrong.status_code == 401

    ok = client.post("/api/v1/auth/login", json={"email": "a@fix.local", "password": "secret-pass"})
    assert ok.status_code == 200, ok.text
    refresh_token = ok.json()["refresh_token"]

    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert rotated.status_code == 200
    reused = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert reused.status_code == 401  # старый refresh отозван (ротация)


# ---------------------------------------------------------------------------
# БД: персистентность закреплений и календаря, recover_stuck
# ---------------------------------------------------------------------------


def test_locked_cells_and_calendar_roundtrip(env) -> None:
    """Закрепления тем и days_per_week переживают сохранение/загрузку."""
    program_id = _seed_program()

    async def run() -> tuple[list[str], int]:
        from karkas.infra.repos import framework as framework_repo
        from tests.integration.test_repos_roundtrip import _kit

        factory = db_module.get_session_factory()
        async with factory() as session:
            kit = _kit()
            kit.framework.modules[0].topics[0].locked = ["practice:in_person", "lecture:in_person"]
            # Ограничения и календарь должны быть согласованы: days_per_week
            # хранится в program.constraints (в calendar_session его нет).
            kit.profile.constraints.days_per_week = 2
            kit.profile.constraints.max_hours_per_day = 2
            await framework_repo.save_kit(session, program_id, kit)
            await session.commit()
            loaded = await framework_repo.load_kit(session, program_id)
            assert loaded is not None
            return (
                list(loaded.framework.modules[0].topics[0].locked),
                int(loaded.framework.calendar.days_per_week if loaded.framework.calendar else 0),
            )

    locked, days_per_week = asyncio.run(run())
    asyncio.run(db_module.dispose_engine())
    assert locked == ["practice:in_person", "lecture:in_person"]
    assert days_per_week == 2  # как в _kit(), а не дефолтные 5


def test_recover_stuck_per_kind(env) -> None:
    """Порог зависания зависит от вида задачи; исчерпавшие попытки → failed + откат статуса."""
    # Статус kit_generating выставляем на INSERT: триггер program_gate проверяет
    # только переходы UPDATE, а нам нужна программа «внутри генерации комплекта».
    program_id = _seed_program(status="kit_generating")
    # Согласованный каркас нужен, чтобы откат в framework_approved не упирался
    # в HOURS_MISMATCH (утверждение без сходящихся часов запрещено триггером).
    asyncio.run(_seed_kit(program_id))
    asyncio.run(db_module.dispose_engine())

    async def run() -> tuple[int, int, str]:
        from karkas.infra.repos import jobs as jobs_repo

        factory = db_module.get_session_factory()
        async with factory() as session:
            # kit «висит» 7 минут и исчерпал попытки — для kit это ещё в пределах
            # таймаута (20 мин), поэтому recover НЕ должен его трогать: проверяем,
            # что «зависла» только framework-задача (порог 360 с), а исчерпавший
            # попытки kit-джоб переводится в failed с откатом статуса программы.
            await jobs_repo.enqueue(
                session,
                kind="kit",
                program_id=program_id,
                priority=5,
                payload={"prev_status": "framework_approved"},
                idempotency_key="stuck-kit",
            )
            await jobs_repo.enqueue(
                session,
                kind="framework",
                program_id=program_id,
                priority=1,
                payload={"prev_status": "framework_review"},
                idempotency_key="stuck-framework",
            )
            await session.execute(
                text(
                    """
                    UPDATE job SET status='running', locked_by='w', locked_at=now() - interval '45 minutes',
                                   attempts = max_attempts
                    WHERE idempotency_key = 'stuck-kit'
                    """
                )
            )
            await session.execute(
                text(
                    """
                    UPDATE job SET status='running', locked_by='w', locked_at=now() - interval '7 minutes'
                    WHERE idempotency_key = 'stuck-framework'
                    """
                )
            )
            await session.commit()
            recovered, failed = await jobs_repo.recover_stuck(session)
            await session.commit()
            status = (
                await session.execute(
                    text("SELECT status FROM program WHERE id = CAST(:pid AS uuid)"), {"pid": program_id}
                )
            ).scalar_one()
            return recovered, failed, str(status)

    recovered, failed, program_status = asyncio.run(run())
    asyncio.run(db_module.dispose_engine())
    assert recovered == 1  # framework «завис» (7 мин > 360 с) и вернулся в очередь
    assert failed == 1  # kit исчерпал попытки и переведён в failed
    assert program_status == "framework_approved"  # откат из kit_generating по prev_status


# ---------------------------------------------------------------------------
# Конвейер: диспетчер очереди, цикл уточнений, правка часов поднимает Human Gate
# ---------------------------------------------------------------------------


def test_dispatch_job_intake_is_wired(env, monkeypatch) -> None:
    """Реальный dispatch_job (без подмены) выполняет intake через навыки."""
    from karkas.agent import pipeline
    from tests.integration.test_pipeline_full_run import FAKE_RESPONSES, FakeGateway

    gateway = FakeGateway(FAKE_RESPONSES)
    monkeypatch.setattr(pipeline, "make_gateway", lambda *args, **kwargs: gateway)

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

    async def run() -> tuple[str, int | None]:
        from karkas.infra.repos import jobs as jobs_repo

        factory = db_module.get_session_factory()
        async with factory() as session:
            job_id = await jobs_repo.enqueue(
                session,
                kind="intake",
                program_id=program_id,
                priority=1,
                payload={"brief": "Программа для школьников 8–9 классов: первые шаги в Python, 16 часов."},
                idempotency_key=f"dispatch-intake:{program_id}",
            )
            await session.commit()
            job = await jobs_repo.get_job(session, job_id)
        await pipeline.dispatch_job(dict(job), on_progress=None)
        async with factory() as session:
            title, total = (
                await session.execute(
                    text("SELECT title, total_hours FROM program WHERE id = CAST(:pid AS uuid)"),
                    {"pid": program_id},
                )
            ).first()
        return str(title), int(total) if total else None

    title, total_hours = asyncio.run(run())
    asyncio.run(db_module.dispose_engine())
    assert total_hours == 16
    assert title and title != "Новая программа"  # название выведено из брифа


def test_clarification_roundtrip_and_kind_from_answer(env, monkeypatch) -> None:
    """Ответы не теряются при повторном intake; вид программы берётся из ответа."""
    from karkas.agent import pipeline
    from tests.integration.test_pipeline_full_run import FAKE_RESPONSES, FakeGateway

    # S01 сообщает, что не хватает kind и total_hours; S03 вернёт вопрос (формат «question»).
    responses = dict(FAKE_RESPONSES)
    responses["S01"] = {
        **FAKE_RESPONSES["S01"],
        "missing_slots": ["kind", "total_hours"],
        # Нейтральная аудитория: иначе правила S02 найдут «школьник» в профиле
        # и определят ДОП без вопроса (как и было бы для реального брифа).
        "profile": {
            **FAKE_RESPONSES["S01"]["profile"],
            "audience": "Взрослые слушатели",
            "entry_level": "Базовый",
        },
        "template_signs": [],
    }
    # S02-арбитр не смог определить вид — вопрос о типе программы остаётся.
    responses["S02"] = {"kind": None, "confidence": 0.5, "rationale": "недостаточно признаков"}
    responses["S03"] = {
        "questions": [
            {
                "slot": "kind",
                "question": "Какой это тип программы?",
                "why": "Шаблон",
                "options": ["Повышение квалификации", "Общеразвивающая"],
            },
            {"slot": "total_hours", "question": "Сколько часов?", "why": "Объём", "options": ["36", "72"]},
        ],
        "assumptions": [],
    }
    gateway = FakeGateway(responses)
    monkeypatch.setattr(pipeline, "make_gateway", lambda *args, **kwargs: gateway)

    program_id = _seed_program()
    # Нейтральный бриф: правила S02 не дают сильных признаков, поэтому тип
    # программы действительно спрашивается (как в неполном запросе ТК-4).
    _psql(
        "-c",
        f"""
        UPDATE program SET profile = jsonb_set(profile, '{{brief}}',
            '"Курс по основам работы с электронными таблицами, 16 часов"'::jsonb, true)
        WHERE id = '{program_id}';
        """,
        db=TEST_DB,
    )

    async def run() -> tuple[int, list[dict], int, str]:
        factory = db_module.get_session_factory()
        async with factory() as session:
            intake = await pipeline.intake_core(session, program_id, gateway=gateway)
            await session.commit()
            questions = await pipeline.programs_repo.get_questions(session, program_id)
            open_count = await pipeline.programs_repo.open_questions_count(session, program_id)
            status = (
                await session.execute(
                    text("SELECT status FROM program WHERE id = CAST(:pid AS uuid)"), {"pid": program_id}
                )
            ).scalar_one()
        return open_count, [dict(q) for q in questions], len(intake["questions"]), str(status)

    open_count, questions, returned, status = asyncio.run(run())
    assert len(questions) == 1, f"stored={questions}"
    assert questions[0]["slot"] == "kind"
    assert returned == 1 and status == "clarifying"

    # Пользователь отвечает: «повышение квалификации» + 16 часов.
    _psql(
        "-c",
        f"""
        UPDATE clarification SET answer = 'Повышение квалификации', answered_at = now()
          WHERE program_id = '{program_id}' AND slot = 'kind';
        UPDATE clarification SET answer = '16', answered_at = now()
          WHERE program_id = '{program_id}' AND slot = 'total_hours';
        """,
        db=TEST_DB,
    )

    async def rerun() -> tuple[int, str, int | None]:
        factory = db_module.get_session_factory()
        async with factory() as session:
            await pipeline.intake_core(session, program_id, gateway=gateway)
            await session.commit()
            open_count = await pipeline.programs_repo.open_questions_count(session, program_id)
            row = (
                await session.execute(
                    text("SELECT kind, total_hours FROM program WHERE id = CAST(:pid AS uuid)"),
                    {"pid": program_id},
                )
            ).first()
        return open_count, str(row[0]), int(row[1]) if row[1] else None

    open_count2, kind, total_hours = asyncio.run(rerun())
    asyncio.run(db_module.dispose_engine())
    assert open_count2 == 0  # ответы сохранились, вопросы не пересозданы
    assert kind == "dpp_pk"  # вид взят из ответа, а не дефолт dop
    assert total_hours == 16


def test_edit_regenerates_only_affected_topic(env, monkeypatch) -> None:
    """Точечная правка пересобирает содержание затронутой темы, refs сохраняются."""
    from karkas.agent import pipeline
    from tests.integration.test_pipeline_full_run import FAKE_RESPONSES, FakeGateway

    gateway = FakeGateway(FAKE_RESPONSES)
    monkeypatch.setattr(pipeline, "make_gateway", lambda *args, **kwargs: gateway)

    program_id = _seed_program(status="kit_review")

    async def run() -> dict:
        from karkas.infra.repos import framework as framework_repo
        from karkas.infra.repos import programs as programs_repo
        from tests.integration.test_repos_roundtrip import _kit

        # S21 — LLM-навык: даём заготовку интента правки.
        gateway.responses["S21"] = {
            "action": "replace",
            "target_ref": "T1.1",
            "params": {"instruction": "проще"},
            "summary": "упростить формулировки темы",
        }

        factory = db_module.get_session_factory()
        async with factory() as session:
            # Каркас + комплект с содержанием темы T1.1 (вопросы/план) для правки.
            kit = _kit()
            from karkas.domain.kit import AnswerKey, Assessment, AssessmentOption, ContentBlock

            kit.content.assessments = [
                Assessment(
                    ref="Q-001",
                    kind="test_question",
                    topic_ref="T1.1",
                    module_ref="M1",
                    stem="Старый вопрос?",
                    qtype="single",
                    options=[
                        AssessmentOption(id="a", text="Старый"),
                        AssessmentOption(id="b", text="Второй"),
                    ],
                    answer_key=AnswerKey(correct=["a"], explanation="старое"),
                    outcome_refs=["LO1.1"],
                )
            ]
            kit.content.lecture_plans = [
                ContentBlock(
                    ref="LP-T1.1",
                    kind="lecture_plan",
                    module_ref="M1",
                    topic_ref="T1.1",
                    body={"title": "Старый план"},
                )
            ]
            # Динамические заготовки FakeGateway ссылаются на LO1.2 — добавим его,
            # чтобы постпроверка S14/S15 не отбросила пересобранные средства.
            from karkas.domain.kit import Outcome

            kit.framework.competencies[0].outcomes.append(Outcome(ref="LO1.2", type="knowledge", text="Знает основы"))
            await framework_repo.save_kit(session, program_id, kit)
            await programs_repo.set_status(
                session, program_id=program_id, status="framework_approved", approved_by=USER_A
            )
            await session.commit()
            edit_id = programs_repo.new_uuid()
            await session.execute(
                text(
                    """
                    INSERT INTO edit_request (id, program_id, author_id, target_ref, instruction, affected_refs, status, base_version)
                    VALUES (CAST(:eid AS uuid), CAST(:pid AS uuid), CAST(:author AS uuid), 'T1.1',
                            'Замени формулировки на более простые', :affected, 'running', 1)
                    """
                ),
                {
                    "eid": edit_id,
                    "pid": program_id,
                    "author": USER_A,
                    "affected": ["T1.1", "LP-T1.1", "Q-001", "MP-M1"],
                },
            )
            await session.commit()
            await pipeline.edit_core(session, program_id, edit_id, gateway=gateway)
            await session.commit()
            loaded = await framework_repo.load_kit(session, program_id)
            assert loaded is not None
            return {
                "questions": [a.ref for a in loaded.content.assessments if a.kind == "test_question"],
                "plans": [b.ref for b in loaded.content.lecture_plans],
                "stem": loaded.content.assessments[0].stem,
                "status": (
                    await session.execute(
                        text("SELECT status FROM program WHERE id = CAST(:pid AS uuid)"), {"pid": program_id}
                    )
                ).scalar_one(),
                "edit_status": (
                    await session.execute(
                        text("SELECT status FROM edit_request WHERE id = CAST(:eid AS uuid)"),
                        {"eid": edit_id},
                    )
                ).scalar_one(),
            }

    result = asyncio.run(run())
    asyncio.run(db_module.dispose_engine())
    assert result["edit_status"] == "applied"
    assert result["questions"] == ["Q-001"], "ref вопроса сохраняется при пересборке"
    assert result["plans"] == ["LP-T1.1"]
    assert result["stem"] != "Старый вопрос?"  # содержание реально пересобрано
    assert result["status"] == "framework_approved"  # часы не менялись — гейт не срабатывает


def test_execute_run_is_locked_against_double_start(env, monkeypatch) -> None:
    """Параллельный повтор execute_run не запускает конвейер дважды (advisory lock)."""
    from karkas.agent import pipeline
    from tests.integration.test_pipeline_full_run import FAKE_RESPONSES, FakeGateway

    gateway = FakeGateway(FAKE_RESPONSES)
    monkeypatch.setattr(pipeline, "make_gateway", lambda *args, **kwargs: gateway)

    _seed_program()

    async def run() -> tuple[int, str]:
        factory = db_module.get_session_factory()
        async with factory() as session:
            run_row = await pipeline.create_run(
                session,
                org_id=ORG_A,
                owner_id=USER_A,
                request_text="Курс для школьников: первые шаги в Python, 16 часов",
                mode="framework",
                auto_approve=True,
                formats=["json"],
                attachments=[],
                api_key_id=None,
            )
            await session.commit()
        run_program_id = run_row["program_id"]
        # create_run создаёт собственную программу — наполняем её слоты и каркас.
        _psql(
            "-c",
            f"""
            INSERT INTO clarification (program_id, slot, question, options, ord, answer, answered_at) VALUES
              ('{run_program_id}', 'kind', 'Тип?', '[]'::jsonb, 1, 'Общеразвивающая', now()),
              ('{run_program_id}', 'total_hours', 'Часы?', '[]'::jsonb, 2, '16', now()),
              ('{run_program_id}', 'audience', 'Кто?', '[]'::jsonb, 3, 'Школьники', now()),
              ('{run_program_id}', 'entry_level', 'Уровень?', '[]'::jsonb, 4, 'Нулевой', now()),
              ('{run_program_id}', 'form', 'Форма?', '[]'::jsonb, 5, 'Очная', now());
            UPDATE program SET profile = jsonb_set(profile, '{{slot_defaults}}', '{{"final_attestation": "Зачёт"}}'::jsonb, true)
            WHERE id = '{run_program_id}';
            """,
            db=TEST_DB,
        )
        run_id = run_row["run_id"]
        # Два параллельных запуска одного прогона: второй обязан выйти по lock.
        await asyncio.gather(pipeline.execute_run(run_id), pipeline.execute_run(run_id))
        async with factory() as session:
            versions = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM program_version WHERE program_id = CAST(:pid AS uuid) AND reason='framework_generated'"
                    ),
                    {"pid": run_program_id},
                )
            ).scalar_one()
            status = (
                await session.execute(
                    text("SELECT status FROM agent_run WHERE id = CAST(:rid AS uuid)"), {"rid": run_id}
                )
            ).scalar_one()
        return int(versions), str(status)

    versions, status = asyncio.run(run())
    asyncio.run(db_module.dispose_engine())
    assert versions == 1, "каркас собран ровно один раз"
    assert status == "completed"
