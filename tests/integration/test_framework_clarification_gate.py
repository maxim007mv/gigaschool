"""ТК-4: API и воркер согласованы — открытый вопрос блокирует framework:generate."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.integration.test_api_flow import MIGRATIONS, TEST_DB, _auth, _client, _psql


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


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _postgres_ready(), reason="PostgreSQL недоступен"),
    pytest.mark.skipif(not (MIGRATIONS / "001_init.sql").exists(), reason="миграции не найдены"),
]


def test_framework_blocked_while_extra_open_question(api_env) -> None:
    """Обязательные слоты закрыты (часть — defaults), но открыт вопрос schedule → 409."""
    client = _client()
    headers = _auth()
    created = client.post(
        "/api/v1/programs",
        headers=headers,
        json={"brief": "Курс 72 часа для колледжа, кибербезопасность"},
    )
    assert created.status_code == 202
    program_id = created.json()["program_id"]

    _psql(
        "-c",
        f"""
        INSERT INTO clarification (program_id, slot, question, options, ord, answer, is_default, answered_at) VALUES
          ('{program_id}', 'kind', 'Тип?', '[]'::jsonb, 1, 'Повышение квалификации', false, now()),
          ('{program_id}', 'total_hours', 'Часы?', '[]'::jsonb, 2, '72', false, now()),
          ('{program_id}', 'audience', 'Кто?', '[]'::jsonb, 3, 'Студенты', false, now()),
          ('{program_id}', 'entry_level', 'Уровень?', '[]'::jsonb, 4, 'Базовый', false, now());
        INSERT INTO clarification (program_id, slot, question, options, ord, answer)
        VALUES ('{program_id}', 'schedule', 'Уточните график занятий?', '[]'::jsonb, 5, NULL);
        UPDATE program
        SET profile = jsonb_set(
          jsonb_set(profile, '{{slot_defaults}}', '{{"form": "Очно", "final_attestation": "Тест"}}'::jsonb, true),
          '{{constraints}}', '{{}}'::jsonb, true
        )
        WHERE id = '{program_id}';
        """,
        db=TEST_DB,
    )

    blocked = client.post(f"/api/v1/programs/{program_id}/framework:generate", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "CLARIFICATION_REQUIRED"

    _psql(
        "-c",
        f"""
        UPDATE clarification SET answer = '3 раза в неделю', answered_at = now()
        WHERE program_id = '{program_id}' AND answer IS NULL;
        """,
        db=TEST_DB,
    )
    allowed = client.post(f"/api/v1/programs/{program_id}/framework:generate", headers=headers)
    assert allowed.status_code == 202, allowed.text
