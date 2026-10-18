"""karkas.api.sse — поток событий программы (Д4 §6.7).

События: progress, needs_input, framework_ready, kit_ready, edit_applied,
export_ready, job_failed. Каждому событию присваивается монотонный id —
клиент переподключается с Last-Event-ID и не теряет события.

Шина работает в двух режимах:
- in-process (каналы + очереди подписчиков);
- поверх PostgreSQL LISTEN/NOTIFY (`karkas_events`): события, опубликованные
  воркером в другом процессе, доходят до API (Д1 §5). При недоступности БД
  деградирует до in-process без падений.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from karkas.settings import settings


@dataclass
class SseEvent:
    id: int
    event: str
    data: dict[str, Any]


@dataclass
class _ProgramChannel:
    next_id: int = 1
    history: list[SseEvent] = field(default_factory=list)
    subscribers: set[asyncio.Queue[SseEvent]] = field(default_factory=set)

    HISTORY_LIMIT = 200
    QUEUE_LIMIT = 1000

    def push(self, event: str, data: dict[str, Any]) -> SseEvent:
        evt = SseEvent(id=self.next_id, event=event, data=data)
        self.next_id += 1
        self.history.append(evt)
        if len(self.history) > self.HISTORY_LIMIT:
            self.history = self.history[-self.HISTORY_LIMIT :]
        for queue in list(self.subscribers):
            if queue.full():
                # Медленный клиент: роняем самое старое событие, а не копим память.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(evt)
        return evt


class PgNotifyBridge:
    """Мост LISTEN/NOTIFY для межпроцессной доставки событий (воркер → API)."""

    CHANNEL = "karkas_events"
    RECONNECT_COOLDOWN_S = 30.0

    def __init__(self, origin: str, on_event: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self.origin = origin
        self._on_event = on_event
        self._conn: Any | None = None
        self._last_failure = 0.0

    @staticmethod
    def _dsn() -> str:
        return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    async def ensure_started(self) -> None:
        if self._conn is not None:
            return
        if time.monotonic() - self._last_failure < self.RECONNECT_COOLDOWN_S:
            return
        try:
            import asyncpg

            self._conn = await asyncpg.connect(self._dsn())
            await self._conn.add_listener(self.CHANNEL, self._handle)
        except Exception:
            self._conn = None
            self._last_failure = time.monotonic()

    def _handle(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict) or data.get("origin") == self.origin:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._on_event(data))

    async def notify(self, payload: dict[str, Any]) -> None:
        await self.ensure_started()
        if self._conn is None:
            return
        try:
            # Соединение живёт в своём loop; страховочный таймаут не даёт
            # подвесить publish при кросс-loop вызове или мёртвом сокете.
            await asyncio.wait_for(
                self._conn.execute(
                    "SELECT pg_notify($1, $2)",
                    self.CHANNEL,
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
                timeout=5.0,
            )
        except Exception:
            conn = self._conn
            self._conn = None
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.terminate()  # sync, безопасно из любого потока
            self._last_failure = time.monotonic()

    async def close(self) -> None:
        """Закрыть мост. terminate() — синхронный: безопасен из любого event loop."""
        conn = self._conn
        self._conn = None
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.terminate()


class EventBus:
    """Шина событий: in-process каналы + (опционально) LISTEN/NOTIFY."""

    def __init__(self) -> None:
        self._channels: dict[str, _ProgramChannel] = {}
        self._lock = asyncio.Lock()
        self._origin = uuid.uuid4().hex
        self._bridge = PgNotifyBridge(self._origin, self._on_remote)
        self._remote_enabled = True

    def _channel(self, program_id: str) -> _ProgramChannel:
        return self._channels.setdefault(program_id, _ProgramChannel())

    async def publish(self, program_id: str | None, event: str, data: dict[str, Any]) -> None:
        if program_id is None:
            return
        async with self._lock:
            self._channel(program_id).push(event, data)
        if self._remote_enabled:
            await self._bridge.notify({"origin": self._origin, "program_id": program_id, "event": event, "data": data})

    async def _on_remote(self, payload: dict[str, Any]) -> None:
        program_id = str(payload.get("program_id") or "")
        event = str(payload.get("event") or "progress")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if not program_id:
            return
        async with self._lock:
            self._channel(program_id).push(event, data)

    async def subscribe(self, program_id: str, last_event_id: int | None = None) -> AsyncIterator[SseEvent]:
        """Подписка: сначала догоняем пропущенное (Last-Event-ID), затем живые события."""
        queue: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=_ProgramChannel.QUEUE_LIMIT)
        async with self._lock:
            channel = self._channel(program_id)
            missed = [e for e in channel.history if last_event_id is None or e.id > last_event_id]
            channel.subscribers.add(queue)
        await self._bridge.ensure_started()  # события из других процессов (worker → api)
        try:
            for evt in missed:
                yield evt
            while True:
                yield await queue.get()
        finally:
            async with self._lock:
                channel = self._channels.get(program_id)
                if channel is not None:
                    channel.subscribers.discard(queue)

    async def close(self) -> None:
        """Закрыть мост LISTEN/NOTIFY (graceful shutdown, тесты)."""
        await self._bridge.close()

    def disable_remote(self) -> None:
        """Отключить межпроцессную доставку (тесты, окружение без БД)."""
        self._remote_enabled = False


bus = EventBus()

# Graceful shutdown: шина закрывает LISTEN/NOTIFY-мост через lifecycle-хук,
# не создавая зависимости infra → api.
from karkas.infra.lifecycle import register_shutdown_hook  # noqa: E402

register_shutdown_hook(bus.close)


def format_sse(evt: SseEvent) -> str:
    """Сериализация события в text/event-stream."""
    payload = json.dumps(evt.data, ensure_ascii=False)
    return f"id: {evt.id}\nevent: {evt.event}\ndata: {payload}\n\n"
