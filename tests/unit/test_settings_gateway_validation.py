"""Тесты валидации шлюза Cloud.ru Foundation Models и ограничений (ЗАД-13)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from karkas.settings import Settings


def test_fm_env_configuration(monkeypatch) -> None:
    monkeypatch.setenv("FM_BASE_URL", "https://foundation-models.api.cloud.ru/v1")
    monkeypatch.setenv("FM_API_KEY", "fm-test-key")
    s = Settings()
    assert s.fm_base_url == "https://foundation-models.api.cloud.ru/v1"
    assert s.fm_api_key == "fm-test-key"


def test_unknown_gateway_host_raises_error(monkeypatch) -> None:
    """Незнакомый хост шлюза даёт ошибку конфигурации."""
    monkeypatch.setenv("FM_BASE_URL", "https://api.unauthorized-provider.com/v1")
    with pytest.raises(ValueError, match="Недопустимый хост шлюза"):
        Settings()


def test_unknown_model_raises_error(monkeypatch) -> None:
    """Незнакомая модель вне белого списка даёт ошибку конфигурации."""
    monkeypatch.setenv("FM_BASE_URL", "https://foundation-models.api.cloud.ru/v1")
    with pytest.raises(ValueError, match="не входит в белый список разрешённых моделей"):
        Settings(model_struct="unauthorized-foreign-model")


def test_approved_models_and_hosts_accepted() -> None:
    """Разрешённые модели GigaChat-3-Pro и Giga-Embeddings принимаются."""
    s = Settings(
        fm_base_url="https://hub.gigaschool.ru/api/v1/llm/v1",
        model_struct="GigaChat/GigaChat-3-Pro",
        model_bulk="GigaChat/GigaChat-3-Pro",
        model_embed="ai-sage/Giga-Embeddings-instruct-3B",
    )
    assert s.model_struct == "GigaChat/GigaChat-3-Pro"
    assert s.llm_concurrency <= 2
    assert s.llm_max_output_tokens <= 4096
    assert s.daily_budget_rub == Decimal("100.0")


def test_strict_concurrency_and_token_limits() -> None:
    """Попытка задать concurrency > 2 или max_tokens > 4096 отклоняется валидатором."""
    with pytest.raises(ValueError):
        Settings(llm_concurrency=4)
    with pytest.raises(ValueError):
        Settings(llm_max_output_tokens=8192)


def test_allowlist_cannot_expand_approved_models() -> None:
    """MODEL_ALLOWLIST — только сужение, а не обход белого списка."""
    with pytest.raises(ValueError, match="неизвестные модели"):
        Settings(model_allowlist="gpt-4", model_struct="gpt-4")


def test_real_reasoning_model_is_accepted() -> None:
    """Точный id рассуждающей модели из хаба входит в белый список."""
    s = Settings(model_struct="ai-sage/GigaChat3.5-432B-A28B-Reasoning")
    assert s.model_struct == "ai-sage/GigaChat3.5-432B-A28B-Reasoning"


def test_extra_body_cannot_override_service_fields() -> None:
    """LLM_EXTRA_BODY_JSON не должен переопределять model/max_tokens/response_format."""
    with pytest.raises(ValueError, match="служебные поля"):
        Settings(llm_extra_body_json='{"model":"gpt-4"}')


def test_prod_rejects_placeholder_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="prod", jwt_secret="change-me-in-prod")
