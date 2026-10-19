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
