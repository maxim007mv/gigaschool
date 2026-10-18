"""POST kit:regenerate — точечная пересборка без смены каркаса."""

from __future__ import annotations

import asyncio

from karkas.agent import pipeline
from tests.integration.test_pipeline_full_run import FAKE_RESPONSES, FakeGateway
import shutil
import subprocess

import pytest

from tests.integration.test_api_flow import MIGRATIONS
from tests.integration.test_review_fixes import _seed_program, env


def _postgres_ready() -> bool:
    psql = shutil.which("psql") or "/opt/homebrew/opt/postgresql@17/bin/psql"
    try:
        return subprocess.run([psql, "-h", "127.0.0.1", "-d", "postgres", "-c", "SELECT 1"], capture_output=True).returncode == 0
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_ready(), reason="PostgreSQL недоступен"),
    pytest.mark.skipif(not (MIGRATIONS / "001_init.sql").exists(), reason="миграции не найдены"),
]


def test_kit_regenerate_core_updates_lecture_plan(env, monkeypatch) -> None:
    gateway = FakeGateway(FAKE_RESPONSES)
    monkeypatch.setattr(pipeline, "make_gateway", lambda *args, **kwargs: gateway)

    program_id = _seed_program(status="kit_review")

    async def run() -> str:
        from karkas.infra import db as db_module
        from karkas.infra.repos import framework as framework_repo
        from tests.integration.test_repos_roundtrip import _kit

        from karkas.domain.kit import ContentBlock, Outcome

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
