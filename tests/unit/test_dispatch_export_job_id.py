"""Регрессия: export-задача передаёт id джоба в export_core (иначе NameError job_id)."""

from __future__ import annotations

import asyncio
from typing import Any

from karkas.agent import pipeline


class _FakeSession:
    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def commit(self) -> None:
        return None


def test_dispatch_export_passes_job_id(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    monkeypatch.setattr(pipeline, "get_session_factory", lambda: (lambda: _FakeSession()))

    async def fake_export(
        session: Any,
        program_id: str,
        formats: list[str],
        *,
        progress_cb: Any = None,
        gateway: Any = None,
        export_id: str | None = None,
    ) -> dict[str, Any]:
        seen["export_id"] = export_id
        seen["program_id"] = program_id
        seen["formats"] = formats
        return {}

    monkeypatch.setattr(pipeline, "export_core", fake_export)

    job_id = "11111111-1111-1111-1111-111111111111"
    program_id = "22222222-2222-2222-2222-222222222222"
    asyncio.run(
        pipeline.dispatch_job(
            {
                "id": job_id,
                "kind": "export",
                "program_id": program_id,
                "payload": {"formats": ["docx", "gift"]},
            }
        )
    )

    assert seen["export_id"] == job_id
    assert seen["program_id"] == program_id
    assert seen["formats"] == ["docx", "gift"]
