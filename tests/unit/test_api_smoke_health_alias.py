"""Алиасы /api/v1/healthz и /api/v1/readyz."""

from __future__ import annotations

from tests.unit.test_api_smoke import _client


def test_healthz_v1_alias_matches_plain() -> None:
    client = _client()
    plain = client.get("/healthz")
    aliased = client.get("/api/v1/healthz")
    assert plain.status_code == 200 == aliased.status_code
    assert plain.json() == aliased.json()
