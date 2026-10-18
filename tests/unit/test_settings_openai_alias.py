"""OPENAI_* на ВМ хакатона читаются как FM_* (шлюз Cloud.ru)."""

from __future__ import annotations

from karkas.settings import Settings


def test_fm_env_still_works(monkeypatch) -> None:
    monkeypatch.setenv("FM_API_KEY", "fm-only")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert Settings().fm_api_key == "fm-only"


def test_openai_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("FM_BASE_URL", raising=False)
    monkeypatch.delenv("FM_API_KEY", raising=False)
    s = Settings()
    assert s.fm_base_url == "https://example.invalid/v1"
    assert s.fm_api_key == "test-key"
