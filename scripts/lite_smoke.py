#!/usr/bin/env python3
"""Lite-smoke: поднять SQLite-схему и пройти основные API-шаги без PostgreSQL.

Проверяет именно тот сценарий, который ломался в README:
список программ → создание с Idempotency-Key → каркас → утверждение → версии.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _smoke_kit():
    """Минимальный каркас для проверки репозиториев без LLM."""
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
        Report,
        ReportIssue,
        Source,
        Topic,
        Workload,
    )

    topic = Topic(
        ref="T1.1",
        title="Введение",
        workload=Workload(lecture=5, practice=9, distance=2),
        outcome_refs=["LO1.1"],
        locked=["practice:in_person"],
    )
    kit = KitV1(
        program=ProgramHeader(
            kind="dop",
            title="Lite smoke: Python",
            form="full_time",
            total_hours=16,
            final_attestation=FinalAttestation(form="защита проекта", hours=2),
        ),
        framework=Framework(
            goal="Проверка lite-режима",
            competencies=[
                Competency(
                    ref="C1",
                    title="Основы",
                    outcomes=[Outcome(ref="LO1.1", type="skill", text="Пишет программы")],
                )
            ],
            modules=[Module(ref="M1", number=1, title="Основы", topics=[topic])],
            final_attestation=FinalAttestation(form="защита проекта", hours=2),
            calendar=Calendar(
                weeks=4,
                days=8,
                days_per_week=2,
                max_hours_per_day=2,
                sessions=[
                    CalendarSession(
                        seq=i + 1, week=i // 2 + 1, day=i + 1, topic_ref="T1.1", activity="lecture", hours=2
                    )
                    for i in range(7)
                ]
                + [CalendarSession(seq=8, week=4, day=8, topic_ref=None, activity="final_attestation", hours=2)],
            ),
        ),
        content=Content(
            assessments=[
                Assessment(
                    ref="Q-001",
                    kind="test_question",
                    topic_ref="T1.1",
                    module_ref="M1",
                    stem="Что такое переменная?",
                    qtype="single",
                    options=[AssessmentOption(id="a", text="Ячейка памяти")],
                    answer_key=AnswerKey(correct=["a"]),
                    outcome_refs=["LO1.1"],
                )
            ],
            module_programs=[ContentBlock(ref="MP-M1", kind="module_program", module_ref="M1", body={"text": "…"})],
            sources=[
                Source(
                    ref="SRC-01",
                    section="main",
                    citation="Самоучитель Python",
                    status="unverified",
                    evidence={"checked": False},
                    topic_refs=["T1.1"],
                )
            ],
        ),
    )
    report = Report(
        passed=False,
        version=1,
        duration_ms=10,
        summary={"scope": "framework"},
        issues=[
            ReportIssue(
                rule_code="V-SMOKE",
                severity="warning",
                message="Проверка lite",
                fix_hint={"action": "none"},
            )
        ],
    )
    return kit, report


async def _check_persistence() -> bool:
    """Цикл create_program → save_kit → load_kit → report → versions."""
    from karkas.infra.db import get_session_factory
    from karkas.infra.repos import framework as framework_repo
    from karkas.infra.repos import programs as programs_repo
    from migrations.lite import ORG_ID, USER_ID

    kit, report = _smoke_kit()
    ok = True
    async with get_session_factory()() as session:
        program_id = await programs_repo.create_program(
            session, org_id=ORG_ID, owner_id=USER_ID, title="Lite smoke", brief="проверка"
        )
        await framework_repo.save_kit(session, program_id, kit)
        await framework_repo.save_report(session, program_id, 1, report)
        version = await programs_repo.save_version(
            session,
            program_id=program_id,
            reason="lite_smoke",
            snapshot=kit.model_dump(mode="json"),
            created_by=USER_ID,
        )
        await session.commit()

        loaded = await framework_repo.load_kit(session, program_id)
        checks = [
            ("каркас: программа", loaded is not None and loaded.program.title == kit.program.title),
            ("каркас: часы", loaded is not None and loaded.grand_total() == 16),
            (
                "каркас: тема и locked",
                loaded is not None and loaded.framework.modules[0].topics[0].locked == ["practice:in_person"],
            ),
            ("каркас: оценка", loaded is not None and loaded.content.assessments[0].answer_key is not None),
            ("каркас: источник", loaded is not None and loaded.content.sources[0].evidence == {"checked": False}),
            (
                "каркас: календарь",
                loaded is not None
                and loaded.framework.calendar is not None
                and len(loaded.framework.calendar.sessions) == 8,
            ),
        ]

        loaded_report = await framework_repo.load_latest_report(session, program_id)
        checks.append(
            (
                "отчёт: issue/fix_hint",
                loaded_report is not None
                and loaded_report.issues[0].fix_hint == {"action": "none"}
                and loaded_report.issues[0].rule_code == "V-SMOKE",
            )
        )

        versions = await programs_repo.list_versions(session, program_id)
        stored = await programs_repo.get_version(session, program_id, version)
        checks.append(
            (
                "версия: список и снимок",
                [row["version"] for row in versions] == [version]
                and stored is not None
                and isinstance(stored["snapshot"], dict)
                and stored["snapshot"]["program"]["title"] == kit.program.title,
            )
        )

    for label, passed in checks:
        ok &= passed
        print(f"{'OK' if passed else 'FAIL'} {label}")
    return ok


async def _run(db_url: str) -> int:
    os.environ["KARKAS_LITE"] = "1"
    os.environ["DATABASE_URL"] = db_url

    import httpx

    from karkas.api.main import app
    from migrations.lite import apply_lite

    applied = await apply_lite(db_url, include_demo=True)
    print("migrations:", ", ".join(applied))

    demo_id = "00000000-0000-0000-0000-0000000000b1"
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "methodist@acr-demo.example", "password": "demo1234"},
        )
        if login.status_code != 200:
            print(f"FAIL login: {login.status_code} {login.text[:300]}", file=sys.stderr)
            return 1
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        checks: list[tuple[str, int, httpx.Response]] = []

        response = await client.get("/api/v1/programs", headers=headers)
        checks.append(("GET /programs", 200, response))

        response = await client.post(
            "/api/v1/programs",
            headers={**headers, "Idempotency-Key": "lite-smoke-create"},
            json={"brief": "Python 16 часов для школьников", "file_ids": [], "options": {}},
        )
        checks.append(("POST /programs + Idempotency-Key", 202, response))

        response = await client.get(f"/api/v1/programs/{demo_id}/framework", headers=headers)
        checks.append(("GET /framework", 200, response))
        etag = response.headers.get("etag")

        response = await client.post(
            f"/api/v1/programs/{demo_id}/framework:approve",
            headers={**headers, "If-Match": etag or '"0"'},
            json={},
        )
        checks.append(("POST /framework:approve", 200, response))

        response = await client.get(f"/api/v1/programs/{demo_id}/versions", headers=headers)
        checks.append(("GET /versions", 200, response))

        response = await client.get(f"/api/v1/programs/{demo_id}/kit", headers=headers)
        checks.append(("GET /kit до генерации", 404, response))

        response = await client.post(
            "/api/v1/kb/documents",
            headers=headers,
            json={"file_id": "x", "title": "x", "doc_role": "other"},
        )
        checks.append(("KB в lite отключена", 403, response))

    failed = False
    for label, expected, response in checks:
        ok = response.status_code == expected
        failed |= not ok
        print(f"{'OK' if ok else 'FAIL'} {label}: {response.status_code} (ожидался {expected})")
        if not ok:
            print(response.text[:500], file=sys.stderr)

    # Реестры в lite: та же ветка, что использует framework_core перед генерацией.
    # Ловит несовместимый с SQLite SQL и даты-строки (см. migrations/sqlite/003_lite_registry_columns.sql).
    registry_ok = True
    try:
        from karkas.agent.pipeline import _registries_for_inputs
        from karkas.infra.db import get_session_factory

        async with get_session_factory()() as session:
            registries = await _registries_for_inputs(session)
        acts = registries["normative_acts"]
        registry_ok = bool(acts) and all(act["signed_on"] is None or isinstance(act["signed_on"], str) for act in acts)
    except Exception as exc:  # noqa: BLE001 — диагностика lite-ветки
        print(f"FAIL реестры в lite: {exc!r}", file=sys.stderr)
        registry_ok = False
    failed |= not registry_ok
    print(f"{'OK' if registry_ok else 'FAIL'} реестры в lite (framework_core)")

    # Полный цикл репозиториев без LLM: сохранение и повторная загрузка каркаса,
    # отчёта и версии. Ловит SQLite-несовместимости, которые не видны в API-шагах.
    try:
        persistence_ok = await _check_persistence()
    except Exception as exc:  # noqa: BLE001 — диагностика lite-ветки
        print(f"FAIL каркас: сохранение/загрузка: {exc!r}", file=sys.stderr)
        persistence_ok = False
    failed |= not persistence_ok
    print(f"{'OK' if persistence_ok else 'FAIL'} каркас: сохранение/загрузка без LLM")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lite smoke-тест КАРКАС")
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///./var/karkas_lite_smoke.db",
        help="SQLite URL для одноразовой проверки",
    )
    parser.add_argument("--keep-db", action="store_true", help="Не удалять SQLite-файл после проверки")
    args = parser.parse_args(argv)

    db_url = args.db_url
    path = Path(db_url.removeprefix("sqlite+aiosqlite:///"))
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)

    code = asyncio.run(_run(db_url))
    if not args.keep_db and path.exists():
        path.unlink()
    print("lite smoke: OK" if code == 0 else "lite smoke: FAILED")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
