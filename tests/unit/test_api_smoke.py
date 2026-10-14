"""Дымовые тесты API: приложение собирается, health работает, ошибки — problem+json.

Эти тесты не требуют БД и LLM (не ходят в сеть).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from karkas.api.main import create_app

    return TestClient(create_app(), raise_server_exceptions=False)


def test_app_imports_and_healthz() -> None:
    client = _client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_available() -> None:
    client = _client()
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/agent/run" in paths
    assert "/api/v1/programs" in paths
    assert "/api/v1/programs/{program_id}/framework:approve" in paths


def test_unauthorized_is_problem_json() -> None:
    client = _client()
    response = client.get("/api/v1/programs")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["code"] == "UNAUTHORIZED"
    assert body["status"] == 401


def test_invalid_api_key_rejected() -> None:
    client = _client()
    response = client.get("/api/v1/programs", headers={"X-Api-Key": "invalid-key-123"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_unknown_route_is_404() -> None:
    client = _client()
    response = client.get("/api/v1/nope")
    assert response.status_code == 404
