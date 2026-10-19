"""Интеграционные тесты репозиториев: круг KitV1 → БД → KitV1, часы, очередь, версии.

Требуют локальный PostgreSQL 17 с pgvector и файлы migrations/sql/*.sql.
Если окружение недоступно — тесты пропускаются (не молча: причина в отчёте pytest).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from karkas.domain.kit import (
    AnswerKey,
    Assessment,
    AssessmentOption,
    Calendar,
    CalendarSession,
    Competency,
    Content,
    ContentBlock,
    FinalAttestation,
    Framework,
    KitV1,
    Module,
    Outcome,
    ProgramHeader,
    Source,
    Topic,
    Workload,
)
from karkas.infra.repos import framework as framework_repo
from karkas.infra.repos import jobs as jobs_repo
from karkas.infra.repos import programs as programs_repo
from karkas.infra.repos import registry as registry_repo

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "migrations" / "sql"
TEST_DB = "karkas_repo_test"


def _psql(*args: str, db: str = "postgres") -> subprocess.CompletedProcess:
    psql = shutil.which("psql") or "/opt/homebrew/opt/postgresql@17/bin/psql"
    return subprocess.run(
        [psql, "-h", "127.0.0.1", "-v", "ON_ERROR_STOP=1", "-d", db, *args],
        capture_output=True,
        text=True,
    )


def _postgres_ready() -> bool:
    try:
        result = _psql("-c", "SELECT 1")
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_ready(), reason="PostgreSQL недоступен для интеграционных тестов"),
    pytest.mark.skipif(not (MIGRATIONS / "001_init.sql").exists(), reason="миграции ещё не созданы"),
]


@pytest.fixture(scope="module")
def database_url() -> str:
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    result = _psql("-c", f"CREATE DATABASE {TEST_DB}")
    assert result.returncode == 0, result.stderr
    for sql_file in sorted(MIGRATIONS.glob("*.sql")):
        result = _psql("-f", str(sql_file), db=TEST_DB)
        assert result.returncode == 0, f"{sql_file.name}: {result.stderr}"
    from tests.integration.pg import pg_user

    user = pg_user()
    yield f"postgresql+asyncpg://{user}@127.0.0.1:5432/{TEST_DB}"
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


@pytest_asyncio.fixture()
async def session(database_url: str):
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture()
async def org_and_user(session) -> tuple[str, str]:
    org_id = (
        await session.execute(
            text(
                """
                INSERT INTO organization (name, requisites)
                VALUES ('АЦР Тест', '{"ОГРН": "1234567890123"}'::jsonb) RETURNING id
                """
            )
        )
    ).scalar_one()
    user_id = (
        await session.execute(
            text(
                """
                INSERT INTO app_user (org_id, email, display_name, role)
                VALUES (:org, 'methodist@test.local', 'Тестовый методист', 'methodist') RETURNING id
                """
            ),
            {"org": org_id},
        )
    ).scalar_one()
    await session.commit()
    return str(org_id), str(user_id)


def _kit(total_hours: int = 16, final_att: int = 2) -> KitV1:
    """Согласованный каркас: M1 (T1.1: 5+9=14) + ИА 2 = 16."""
    topic = Topic(
        ref="T1.1",
        title="Введение",
        summary="Первая тема",
        workload=Workload(lecture=5, practice=9, distance=2),
        outcome_refs=["LO1.1"],
        complexity=1,
        practicality=0.6,
    )
    module = Module(ref="M1", number=1, title="Основы", weight=1.0, topics=[topic])
    assessment = Assessment(
        ref="Q-001",
        kind="test_question",
        topic_ref="T1.1",
        module_ref="M1",
        stem="Что такое переменная?",
        qtype="single",
        options=[AssessmentOption(id="a", text="Ячейка памяти"), AssessmentOption(id="b", text="Файл")],
        answer_key=AnswerKey(correct=["a"], explanation="Переменная — именованная ячейка памяти"),
        outcome_refs=["LO1.1"],
        difficulty=1,
    )
    calendar = Calendar(
        weeks=4,
        days=8,
        days_per_week=2,
        max_hours_per_day=2,
        sessions=[
            CalendarSession(seq=i + 1, week=i // 2 + 1, day=i + 1, topic_ref="T1.1", activity="lecture", hours=2)
            for i in range(7)
        ]
        + [CalendarSession(seq=8, week=4, day=8, topic_ref=None, activity="final_attestation", hours=2)],
    )
    return KitV1(
        program=ProgramHeader(
            kind="dop",
            title="Первые шаги в Python",
            form="full_time",
            total_hours=total_hours,
            final_attestation=FinalAttestation(form="защита проекта", hours=final_att),
            document="сертификат",
        ),
        framework=Framework(
            goal="Познакомить школьников с основами Python",
            competencies=[
                Competency(
                    ref="C1",
                    title="Основы программирования",
                    outcomes=[Outcome(ref="LO1.1", type="skill", text="Пишет простые программы")],
                )
            ],
            modules=[module],
            final_attestation=FinalAttestation(form="защита проекта", hours=final_att),
            calendar=calendar,
        ),
        content=Content(
            assessments=[assessment],
            module_programs=[ContentBlock(ref="MP-M1", kind="module_program", module_ref="M1", body={"text": "…"})],
            sources=[
                Source(ref="SRC-01", section="main", citation="Самоучитель Python", status="unverified"),
            ],
        ),
    )


async def test_kit_roundtrip_through_normalized_tables(session, org_and_user) -> None:
    org_id, user_id = org_and_user
    program_id = await programs_repo.create_program(
        session, org_id=org_id, owner_id=user_id, title="Тест", brief="бриф"
    )
    kit = _kit()
    await framework_repo.save_kit(session, program_id, kit)
    await session.commit()

    loaded = await framework_repo.load_kit(session, program_id)
    assert loaded is not None
    assert loaded.program.title == kit.program.title
    assert loaded.program.total_hours == 16
    assert loaded.grand_total() == 16
    topic = loaded.framework.modules[0].topics[0]
    assert topic.workload.lecture == 5 and topic.workload.practice == 9
    assert topic.workload.distance == 2  # «из них дистанционно» разнесено и собрано обратно
    assert topic.outcome_refs == ["LO1.1"]
    assert loaded.content.assessments[0].ref == "Q-001"
    assert loaded.content.assessments[0].answer_key.correct == ["a"]
    assert loaded.content.sources[0].ref == "SRC-01"
    assert loaded.framework.calendar is not None
    assert len(loaded.framework.calendar.sessions) == 8


async def test_hours_views_and_gate(session, org_and_user) -> None:
    org_id, user_id = org_and_user
    program_id = await programs_repo.create_program(session, org_id=org_id, owner_id=user_id)
    kit = _kit()
    await framework_repo.save_kit(session, program_id, kit)
    await session.commit()

    # часы сходятся — нарушений нет
    assert await programs_repo.hours_issues(session, program_id) == []

    # статус framework_approved без утверждающего → ошибка триггера
    with pytest.raises(Exception) as exc_info:
        await programs_repo.set_status(session, program_id=program_id, status="framework_approved")
        await session.commit()
    assert "APPROVER_REQUIRED" in str(exc_info.value)
    await session.rollback()

    # корректное утверждение
    lock = await programs_repo.set_status(
        session, program_id=program_id, status="framework_approved", approved_by=user_id
    )
    assert lock is not None
    await session.commit()

    # теперь kit_generating разрешён
    await programs_repo.set_status(session, program_id=program_id, status="kit_generating")
    await session.commit()

    # комплект собран → kit_review; правка часов возвращает каркас на проверку
    await programs_repo.set_status(session, program_id=program_id, status="kit_review")
    await session.commit()
    await session.execute(text("SET LOCAL karkas.solver = 'off'"))
    await session.execute(
        text(
            """
            UPDATE topic_workload SET hours = 4
            WHERE topic_id = (SELECT id FROM topic WHERE program_id = CAST(:pid AS uuid) AND ref = 'T1.1')
              AND activity = 'lecture'
            """
        ),
        {"pid": program_id},
    )
    await session.commit()
    status = (
        await session.execute(text("SELECT status FROM program WHERE id = CAST(:pid AS uuid)"), {"pid": program_id})
    ).scalar_one()
    assert status == "framework_review"

    # теперь часы не сходятся → V-HRS-01
    issues = await programs_repo.hours_issues(session, program_id)
    assert any(i["rule_code"] == "V-HRS-01" for i in issues)


async def test_kit_generating_before_approval_blocked(session, org_and_user) -> None:
    org_id, user_id = org_and_user
    program_id = await programs_repo.create_program(session, org_id=org_id, owner_id=user_id)
    with pytest.raises(Exception) as exc_info:
        await programs_repo.set_status(session, program_id=program_id, status="kit_generating")
        await session.commit()
    assert "GATE_NOT_PASSED" in str(exc_info.value)
    await session.rollback()


async def test_versions_are_immutable_and_listed(session, org_and_user) -> None:
    org_id, user_id = org_and_user
    program_id = await programs_repo.create_program(session, org_id=org_id, owner_id=user_id)
    kit = _kit()
    await framework_repo.save_kit(session, program_id, kit)
    v1 = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason="framework_generated",
        snapshot=kit.model_dump(mode="json"),
        created_by=user_id,
    )
    v2 = await programs_repo.save_version(
        session,
        program_id=program_id,
        reason="edit:test",
        snapshot=kit.model_dump(mode="json"),
        created_by=user_id,
    )
    await session.commit()
    assert (v1, v2) == (1, 2)
    versions = await programs_repo.list_versions(session, program_id)
    assert [v["version"] for v in versions] == [2, 1]

    with pytest.raises(Exception) as exc_info:
        await session.execute(
            text("UPDATE program_version SET reason = 'hack' WHERE program_id = CAST(:pid AS uuid)"),
            {"pid": program_id},
        )
        await session.commit()
    assert "append-only" in str(exc_info.value)
    await session.rollback()


async def test_jobs_queue_claim_and_idempotency(session, org_and_user) -> None:
    org_id, user_id = org_and_user
    program_id = await programs_repo.create_program(session, org_id=org_id, owner_id=user_id)
    job_id = await jobs_repo.enqueue(
        session, kind="framework", program_id=program_id, priority=1, idempotency_key="key-1"
    )
    again = await jobs_repo.enqueue(
        session, kind="framework", program_id=program_id, priority=1, idempotency_key="key-1"
    )
    assert job_id == again
    await session.commit()

    claimed = await jobs_repo.claim(session, "worker-test")
    assert claimed is not None and str(claimed["id"]) == job_id
    assert claimed["attempts"] == 1
    await jobs_repo.set_progress(session, job_id, {"step": "S07", "done": 3, "total": 9})
    await jobs_repo.succeed(session, job_id)
    await session.commit()

    job = await jobs_repo.get_job(session, job_id)
    assert job["status"] == "succeeded"
    assert job["progress"]["step"] == "S07"

    # очередь пуста
    assert await jobs_repo.claim(session, "worker-test") is None


async def test_questions_and_answers_flow(session, org_and_user) -> None:
    org_id, user_id = org_and_user
    program_id = await programs_repo.create_program(session, org_id=org_id, owner_id=user_id)
    await programs_repo.replace_questions(
        session,
        program_id=program_id,
        questions=[
            {
                "slot": "kind",
                "text": "Какой это тип программы?",
                "options": ["Повышение квалификации", "Общеразвивающая"],
            },
            {"slot": "total_hours", "text": "Сколько часов?", "options": ["36", "72", "144"]},
        ],
    )
    await session.commit()
    assert await programs_repo.open_questions_count(session, program_id) == 2
    assert not await programs_repo.required_slots_filled(session, program_id)

    questions = await programs_repo.get_questions(session, program_id)
    answers = {str(q["id"]): ("Повышение квалификации" if q["slot"] == "kind" else "72") for q in questions}
    await programs_repo.save_answers(session, program_id=program_id, answers=answers, use_default=set())
    await session.commit()
    assert await programs_repo.open_questions_count(session, program_id) == 0
    assert await programs_repo.required_slots_filled(session, program_id) is False  # остальные слоты не заданы


async def test_registry_search_finds_seeded_standard(session) -> None:
    found = await registry_repo.search_prof_standards(session, "информационные системы")
    assert any(row["code"] == "06.015" for row in found)
    functions = await registry_repo.labor_functions(session, "06.015")
    assert any(row["code"] == "C/14.6" for row in functions)

    acts = await registry_repo.normative_acts(session, program_kind="dpp_pk", on_date="2026-10-13")
    numbers = {row["number"] for row in acts}
    assert "266" in numbers  # действующий порядок ДПП
    assert "499" not in numbers  # утратил силу
