"""Интеграционный тест конвейера: S01–S20 на живом PostgreSQL с FakeGateway.

LLM подменяется детерминированными ответами по схемам навыков — проверяется вся
оркестрация pipeline: сборка каркаса из выходов S01–S09, валидация S10, Human Gate,
генерация комплекта S11–S19, выгрузка S20 и результат единого эндпоинта.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from sqlalchemy import text

from karkas.infra import db as db_module
from karkas.settings import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO_ROOT / "migrations" / "sql"
TEST_DB = "karkas_pipeline_test"


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


# ---------------------------------------------------------------------------
# Детерминированные ответы «модели» по схемам навыков
# ---------------------------------------------------------------------------

FAKE_RESPONSES: dict[str, dict[str, Any]] = {
    "S01": {
        "profile": {
            "audience": "Школьники 8–9 классов",
            "entry_level": "Нулевой",
            "constraints": {
                "min_practice_share_pct": 50,
                "days_per_week": 2,
                "max_hours_per_day": 2,
            },
        },
        "goal": "Познакомить школьников с основами программирования на Python",
        "requested": [],
        "missing_slots": [],
        "assumptions": [],
        "gaps": [],
        "template_signs": ["школьники"],
    },
    "S02": {"kind": "dop", "confidence": 0.95, "rationale": "признаки ДОП: школьники"},
    "S03": {"questions": [], "assumptions": []},
    "S04": {
        "sections": [{"title": "1.1 Аннотация", "order": 1}, {"title": "2.1 Учебный план", "order": 2}],
        "sample_errors": [],
        "topic_candidates": [],
        "findings": [],
        "notes": "",
    },
    "S05": {
        "prof_standard": None,
        "labor_functions": [],
        "confidence": 1.0,
        "note": "ДОП — без профстандартов",
    },
    "S06": {
        "competencies": [
            {
                "ref": "C1",
                "title": "Основы программирования на Python",
                "outcomes": [
                    {"ref": "LO1.1", "type": "knowledge", "text": "Знает, что такое переменная и условие"},
                    {"ref": "LO1.2", "type": "skill", "text": "Пишет простые программы с циклами"},
                    {"ref": "LO1.3", "type": "experience", "text": "Создал и защитил мини-проект"},
                ],
            }
        ],
        "gaps": [],
    },
    "S07": {
        "modules": [
            {
                "ref": "M1",
                "number": 1,
                "title": "Первые шаги",
                "weight": 1.0,
                "att_form": "тест",
                "topics": [
                    {
                        "ref": "T1.1",
                        "title": "Знакомство со средой",
                        "outcome_refs": ["LO1.1"],
                        "complexity": 1,
                        "practicality": 0.9,
                    },
                    {
                        "ref": "T1.2",
                        "title": "Переменные",
                        "outcome_refs": ["LO1.1"],
                        "complexity": 1,
                        "practicality": 0.5,
                    },
                    {
                        "ref": "T1.3",
                        "title": "Условия",
                        "outcome_refs": ["LO1.2"],
                        "complexity": 2,
                        "practicality": 0.8,
                    },
                    {
                        "ref": "T1.4",
                        "title": "Циклы",
                        "outcome_refs": ["LO1.2"],
                        "complexity": 2,
                        "practicality": 0.7,
                    },
                ],
            },
            {
                "ref": "M2",
                "number": 2,
                "title": "Мини-проект",
                "weight": 1.0,
                "att_form": "защита проекта",
                "topics": [
                    {
                        "ref": "T2.1",
                        "title": "Функции",
                        "outcome_refs": ["LO1.2"],
                        "complexity": 3,
                        "practicality": 0.6,
                    },
                    {
                        "ref": "T2.2",
                        "title": "Списки",
                        "outcome_refs": ["LO1.2"],
                        "complexity": 3,
                        "practicality": 0.4,
                    },
                    {
                        "ref": "T2.3",
                        "title": "Работа над проектом",
                        "outcome_refs": ["LO1.3"],
                        "complexity": 4,
                        "practicality": 0.9,
                    },
                ],
            },
        ],
        "gaps": [],
    },
    "S11": {
        "module_programs": [
            {
                "body": {
                    "annotation": "Модуль знакомит с базовыми конструкциями языка.",
                    "att_form": "тест",
                    "topics": [
                        {
                            "topic_ref": "T1.1",
                            "summary": "Среда разработки и первая программа",
                            "work_forms": ["практика"],
                            "materials": ["слайды"],
                        },
                        {
                            "topic_ref": "T1.2",
                            "summary": "Переменные и типы",
                            "work_forms": ["практика"],
                            "materials": ["слайды"],
                        },
                        {
                            "topic_ref": "T1.3",
                            "summary": "Условия и ветвления",
                            "work_forms": ["практика"],
                            "materials": ["слайды"],
                        },
                        {
                            "topic_ref": "T1.4",
                            "summary": "Циклы",
                            "work_forms": ["практика"],
                            "materials": ["слайды"],
                        },
                        {
                            "topic_ref": "T2.1",
                            "summary": "Функции",
                            "work_forms": ["практика"],
                            "materials": ["слайды"],
                        },
                        {
                            "topic_ref": "T2.2",
                            "summary": "Списки",
                            "work_forms": ["практика"],
                            "materials": ["слайды"],
                        },
                        {
                            "topic_ref": "T2.3",
                            "summary": "Работа над проектом",
                            "work_forms": ["проект"],
                            "materials": ["примеры"],
                        },
                    ],
                }
            }
        ],
        "notes": "",
    },
    "S12": {
        "lecture_plans": [
            {
                "ref": "LP-T1.1",
                "title": "Знакомство со средой",
                "body": {
                    "goals": ["Показать среду разработки"],
                    "stages": [{"stage": "Введение", "minutes": 5, "activity": "лекция", "notes": "пример"}],
                    "questions": ["Что такое программа?"],
                    "materials": ["слайды"],
                    "notes": "",
                },
            }
        ]
    },
    "S13": {
        "title": "Знакомство со средой",
        "body": {
            "slides": [
                {"title": "Слайд 1. Первая программа", "bullets": ["print()", "запуск"], "notes": "показать"},
                {"title": "Слайд 2. Ошибки", "bullets": ["читать сообщение"], "notes": "разобрать"},
            ],
            "notes": "",
        },
    },
    "S14": {
        "questions": [
            {
                "ref": "Q-001",
                "stem": "Что хранит переменная?",
                "qtype": "single",
                "options": [{"id": "a", "text": "Значение"}, {"id": "b", "text": "Только число"}],
                "answer_key": {"correct": ["a"], "explanation": "Переменная хранит значение"},
                "outcome_refs": ["LO1.1"],
                "difficulty": 1,
            },
            {
                "ref": "Q-002",
                "stem": "Что делает цикл for?",
                "qtype": "single",
                "options": [{"id": "a", "text": "Повторяет"}, {"id": "b", "text": "Удаляет"}],
                "answer_key": {"correct": ["a"], "explanation": "Повторяет блок"},
                "outcome_refs": ["LO1.2"],
                "difficulty": 2,
            },
        ]
    },
    "S15": {
        "tasks": [
            {
                "ref": "ST-T1.1-1",
                "stem": "Напишите программу, которая спрашивает имя и здоровается",
                "rubric": [{"criterion": "Программа работает", "max_points": 5, "levels": ["зачтено"]}],
                "outcome_refs": ["LO1.2"],
            }
        ]
    },
    "S16": {
        "items": [
            {
                "ref": "FA-1",
                "kind": "final_project",
                "stem": "Защита мини-проекта на Python",
                "rubric": [
                    {
                        "criterion": "Проект работает и объяснён",
                        "max_points": 10,
                        "levels": ["зачтено при ≥70%"],
                    }
                ],
                "outcome_refs": ["LO1.3"],
            }
        ],
        "form": "Защита проекта",
        "requirements": ["Код проекта", "Краткое описание"],
        "notes": "",
        "dropped": [],
    },
    "S17": {
        "sources": [
            {
                "section": "main",
                "citation": "Учебник «Python для школьников»",
                "url": None,
                "isbn": None,
                "normative_act_ref": None,
            }
        ],
        "notes": "",
    },
}


class FakeGateway:
    """LLM-шлюз для тестов: ответы по коду навыка, валидируемые его Pydantic-схемой.

    Для пошаговых навыков (S12/S13/S14/S15) ответ строится по теме из промпта,
    чтобы refs были уникальны для каждой темы (как в реальной генерации).
    """

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    @staticmethod
    def _topic_ref(messages: list[dict[str, Any]]) -> str:
        import re

        prompt = "\n".join(str(m.get("content") or "") for m in messages)
        match = re.search(r'"ref":\s*"(T\d{1,2}\.\d{1,2})"', prompt)
        return match.group(1) if match else "T1.1"

    def _dynamic(self, skill: str, topic_ref: str) -> dict[str, Any]:
        if skill == "S12":
            return {
                "lecture_plans": [
                    {
                        "ref": f"LP-{topic_ref}",
                        "title": f"Лекция по теме {topic_ref}",
                        "body": {
                            "goals": ["Разобрать тему"],
                            "stages": [{"stage": "Введение", "minutes": 5, "activity": "лекция", "notes": "пример"}],
                            "questions": ["Что мы узнали?"],
                            "materials": ["слайды"],
                            "notes": "",
                        },
                    }
                ]
            }
        if skill == "S13":
            return {
                "title": f"Тема {topic_ref}",
                "body": {
                    "slides": [
                        {"title": "Слайд 1", "bullets": ["тезис 1", "тезис 2"], "notes": "показать"},
                        {"title": "Слайд 2", "bullets": ["практика"], "notes": "разобрать"},
                    ],
                    "notes": "",
                },
            }
        if skill == "S14":
            return {
                "questions": [
                    {
                        "ref": f"Q-{topic_ref}",
                        "topic_ref": topic_ref,
                        "stem": f"Вопрос по теме {topic_ref}",
                        "qtype": "single",
                        "options": [{"id": "a", "text": "Верный"}, {"id": "b", "text": "Неверный"}],
                        "answer_key": {"correct": ["a"], "explanation": "Верный вариант"},
                        "outcome_refs": ["LO1.2"],
                        "difficulty": 1,
                    }
                ]
            }
        if skill == "S15":
            return {
                "tasks": [
                    {
                        "ref": f"ST-{topic_ref}-1",
                        "topic_ref": topic_ref,
                        "stem": f"Практическое задание по теме {topic_ref}",
                        "rubric": [{"criterion": "Выполнено", "max_points": 5, "levels": ["зачтено"]}],
                        "outcome_refs": ["LO1.2"],
                    }
                ]
            }
        raise AssertionError(f"FakeGateway: нет динамического ответа для {skill}")

    async def complete_json(
        self,
        skill: str,
        model_class: str,
        messages: list[dict[str, Any]],
        schema: type[BaseModel],
        temperature: float | None = None,
    ) -> BaseModel:
        self.calls.append(skill)
        if skill in ("S12", "S13", "S14", "S15"):
            payload = self._dynamic(skill, self._topic_ref(messages))
        else:
            payload = self.responses.get(skill)
            if payload is None:
                raise AssertionError(f"FakeGateway: нет заготовки для навыка {skill}")
        return schema.model_validate(payload)


# ---------------------------------------------------------------------------
# Окружение
# ---------------------------------------------------------------------------


@pytest.fixture()
def pipeline_db(monkeypatch, tmp_path):
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    assert _psql("-c", f"CREATE DATABASE {TEST_DB}").returncode == 0
    for sql_file in sorted(MIGRATIONS.glob("*.sql")):
        result = _psql("-f", str(sql_file), db=TEST_DB)
        assert result.returncode == 0, f"{sql_file.name}: {result.stderr}"

    import os

    user = os.environ.get("USER", "postgres")
    monkeypatch.setattr(settings, "database_url", f"postgresql+asyncpg://{user}@127.0.0.1:5432/{TEST_DB}")
    monkeypatch.setattr(settings, "db_pool_mode", "null")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    asyncio.run(db_module.dispose_engine())
    yield
    asyncio.run(db_module.dispose_engine())
    _psql("-c", f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")


async def _seed_program() -> tuple[str, str]:
    """Организация, методист и программа с отвеченными слотами (16 ч, ДОП)."""
    from karkas.infra.repos import programs as programs_repo

    factory = db_module.get_session_factory()
    async with factory() as session:
        org_id = (
            await session.execute(text("INSERT INTO organization (name) VALUES ('АЦР Тест') RETURNING id"))
        ).scalar_one()
        user_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO app_user (org_id, email, display_name, role)
                    VALUES (:org, 'pipeline@test.local', 'Методист', 'methodist') RETURNING id
                    """
                ),
                {"org": org_id},
            )
        ).scalar_one()
        program_id = await programs_repo.create_program(
            session,
            org_id=str(org_id),
            owner_id=str(user_id),
            title="Новая программа",
            profile={
                "brief": "Программа для школьников 8–9 классов без опыта: первые шаги в Python, 16 часов.",
                "slot_defaults": {"final_attestation": "Защита проекта"},
            },
        )
        for ord_value, (slot, question, answer) in enumerate(
            [
                ("kind", "Какой это тип программы?", "Общеразвивающая"),
                ("total_hours", "Сколько часов?", "16"),
                ("audience", "Кто слушатели?", "Школьники 8–9 классов"),
                ("entry_level", "Входной уровень?", "Нулевой"),
                ("form", "Форма обучения?", "Очная"),
            ],
            start=1,
        ):
            await session.execute(
                text(
                    """
                    INSERT INTO clarification (program_id, slot, question, options, ord, answer, answered_at)
                    VALUES (CAST(:pid AS uuid), :slot, :question, '[]'::jsonb, :ord, :answer, now())
                    """
                ),
                {"pid": program_id, "slot": slot, "question": question, "ord": ord_value, "answer": answer},
            )
        await session.commit()
    return program_id, str(org_id)


async def _run_framework(program_id: str, gateway: FakeGateway) -> dict[str, Any]:
    from karkas.agent import pipeline

    factory = db_module.get_session_factory()
    async with factory() as session:
        intake = await pipeline.intake_core(session, program_id, gateway=gateway)
        await session.commit()
        framework = await pipeline.framework_core(session, program_id, gateway=gateway)
        await session.commit()
        return {"intake": intake, "framework": framework}


def test_intake_and_framework_assembly(pipeline_db) -> None:
    program_id, _ = asyncio.run(_seed_program())
    gateway = FakeGateway(FAKE_RESPONSES)
    result = asyncio.run(_run_framework(program_id, gateway))

    # --- S01–S03: вид программы, объём, вопросы ---
    assert result["intake"]["questions"] == []
    assert "S01" in gateway.calls
    # S02/S03/S05 для ДОП решаются правилами (сильные признаки «школьники»),
    # LLM-арбитр не вызывается — это ожидаемое поведение (Д4 §5.1).
    assert "S02" not in gateway.calls

    # --- S04–S10: каркас собран из выходов навыков, часы — из солвера ---
    kit = result["framework"]["kit"]
    assert kit.program.kind == "dop"
    assert kit.program.total_hours == 16
    assert kit.grand_total() == 16, "Σ тем + ИА обязана сходиться"
    workload = kit.framework_workload()
    assert workload.practice >= 8, "минимальная доля практики 50 %"
    assert workload.lecture + workload.practice == 14
    assert len(kit.framework.modules) == 2
    assert len(list(kit.iter_topics())) == 7
    assert len(list(kit.iter_outcomes())) == 3
    assert kit.framework.calendar is not None
    assert kit.framework.calendar.days == 8
    assert kit.framework.calendar.weeks == 4
    assert kit.framework.calendar.max_hours_per_day == 2

    report = result["framework"]["report"]
    assert report is not None
    hours_errors = [i for i in report.errors if i.rule_code.startswith("V-HRS")]
    assert hours_errors == [], f"часы должны сходиться: {hours_errors}"

    # --- сохранение: статус, снимок, отчёт ---
    async def _check_db() -> None:
        factory = db_module.get_session_factory()
        async with factory() as session:
            status = (
                await session.execute(
                    text("SELECT status FROM program WHERE id = CAST(:pid AS uuid)"), {"pid": program_id}
                )
            ).scalar_one()
            assert status == "framework_review"
            version = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM program_version WHERE program_id = CAST(:pid AS uuid) AND reason = 'framework_generated'"
                    ),
                    {"pid": program_id},
                )
            ).scalar_one()
            assert version == 1
            runs = (
                await session.execute(
                    text("SELECT count(*) FROM validation_run WHERE program_id = CAST(:pid AS uuid)"),
                    {"pid": program_id},
                )
            ).scalar_one()
            assert runs >= 1

    asyncio.run(_check_db())


def test_full_agent_run_end_to_end(pipeline_db, monkeypatch) -> None:
    """POST /agent/run (mode=full, auto_approve): бриф → карты → комплект → выгрузки."""
    from karkas.agent import pipeline

    program_id, _ = asyncio.run(_seed_program())
    # У программы уже есть ответы — прогон создаёт СВОЮ программу; поэтому создаём
    # новую с теми же слотами через create_run и заполняем ответы.
    gateway = FakeGateway(FAKE_RESPONSES)
    monkeypatch.setattr(pipeline, "make_gateway", lambda *args, **kwargs: gateway)

    async def _prepare() -> str:
        factory = db_module.get_session_factory()
        async with factory() as session:
            org_id = (await session.execute(text("SELECT id FROM organization LIMIT 1"))).scalar_one()
            owner_id = (await session.execute(text("SELECT id FROM app_user LIMIT 1"))).scalar_one()
            run = await pipeline.create_run(
                session,
                org_id=str(org_id),
                owner_id=str(owner_id),
                request_text="Курс для школьников 8–9 классов: первые шаги в Python, 16 часов.",
                mode="full",
                auto_approve=True,
                formats=["docx", "gift", "json"],
                attachments=[],
                api_key_id=None,
            )
            run_program_id = run["program_id"]
            await session.execute(
                text(
                    """
                    UPDATE program SET profile = jsonb_set(profile, '{slot_defaults}', '{"final_attestation": "Защита проекта"}'::jsonb, true)
                    WHERE id = CAST(:pid AS uuid)
                    """
                ),
                {"pid": run_program_id},
            )
            for ord_value, (slot, answer) in enumerate(
                [
                    ("kind", "Общеразвивающая"),
                    ("total_hours", "16"),
                    ("audience", "Школьники 8–9 классов"),
                    ("entry_level", "Нулевой"),
                    ("form", "Очная"),
                ],
                start=1,
            ):
                await session.execute(
                    text(
                        """
                        INSERT INTO clarification (program_id, slot, question, options, ord, answer, answered_at)
                        VALUES (CAST(:pid AS uuid), :slot, :question, '[]'::jsonb, :ord, :answer, now())
                        """
                    ),
                    {
                        "pid": run_program_id,
                        "slot": slot,
                        "question": slot,
                        "ord": ord_value,
                        "answer": answer,
                    },
                )
            await session.commit()
            return run["run_id"]

    run_id = asyncio.run(_prepare())
    asyncio.run(pipeline.execute_run(run_id))

    async def _result() -> Any:
        factory = db_module.get_session_factory()
        async with factory() as session:
            return await pipeline.run_result(session, run_id)

    out = asyncio.run(_result())
    assert out.status == "completed", out.detail
    assert out.kit is not None
    assert out.kit.grand_total() == 16
    assert out.version is not None and out.version >= 2  # framework_generated + kit_generated
    assert out.report is not None
    assert set(out.artifacts) >= {"program_docx", "tests_gift", "kit_json"}
    assert out.timings.get("framework_s") is not None
    assert out.timings.get("kit_s") is not None

    # Артефакты реально лежат в объектном хранилище и записаны в таблицу artifact
    async def _artifacts() -> tuple[int, str]:
        factory = db_module.get_session_factory()
        async with factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM artifact WHERE program_id = CAST(:pid AS uuid)"),
                    {"pid": out.program_id},
                )
            ).scalar_one()
            status = (
                await session.execute(
                    text("SELECT status FROM program WHERE id = CAST(:pid AS uuid)"), {"pid": out.program_id}
                )
            ).scalar_one()
        return int(count), str(status)

    artifact_count, program_status = asyncio.run(_artifacts())
    assert artifact_count >= 3
    assert program_status == "kit_review"

    from karkas.infra.storage import get_storage

    # presigned-ссылка в LocalStorage — file:// путь; проверяем сам ключ через таблицу
    async def _key() -> str:
        factory = db_module.get_session_factory()
        async with factory() as session:
            return (
                await session.execute(
                    text(
                        """
                        SELECT s3_key FROM artifact
                        WHERE program_id = CAST(:pid AS uuid) AND kind = 'program_docx'
                        ORDER BY created_at DESC LIMIT 1
                        """
                    ),
                    {"pid": out.program_id},
                )
            ).scalar_one()

    key = asyncio.run(_key())
    data = get_storage().get(settings.s3_bucket_art, key)
    assert data[:2] == b"PK", "docx — это zip-контейнер"

    # Навыки вызывались в правильном порядке: каркас до комплекта; S20 — код (без LLM)
    assert gateway.calls.index("S01") < gateway.calls.index("S11")
    assert "S16" in gateway.calls and "S17" in gateway.calls
    assert "S20" not in gateway.calls, "S20 — детерминированный экспорт, LLM не нужен"
