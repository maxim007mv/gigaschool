"""POST kit:regenerate — точечная пересборка без смены каркаса."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid

import pytest

from karkas.agent import pipeline
from tests.integration.test_api_flow import MIGRATIONS, TEST_DB
from tests.integration.test_pipeline_full_run import FAKE_RESPONSES, FakeGateway

API_ORG = "00000000-0000-0000-0000-0000000000aa"
API_USER = "00000000-0000-0000-0000-0000000000bb"


def _postgres_ready() -> bool:
    psql = shutil.which("psql") or "/opt/homebrew/opt/postgresql@17/bin/psql"
    try:
        return (
            subprocess.run(
                [psql, "-h", "127.0.0.1", "-d", "postgres", "-c", "SELECT 1"], capture_output=True
            ).returncode
            == 0
        )
    except Exception:
        return False


def _psql(*args: str) -> subprocess.CompletedProcess:
    psql = shutil.which("psql") or "/opt/homebrew/opt/postgresql@17/bin/psql"
    return subprocess.run(
        [psql, "-h", "127.0.0.1", "-v", "ON_ERROR_STOP=1", "-d", TEST_DB, *args],
        capture_output=True,
        text=True,
    )


def _seed_program_api(*, status: str = "kit_review") -> str:
    program_id = str(uuid.uuid4())
    approved = status in ("framework_approved", "kit_generating", "kit_review", "kit_updating")
    approved_by = f"'{API_USER}'" if approved else "NULL"
    approved_at = "now()" if approved else "NULL"
    result = _psql(
        "-c",
        f"""
        INSERT INTO program (id, org_id, owner_id, title, kind, form, total_hours, final_att_hours,
                             status, approved_by, approved_at, profile)
        VALUES ('{program_id}', '{API_ORG}', '{API_USER}', 'Новая программа', 'dop', 'full_time', 16, 2,
                '{status}', {approved_by}, {approved_at},
                '{{"brief": "Программа для школьников 8–9 классов: первые шаги в Python, 16 часов."}}'::jsonb);
        """,
    )
    assert result.returncode == 0, result.stderr
    return program_id


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_ready(), reason="PostgreSQL недоступен"),
    pytest.mark.skipif(not (MIGRATIONS / "001_init.sql").exists(), reason="миграции не найдены"),
]


def test_kit_regenerate_core_updates_lecture_plan(api_env, monkeypatch) -> None:
    gateway = FakeGateway(FAKE_RESPONSES)
    monkeypatch.setattr(pipeline, "make_gateway", lambda *args, **kwargs: gateway)

    program_id = _seed_program_api(status="kit_review")

    async def run() -> str:
        from karkas.domain.kit import ContentBlock, Outcome
        from karkas.infra import db as db_module
        from karkas.infra.repos import framework as framework_repo
        from tests.integration.test_repos_roundtrip import _kit

        factory = db_module.get_session_factory()
        async with factory() as session:
            kit = _kit()
            kit.framework.competencies[0].outcomes.append(
                Outcome(ref="LO1.2", type="knowledge", text="Дополнительный результат")
            )
            kit.content.lecture_plans = [
                ContentBlock(
                    ref="LP-T1.1",
                    kind="lecture_plan",
                    module_ref="M1",
                    topic_ref="T1.1",
                    body={"title": "Старый план"},
                )
            ]
            await framework_repo.save_kit(session, program_id, kit)
            await session.commit()
            await pipeline.kit_regenerate_core(
                session,
                program_id,
                target_ref="T1.1",
                parts=["lecture_plan"],
                gateway=gateway,
            )
            await session.commit()
            loaded = await framework_repo.load_kit(session, program_id)
            assert loaded is not None
            plan = next(b for b in loaded.content.lecture_plans if b.topic_ref == "T1.1")
            return str(plan.body.get("title") or plan.body)

    body = asyncio.run(run())
    assert "Старый план" not in body
