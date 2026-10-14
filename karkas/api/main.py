"""karkas.api.main — сборка FastAPI-приложения (Д4 §2, §6).

Запуск: uvicorn karkas.api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI

from karkas import __version__
from karkas.api.errors import register_error_handlers
from karkas.logging_setup import configure_logging
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
from karkas.settings import settings


def create_app() -> FastAPI:
    """Фабрика приложения (используется тестами и uvicorn)."""
    configure_logging()
    app = FastAPI(
        title="КАРКАС API",
        description="ИИ-агент проектирования образовательных программ: каркас → Human Gate → комплект",
        version=__version__,
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/v1/docs",
        redoc_url=None,
    )

    register_error_handlers(app)

    # Инфраструктурные эндпоинты — без версии и аутентификации.
    app.include_router(health.router)

    # API v1.
    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(auth.me_router, prefix=api_prefix)
    app.include_router(files.router, prefix=api_prefix)
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

    return app


app = create_app()
