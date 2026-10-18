"""SQLite lite-режим: схема и демо-сид без PostgreSQL.

    python -m migrations.lite
    python -m migrations.lite --demo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

SQLITE_DIR = Path(__file__).resolve().parent / "sqlite"
LITE_SQL = SQLITE_DIR / "001_lite.sql"

ORG_ID = "00000000-0000-0000-0000-0000000000a1"
USER_ID = "00000000-0000-0000-0000-0000000000a2"
DEMO_PROGRAM_ID = "00000000-0000-0000-0000-0000000000b1"


def _demo_password_hash() -> str:
    from argon2 import PasswordHasher

    return PasswordHasher().hash("demo1234")


async def apply_lite(database_url: str, *, include_demo: bool = False) -> list[str]:
    """Применить lite-схему и базовый сид. Возвращает список шагов."""
    applied: list[str] = []
    engine = create_async_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    digest = hashlib.sha256(LITE_SQL.read_bytes()).digest()
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    sha256 BLOB NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
        )
        row = (
            await conn.execute(
                text("SELECT sha256 FROM schema_migrations WHERE filename = :f"),
                {"f": LITE_SQL.name},
            )
        ).first()
        if row is None:
            script = LITE_SQL.read_text(encoding="utf-8")
            for chunk in script.split(";"):
                stmt = chunk.strip()
                if stmt and not stmt.startswith("PRAGMA"):
                    await conn.execute(text(stmt))
            await conn.execute(
                text("INSERT INTO schema_migrations (filename, sha256) VALUES (:f, :d)"),
                {"f": LITE_SQL.name, "d": digest},
            )
            applied.append(LITE_SQL.name)
        await _seed_core(conn)
        applied.append("seed_core")
        if include_demo:
            await _seed_demo_program(conn)
            applied.append("demo_program")
    await engine.dispose()
    return applied


async def _seed_core(conn) -> None:  # type: ignore[no-untyped-def]
    exists = (
        await conn.execute(text("SELECT 1 FROM organization WHERE id = :id"), {"id": ORG_ID})
    ).first()
    if exists:
        return
    await conn.execute(
        text("INSERT INTO organization (id, name) VALUES (:id, :name)"),
        {"id": ORG_ID, "name": "Академия цифрового развития (демо)"},
    )
    await conn.execute(
        text(
            """
            INSERT INTO app_user (id, org_id, email, display_name, role, password_hash)
            VALUES (:id, :org, :email, :name, 'methodist', :ph)
            """
        ),
        {
            "id": USER_ID,
            "org": ORG_ID,
            "email": "methodist@acr-demo.example",
            "name": "Методист АЦР (демо)",
            "ph": _demo_password_hash(),
        },
    )
    acts = [
        (
            str(uuid.uuid4()),
            "federal_law",
            "Российская Федерация",
            "273-ФЗ",
            "2012-12-29",
            "Об образовании в Российской Федерации",
        ),
        (
            str(uuid.uuid4()),
            "order",
            "Минпросвещения России",
            "629",
            "2022-07-27",
            "Порядок ДОП (приказ № 629)",
        ),
    ]
    for act_id, kind, issuer, number, signed_on, title in acts:
        await conn.execute(
            text(
                """
                INSERT INTO normative_act (id, kind, issuer, number, signed_on, title, verified_by, verified_on)
                VALUES (:id, :kind, :issuer, :number, :signed_on, :title, 'lite-seed', date('now'))
                """
            ),
            {
                "id": act_id,
                "kind": kind,
                "issuer": issuer,
                "number": number,
                "signed_on": signed_on,
                "title": title,
            },
        )
    ps_id = str(uuid.uuid4())
    await conn.execute(
        text(
            """
            INSERT INTO prof_standard (id, code, title, source)
            VALUES (:id, '06.015', 'Специалист по информационным системам', 'lite-seed')
            """
        ),
        {"id": ps_id},
    )
    await conn.execute(
        text(
            """
            INSERT INTO labor_function (id, prof_standard_id, otf_code, code, title, qual_level)
            VALUES (:id, :ps, 'C', 'C/14.6', 'Разработка архитектуры ИС', 6)
            """
        ),
        {"id": str(uuid.uuid4()), "ps": ps_id},
    )


async def _seed_demo_program(conn) -> None:  # type: ignore[no-untyped-def]
    exists = (
        await conn.execute(text("SELECT 1 FROM program WHERE id = :id"), {"id": DEMO_PROGRAM_ID})
    ).first()
    if exists:
        return
    profile = json.dumps(
        {"audience": "Специалисты, начинающие работу в ИТ", "entry_level": "начальный", "demo": True},
        ensure_ascii=False,
    )
    await conn.execute(
        text(
            """
            INSERT INTO program (id, org_id, owner_id, title, kind, form, total_hours, final_att_hours,
                                 final_att_form, status, profile, constraints, goal)
            VALUES (:id, :org, :owner, :title, 'dpp_pk', 'distance', 16, 2,
                    'Защита мини-проекта', 'framework_review', :profile, '{}',
                    'Демо: каркас для проверки часов в UI')
            """
        ),
        {
            "id": DEMO_PROGRAM_ID,
            "org": ORG_ID,
            "owner": USER_ID,
            "title": "Демо: Python для школьников (16 ч)",
            "profile": profile,
        },
    )
    mod_id = str(uuid.uuid4())
    await conn.execute(
        text(
            """
            INSERT INTO module (id, program_id, ref, number, title, weight)
            VALUES (:id, :pid, 'M1', 1, 'Основы Python', 1)
            """
        ),
        {"id": mod_id, "pid": DEMO_PROGRAM_ID},
    )
    topics = [
        ("T1.1", 1, "Введение и переменные", 6),
        ("T1.2", 2, "Условия и циклы", 8),
    ]
    for ref, num, title, hours in topics:
        tid = str(uuid.uuid4())
        await conn.execute(
            text(
                """
                INSERT INTO topic (id, program_id, module_id, ref, number, title, weight, practicality)
                VALUES (:id, :pid, :mid, :ref, :num, :title, 1, 0.6)
                """
            ),
            {"id": tid, "pid": DEMO_PROGRAM_ID, "mid": mod_id, "ref": ref, "num": num, "title": title},
        )
        await conn.execute(
            text(
                """
                INSERT INTO topic_workload (topic_id, activity, mode, hours)
                VALUES (:tid, 'practice', 'in_person', :h)
                """
            ),
            {"tid": tid, "h": hours},
        )


def main() -> None:
    from karkas.settings import settings

    parser = argparse.ArgumentParser(description="КАРКАС lite (SQLite)")
    parser.add_argument("--demo", action="store_true", help="демо-программа в каркасе")
    parser.add_argument("--db-url", default=None, help="sqlite+aiosqlite:///…")
    args = parser.parse_args()
    url = args.db_url or settings.database_url
    if not url.startswith("sqlite"):
        raise SystemExit("lite-миграции только для sqlite+aiosqlite (задайте KARKAS_LITE=1 или DATABASE_URL)")
    import asyncio

    steps = asyncio.run(apply_lite(url, include_demo=args.demo))
    print("Lite:", ", ".join(steps) if steps else "уже актуально")


if __name__ == "__main__":
    main()
