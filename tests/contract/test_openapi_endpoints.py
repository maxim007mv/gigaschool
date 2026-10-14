"""Контрактный тест: все эндпоинты из таблицы Д4 §6.2 присутствуют в OpenAPI.

Это трассировка «спецификация → реализация»: если эндпоинт потеряется,
тест укажет конкретный путь.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

#: (метод, путь) — таблица эндпоинтов Д4 §6.2.
EXPECTED_ENDPOINTS: list[tuple[str, str]] = [
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/refresh"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/me"),
    ("post", "/api/v1/files"),
    ("get", "/api/v1/files/{file_id}"),
    ("post", "/api/v1/programs"),
    ("get", "/api/v1/programs"),
    ("get", "/api/v1/programs/{program_id}"),
    ("patch", "/api/v1/programs/{program_id}"),
    ("delete", "/api/v1/programs/{program_id}"),
    ("get", "/api/v1/programs/{program_id}/questions"),
    ("post", "/api/v1/programs/{program_id}/answers"),
    ("post", "/api/v1/programs/{program_id}/framework:generate"),
    ("get", "/api/v1/programs/{program_id}/framework"),
    ("patch", "/api/v1/programs/{program_id}/framework"),
    ("post", "/api/v1/programs/{program_id}/framework:rebalance"),
    ("post", "/api/v1/programs/{program_id}/framework:validate"),
    ("post", "/api/v1/programs/{program_id}/framework:approve"),
    ("post", "/api/v1/programs/{program_id}/framework:reopen"),
    ("post", "/api/v1/programs/{program_id}/kit:generate"),
    ("get", "/api/v1/programs/{program_id}/kit"),
    ("get", "/api/v1/programs/{program_id}/kit/items/{ref}"),
    ("post", "/api/v1/programs/{program_id}/edits"),
    ("get", "/api/v1/programs/{program_id}/edits/{edit_id}"),
    ("get", "/api/v1/programs/{program_id}/report"),
    ("post", "/api/v1/programs/{program_id}/exports"),
    ("get", "/api/v1/exports/{export_id}"),
    ("get", "/api/v1/programs/{program_id}/versions"),
    ("get", "/api/v1/programs/{program_id}/versions/{version}/diff"),
    ("post", "/api/v1/programs/{program_id}/versions/{version}:restore"),
    ("post", "/api/v1/programs/{program_id}:actualize"),
    ("post", "/api/v1/programs/{program_id}:adapt"),
    ("get", "/api/v1/jobs/{job_id}"),
    ("post", "/api/v1/jobs/{job_id}:cancel"),
    ("get", "/api/v1/programs/{program_id}/events"),
    ("post", "/api/v1/kb/documents"),
    ("get", "/api/v1/kb/documents"),
    ("delete", "/api/v1/kb/documents/{doc_id}"),
    ("get", "/api/v1/registry/prof-standards"),
    ("get", "/api/v1/registry/prof-standards/{code}/labor-functions"),
    ("get", "/api/v1/registry/normative-acts"),
    ("get", "/api/v1/programs/{program_id}/usage"),
    ("post", "/api/v1/agent/run"),
    ("get", "/api/v1/agent/runs/{run_id}"),
    ("get", "/healthz"),
    ("get", "/readyz"),
    ("get", "/metrics"),
]


def _schema() -> dict:
    from karkas.api.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    return response.json()


def test_all_spec_endpoints_exist() -> None:
    paths = _schema()["paths"]
    missing: list[str] = []
    for method, path in EXPECTED_ENDPOINTS:
        if path not in paths or method not in paths[path]:
            missing.append(f"{method.upper()} {path}")
    assert missing == [], f"Нет эндпоинтов из Д4 §6.2: {missing}"


def test_no_unexpected_v1_paths() -> None:
    """Обратная проверка: в v1 нет путей вне каталога (защита от дублей/опечаток)."""
    paths = set(_schema()["paths"])
    expected = {path for _, path in EXPECTED_ENDPOINTS}
    extra = {p for p in paths if p.startswith("/api/v1")} - expected
    assert extra == set(), f"Лишние пути в /api/v1: {sorted(extra)}"


def test_agent_run_response_contract() -> None:
    """Схема ответа POST /agent/run содержит run_id, status, kit, artifacts (Д4 §6.6)."""
    schema = _schema()
    operation = schema["paths"]["/api/v1/agent/run"]["post"]
    ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    model_name = ref.rsplit("/", 1)[-1]
    model = schema["components"]["schemas"][model_name]
    for field in ("run_id", "status", "questions", "kit", "report", "artifacts", "timings", "usage"):
        assert field in model["properties"], f"В ответе /agent/run нет поля {field}"
