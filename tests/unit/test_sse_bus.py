"""Тесты SSE-шины и токена для EventSource (без HTTP-стримов — их подвешивает TestClient)."""

from __future__ import annotations

import asyncio

import pytest

from karkas.api.sse import EventBus, SseEvent, _ProgramChannel, format_sse


@pytest.fixture(autouse=True)
def _no_pg_bridge(monkeypatch):
    """Юнит-тесты не ходят в PostgreSQL: отключаем межпроцессный мост и удлиняем JWT-секрет."""
    from karkas.api import sse
    from karkas.settings import settings

    monkeypatch.setattr(sse.bus, "_remote_enabled", False)
    monkeypatch.setattr(settings, "jwt_secret", "unit-test-secret-unit-test-secret-32b")
    yield


def test_format_sse() -> None:
    line = format_sse(SseEvent(id=7, event="progress", data={"step": "S08", "done": 1}))
    assert line.startswith("id: 7\nevent: progress\n")
    assert '"step": "S08"' in line
    assert line.endswith("\n\n")


async def test_publish_subscribe_and_replay() -> None:
    bus = EventBus()
    bus.disable_remote()
    await bus.publish("p1", "progress", {"step": "S01"})
    await bus.publish("p1", "progress", {"step": "S02"})

    # Подписка без Last-Event-ID получает историю
    received: list[SseEvent] = []
    stream = bus.subscribe("p1")
    for _ in range(2):
        received.append(await anext(stream))
    assert [e.data["step"] for e in received] == ["S01", "S02"]
    assert [e.id for e in received] == [1, 2]

    # Last-Event-ID=1 пропускает первое событие
    stream2 = bus.subscribe("p1", last_event_id=1)
    event = await anext(stream2)
    assert event.id == 2
    await stream2.aclose()
    await stream.aclose()


async def test_live_events_after_replay() -> None:
    bus = EventBus()
    bus.disable_remote()
    stream = bus.subscribe("p2")
    publish_task = asyncio.create_task(bus.publish("p2", "kit_ready", {"version": 3}))
    event = await asyncio.wait_for(anext(stream), timeout=2)
    await publish_task
    assert event.event == "kit_ready" and event.data["version"] == 3
    await stream.aclose()


async def test_slow_client_drops_oldest_not_memory() -> None:
    """Медленный клиент: очередь ограничена, старые события вытесняются (без роста памяти)."""
    channel = _ProgramChannel()
    queue: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=3)
    channel.subscribers.add(queue)
    for index in range(6):
        channel.push("progress", {"n": index})
    received = [queue.get_nowait() for _ in range(3)]
    assert [e.data["n"] for e in received] == [3, 4, 5]  # остались последние три
    assert queue.empty()
    assert len(channel.history) == 6  # история для Last-Event-ID не теряется


def test_sse_principal_from_query_token() -> None:
    from karkas.api.deps import create_access_token
    from karkas.api.routers.programs import _sse_principal

    token = create_access_token("u1", "org1", "methodist", "u@test.local")
    principal = _sse_principal(None, token)
    assert principal.user_id == "u1" and principal.org_id == "org1"

    principal_from_header = _sse_principal(f"Bearer {token}", None)
    assert principal_from_header.user_id == "u1"

    from karkas.api.errors import Unauthorized

    with pytest.raises(Unauthorized):
        _sse_principal(None, None)
    with pytest.raises(Unauthorized):
        _sse_principal(None, "not-a-jwt")
