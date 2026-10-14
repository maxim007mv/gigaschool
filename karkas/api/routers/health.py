"""karkas.api.routers.health — /healthz, /readyz, /metrics (Д4 §6.2)."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from karkas.infra.db import ping
from karkas.settings import settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Живость процесса."""
    return {"status": "ok", "app": settings.app_name}


@router.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Готовность: БД отвечает, конфигурация LLM заполнена."""
    db_ok = await ping()
    llm_ok = bool(settings.fm_api_key and settings.allowed_models)
    ready = db_ok and llm_ok
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "db": db_ok,
        "llm_configured": llm_ok,
    }


@router.get("/metrics")
async def metrics() -> Response:
    """Метрики Prometheus."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
