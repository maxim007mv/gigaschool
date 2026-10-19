"""karkas.infra.lifecycle — хуки graceful shutdown без инверсии слоёв.

Инфраструктура не знает об API: модули верхних слоёв (например, SSE-шина)
регистрируют свои shutdown-хуки, а `db.dispose_engine` вызывает их при остановке.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

_hooks: list[Callable[[], Awaitable[None]]] = []


def register_shutdown_hook(hook: Callable[[], Awaitable[None]]) -> None:
    """Зарегистрировать асинхронный хук остановки (вызывается один раз)."""
    _hooks.append(hook)


async def run_shutdown_hooks() -> None:
    """Выполнить все хуки; ошибки не прерывают остановку."""
    for hook in list(_hooks):
        try:
            await hook()
        except (OSError, RuntimeError, TimeoutError, ConnectionError, ValueError, TypeError):
            continue
