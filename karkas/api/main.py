"""karkas.api.main — сборка FastAPI-приложения (Д4 §2, §6).

Запуск: uvicorn karkas.api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from karkas import __version__
from karkas.api.errors import register_error_handlers
from karkas.api.routers import (
    agent,
    auth,
    clarify,
    files,
    framework,
    health,
    jobs,
    kb,
    kit,
    programs,
    registry,
    usage,
)
from karkas.logging_setup import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Управление жизненным циклом приложения: запуск и корректное закрытие ресурсов."""
    configure_logging()
    yield
    from karkas.infra.db import dispose_engine

    await dispose_engine()


def create_app() -> FastAPI:
    """Фабрика приложения (используется тестами и uvicorn)."""
    import karkas.infra.exporters.bootstrap  # noqa: F401 — регистрация export_program_docx

    app = FastAPI(
        title="КАРКАС API",
        description="ИИ-агент проектирования образовательных программ: каркас → Human Gate → комплект",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    register_error_handlers(app)

    # Инфраструктурные эндпоинты — без версии и аутентификации.
    app.include_router(health.router)
    app.include_router(health.router, prefix="/api/v1")

    # API v1.
    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(auth.me_router, prefix=api_prefix)
    app.include_router(files.router, prefix=api_prefix)
    app.include_router(files.local_storage_router, prefix=api_prefix)
    app.include_router(programs.router, prefix=api_prefix)
    app.include_router(programs.sse_router, prefix=api_prefix)
    app.include_router(clarify.router, prefix=api_prefix)
    app.include_router(framework.router, prefix=api_prefix)
    app.include_router(kit.router, prefix=api_prefix)
    app.include_router(kit.exports_router, prefix=api_prefix)
    app.include_router(kb.router, prefix=api_prefix)
    app.include_router(jobs.router, prefix=api_prefix)
    app.include_router(registry.router, prefix=api_prefix)
    app.include_router(usage.router, prefix=api_prefix)
    app.include_router(agent.router, prefix=api_prefix)

    _maybe_mount_ui(app)
    return app


def _maybe_mount_ui(app: FastAPI) -> None:
    """SPA методиста с того же порта, что и API (хакатон: 0.0.0.0:8000)."""
    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    if not dist.is_dir():
        return
    # html=True — fallback на index.html для client-side routing.
    app.mount("/", StaticFiles(directory=dist, html=True), name="ui")


app = create_app()
