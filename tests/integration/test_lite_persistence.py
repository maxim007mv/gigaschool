"""Lite-режим (SQLite): полный цикл сохранения/загрузки каркаса, отчёта и версий.

Тест не требует PostgreSQL: схема применяется через migrations.lite.apply_lite
на временной базе, настройки переключаются на SQLite на время теста.
"""

from __future__ import annotations

from pathlib import Path

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from karkas.domain.kit import (
    AnswerKey,
    Assessment,
    AssessmentOption,
    Calendar,
    CalendarSession,
    Competency,
    Content,
    ContentBlock,
    Criterion,
    FinalAttestation,
    Framework,
    KitV1,
    Module,
    Outcome,
    ProgramConstraints,
    ProgramHeader,
    ProgramProfile,
    Report,
    ReportIssue,
    Source,
    Topic,
    Workload,
)
from karkas.infra.repos import files as files_repo
from karkas.infra.repos import framework as framework_repo
from karkas.infra.repos import jobs as jobs_repo
from karkas.infra.repos import programs as programs_repo
from karkas.infra.repos import registry as registry_repo
from karkas.settings import settings
from migrations.lite import ORG_ID, USER_ID, apply_lite


def _lite_kit() -> KitV1:
    """Каркас со всеми JSON-полями: options/answer_key/rubric/body/evidence."""
    topic = Topic(
        ref="T1.1",
        title="Введение",
        summary="Первая тема",
        workload=Workload(lecture=5, practice=9, distance=2),
        outcome_refs=["LO1.1"],
        control_form="тест",
        complexity=1,
        practicality=0.6,
        locked=["practice:in_person"],
    )
    module = Module(ref="M1", number=1, title="Основы", weight=1.0, att_form="тест", topics=[topic])
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
    seminar = Assessment(
        ref="Q-002",
        kind="seminar_task",
        topic_ref="T1.1",
        stem="Опишите переменную",
        rubric=[Criterion(criterion="Полнота", max_points=2, levels=["0", "1", "2"])],
        outcome_refs=["LO1.1"],
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
            total_hours=16,
            final_attestation=FinalAttestation(form="защита проекта", hours=2),
            document="сертификат",
            organization="АЦР",
            city="Москва",
            year=2026,
        ),
        profile=ProgramProfile(
            audience="Школьники",
            entry_level="начальный",
            schedule="2 раза в неделю",
            notes="пилот",
            glossary={"переменная": "ячейка памяти"},
            constraints=ProgramConstraints(days_per_week=2, max_hours_per_day=2),
        ),
        framework=Framework(
            goal="Познакомить школьников с основами Python",
            tasks=["Написать первую программу"],
            competencies=[
                Competency(
                    ref="C1",
                    title="Основы программирования",
                    outcomes=[Outcome(ref="LO1.1", type="skill", text="Пишет простые программы", bloom_level=2)],
                )
            ],
            modules=[module],
            final_attestation=FinalAttestation(form="защита проекта", hours=2),
            calendar=calendar,
            gaps=["нет практики в лаборатории"],
        ),
        content=Content(
            assessments=[assessment, seminar],
            module_programs=[
                ContentBlock(ref="MP-M1", kind="module_program", module_ref="M1", body={"text": "…", "hours": 14})
            ],
            sources=[
                Source(
                    ref="SRC-01",
                    section="main",
                    citation="Самоучитель Python",
                    status="unverified",
                    evidence={"checked": False, "note": "нужна проверка"},
                    topic_refs=["T1.1"],
                )
            ],
        ),
    )


@pytest_asyncio.fixture()
async def lite_session(tmp_path: Path, monkeypatch) -> AsyncSession:
    """Временная SQLite-база + сессия; настройки указывают на неё (uses_sqlite())."""
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'lite.db'}"
    monkeypatch.setattr(settings, "database_url", db_url)
    monkeypatch.setattr(settings, "karkas_lite", True)
    await apply_lite(db_url)
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def test_lite_kit_report_and_versions_roundtrip(lite_session: AsyncSession) -> None:
    session = lite_session
    kit = _lite_kit()
    program_id = await programs_repo.create_program(
        session, org_id=ORG_ID, owner_id=USER_ID, title="Тест lite", brief="бриф"
    )

    await framework_repo.save_kit(session, program_id, kit)
    await session.commit()

    loaded = await framework_repo.load_kit(session, program_id)
    assert loaded is not None
    assert loaded.program.title == kit.program.title
    assert loaded.program.total_hours == 16
    assert loaded.program.final_attestation.form == "защита проекта"
    assert loaded.profile.constraints.days_per_week == 2
    assert loaded.profile.constraints.max_hours_per_day == 2
    assert loaded.profile.glossary == {"переменная": "ячейка памяти"}
    assert loaded.framework.goal == kit.framework.goal
    assert loaded.framework.gaps == ["нет практики в лаборатории"]
    assert loaded.grand_total() == 16

    assert len(loaded.framework.competencies) == 1
    competency = loaded.framework.competencies[0]
    assert competency.ref == "C1"
    assert competency.outcomes[0].ref == "LO1.1"
    assert competency.outcomes[0].bloom_level == 2

    assert len(loaded.framework.modules) == 1
    loaded_module = loaded.framework.modules[0]
    assert loaded_module.ref == "M1" and loaded_module.att_form == "тест"
    loaded_topic = loaded_module.topics[0]
    assert loaded_topic.ref == "T1.1"
    assert loaded_topic.workload.lecture == 5
    assert loaded_topic.workload.practice == 9
    assert loaded_topic.workload.distance == 2
    assert loaded_topic.outcome_refs == ["LO1.1"]
    assert loaded_topic.locked == ["practice:in_person"]

    assessments = {item.ref: item for item in loaded.content.assessments}
    assert assessments["Q-001"].options == [
        AssessmentOption(id="a", text="Ячейка памяти"),
        AssessmentOption(id="b", text="Файл"),
    ]
    assert assessments["Q-001"].answer_key is not None
    assert assessments["Q-001"].answer_key.correct == ["a"]
    assert assessments["Q-001"].answer_key.explanation == "Переменная — именованная ячейка памяти"
    assert assessments["Q-001"].module_ref == "M1"
    assert assessments["Q-001"].topic_ref == "T1.1"
    assert assessments["Q-002"].rubric[0].criterion == "Полнота"
    assert assessments["Q-002"].rubric[0].levels == ["0", "1", "2"]

    assert len(loaded.content.module_programs) == 1
    assert loaded.content.module_programs[0].body == {"text": "…", "hours": 14}
    assert loaded.content.module_programs[0].module_ref == "M1"

    assert len(loaded.content.sources) == 1
    loaded_source = loaded.content.sources[0]
    assert loaded_source.ref == "SRC-01"
    assert loaded_source.evidence == {"checked": False, "note": "нужна проверка"}
    assert loaded_source.topic_refs == ["T1.1"]

    assert loaded.framework.calendar is not None
    assert len(loaded.framework.calendar.sessions) == 8
    assert loaded.framework.calendar.sessions[-1].activity == "final_attestation"
    assert loaded.framework.calendar.days_per_week == 2

    # Повторное сохранение — полная замена дочерних строк без FK-конфликтов.
    await framework_repo.save_kit(session, program_id, kit)
    await session.commit()
    reloaded = await framework_repo.load_kit(session, program_id)
    assert reloaded is not None and reloaded.grand_total() == 16
    assert len(reloaded.content.sources) == 1
    assert len(reloaded.content.assessments) == 2

    report = Report(
        passed=False,
        version=1,
        duration_ms=42,
        summary={"scope": "kit", "errors": 1},
        issues=[
            ReportIssue(
                rule_code="V-HRS-01",
                severity="error",
                entity_ref="T1.1",
                message="Часы не сходятся",
                fix_hint={"field": "hours", "action": "rebalance"},
            )
        ],
        gaps=["нет источника"],
        sample_findings=["проверено 2 вопроса"],
        assumptions=["аудитория по умолчанию"],
    )
    run_id = await framework_repo.save_report(session, program_id, 1, report)
    await session.commit()

    loaded_report = await framework_repo.load_latest_report(session, program_id)
    assert loaded_report is not None
    assert loaded_report.passed is False
    assert loaded_report.version == 1
    assert loaded_report.duration_ms == 42
    assert loaded_report.summary["scope"] == "kit"
    assert loaded_report.gaps == ["нет источника"]
    assert loaded_report.sample_findings == ["проверено 2 вопроса"]
    assert loaded_report.assumptions == ["аудитория по умолчанию"]
    assert loaded_report.issues[0].rule_code == "V-HRS-01"
    assert loaded_report.issues[0].fix_hint == {"field": "hours", "action": "rebalance"}
    assert run_id

    snapshot = kit.model_dump(mode="json")
    v1 = await programs_repo.save_version(
        session, program_id=program_id, reason="framework_generated", snapshot=snapshot, created_by=USER_ID
    )
    v2 = await programs_repo.save_version(
        session, program_id=program_id, reason="edit:test", snapshot=snapshot, created_by=USER_ID
    )
    await session.commit()
    assert (v1, v2) == (1, 2)

    versions = await programs_repo.list_versions(session, program_id)
    assert [row["version"] for row in versions] == [2, 1]
    assert versions[0]["reason"] == "edit:test"

    stored = await programs_repo.get_version(session, program_id, 2)
    assert stored is not None
    assert stored["snapshot"]["program"]["title"] == kit.program.title
    assert stored["snapshot"]["framework"]["modules"][0]["topics"][0]["locked"] == ["practice:in_person"]
    assert KitV1.model_validate(stored["snapshot"]).grand_total() == 16


async def test_lite_program_pagination_cursor(lite_session: AsyncSession) -> None:
    session = lite_session
    created = [
        await programs_repo.create_program(session, org_id=ORG_ID, owner_id=USER_ID, title=f"Программа {i}")
        for i in range(3)
    ]
    await session.commit()

    first = await programs_repo.list_programs(session, org_id=ORG_ID, limit=2)
    assert len(first) == 2
    second = await programs_repo.list_programs(
        session, org_id=ORG_ID, limit=2, cursor=programs_repo.make_cursor(first[-1])
    )
    assert len(second) == 1
    assert not ({str(row["id"]) for row in first} & {str(row["id"]) for row in second})
    assert {str(row["id"]) for row in first + second} == set(created)


async def test_lite_clarification_json_and_answers(lite_session: AsyncSession) -> None:
    session = lite_session
    program_id = await programs_repo.create_program(session, org_id=ORG_ID, owner_id=USER_ID, title="Вопросы")
    await programs_repo.replace_questions(
        session,
        program_id=program_id,
        questions=[
            {"slot": "kind", "text": "Какой тип программы?", "options": ["ПК", "ДОП"]},
            {"slot": "total_hours", "text": "Сколько часов?", "options": ["16", "72"]},
        ],
    )
    await session.commit()

    rows = await programs_repo.get_questions(session, program_id)
    assert [row["options"] for row in rows] == [["ПК", "ДОП"], ["16", "72"]]
    assert await programs_repo.open_questions_count(session, program_id) == 2

    await programs_repo.save_answers(
        session,
        program_id=program_id,
        answers={str(rows[0]["id"]): "ПК", str(rows[1]["id"]): "16"},
        use_default=set(),
    )
    await session.commit()
    assert await programs_repo.open_questions_count(session, program_id) == 0


async def test_lite_file_object_dedup_and_program_link(lite_session: AsyncSession) -> None:
    session = lite_session
    program_id = await programs_repo.create_program(session, org_id=ORG_ID, owner_id=USER_ID, title="Файлы")
    params = {
        "org_id": ORG_ID,
        "uploaded_by": USER_ID,
        "filename": "brief.txt",
        "mime_type": "text/plain",
        "size_bytes": 5,
        "sha256": b"lite-sha-1",
        "s3_key": f"{ORG_ID}/sha/brief.txt",
        "extracted_text": "hello",
        "extract_meta": {"pages": 1, "chars": 5},
    }
    file_id = await files_repo.create_file(session, **params)
    same_id = await files_repo.create_file(session, **params)
    await session.commit()
    assert same_id == file_id

    row = await files_repo.get_file(session, file_id, org_id=ORG_ID)
    assert row is not None
    assert row["extract_meta"] == {"pages": 1, "chars": 5}
    found = await files_repo.find_by_sha(session, ORG_ID, b"lite-sha-1")
    assert found is not None and str(found["id"]) == file_id
    assert found["extract_meta"] == {"pages": 1, "chars": 5}

    await files_repo.attach_to_program(session, program_id=program_id, file_id=file_id, role="reference")
    await files_repo.attach_to_program(session, program_id=program_id, file_id=file_id, role="old_program")
    await session.commit()
    links = await files_repo.program_files(session, program_id)
    assert len(links) == 1
    assert links[0]["role"] == "old_program"
    assert links[0]["filename"] == "brief.txt"
    assert links[0]["has_text"] == 1


async def test_lite_jobs_payload_progress_and_error(lite_session: AsyncSession) -> None:
    session = lite_session
    program_id = await programs_repo.create_program(session, org_id=ORG_ID, owner_id=USER_ID, title="Задачи")
    job_id = await jobs_repo.enqueue(
        session,
        kind="framework",
        program_id=program_id,
        payload={"step": "S07", "n": 3},
        priority=1,
        idempotency_key="lite-job-1",
    )
    again = await jobs_repo.enqueue(
        session,
        kind="framework",
        program_id=program_id,
        payload={"step": "S07", "n": 3},
        priority=1,
        idempotency_key="lite-job-1",
    )
    assert again == job_id
    await session.commit()

    by_key = await jobs_repo.find_by_idempotency(session, "lite-job-1", org_id=ORG_ID)
    assert by_key is not None and by_key["payload"]["step"] == "S07"

    claimed = await jobs_repo.claim(session, "lite-worker")
    assert claimed is not None and str(claimed["id"]) == job_id
    assert claimed["attempts"] == 1
    assert claimed["payload"] == {"step": "S07", "n": 3}
    await jobs_repo.set_progress(session, job_id, {"done": 1, "total": 2})
    await jobs_repo.fail(session, job_id, {"code": "BOOM", "transient": False})
    await session.commit()

    job = await jobs_repo.get_job(session, job_id)
    assert job is not None
    assert job["status"] == "failed"
    assert job["progress"] == {"done": 1, "total": 2}
    assert job["error"] == {"code": "BOOM", "transient": False}
    assert await jobs_repo.has_active(session, program_id=program_id, kind="framework") is False


async def test_lite_registry_queries(lite_session: AsyncSession) -> None:
    session = lite_session
    found = await registry_repo.search_prof_standards(session, "информационным")
    assert any(row["code"] == "06.015" for row in found)
    functions = await registry_repo.labor_functions(session, "06.015")
    assert any(row["code"] == "C/14.6" for row in functions)
    assert all(isinstance(row[key], list) for row in functions for key in ("actions", "skills", "knowledge"))

    acts = await registry_repo.normative_acts(session, program_kind="dpp_pk", on_date="2026-10-13")
    numbers = {row["number"] for row in acts}
    assert "266" in numbers
    assert "499" not in numbers
    assert "official_url" in acts[0]

    services = await registry_repo.search_services(session, "Python")
    assert any(row["name"] == "Python" for row in services)


async def test_lite_llm_call_accepts_decimal_cost(lite_session: AsyncSession) -> None:
    """sqlite3 не умеет Decimal: учёт llm_call должен привести стоимость сам."""
    from decimal import Decimal

    from karkas.infra.repos import usage as usage_repo

    await usage_repo.record_llm_call(
        lite_session,
        org_id=ORG_ID,
        skill="S01",
        model="GigaChat/GigaChat-3-Pro",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=100,
        ok=True,
        cost_rub=Decimal("0.25"),
    )
    await lite_session.commit()
    assert await usage_repo.org_spent_today(lite_session, ORG_ID) == Decimal("0.25")
