"""Регрессия: параллельные pg_notify на одном asyncpg-соединении не валят job экспорта."""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import pytest

from karkas.api.sse import PgNotifyBridge


class _ExclusiveConn:
    """Имитация asyncpg: параллельная операция на соединении -> InterfaceError."""

    def __init__(self) -> None:
        self.busy = False
        self.calls = 0

    async def execute(self, *_args: Any) -> None:
        if self.busy:
            raise asyncpg.InterfaceError("cannot perform operation: another operation is in progress")
        self.busy = True
        try:
            await asyncio.sleep(0.01)
            self.calls += 1
        finally:
            self.busy = False

    def terminate(self) -> None:  # pragma: no cover - не должен вызываться
        raise AssertionError("terminate() не ожидается при сериализованных notify")


async def _noop(_data: dict[str, Any]) -> None:
    return None


@pytest.mark.asyncio
async def test_parallel_notify_is_serialized() -> None:
    bridge = PgNotifyBridge("test-origin", _noop)
    conn = _ExclusiveConn()
    bridge._conn = conn

    async def _started() -> None:
        return None

    bridge.ensure_started = _started  # type: ignore[method-assign]
    await asyncio.gather(*(bridge.notify({"event": "export_ready", "i": i}) for i in range(5)))
    assert conn.calls == 5
    assert bridge._conn is conn


@pytest.mark.asyncio
async def test_notify_interface_error_is_swallowed() -> None:
    bridge = PgNotifyBridge("test-origin", _noop)

    class _Broken:
        async def execute(self, *_args: Any) -> None:
            raise asyncpg.InterfaceError("connection is closed")

        def terminate(self) -> None:
            return None

    bridge._conn = _Broken()

    async def _started() -> None:
        return None

    bridge.ensure_started = _started  # type: ignore[method-assign]
    await bridge.notify({"event": "export_ready"})  # не должно бросать
    assert bridge._conn is None
