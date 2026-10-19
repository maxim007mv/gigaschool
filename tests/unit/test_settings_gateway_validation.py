"""Тесты валидации шлюза Cloud.ru Foundation Models и ограничений (ЗАД-13)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from karkas.settings import APPROVED_MODELS, RESERVED_EXTRA_BODY_KEYS, Settings


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


@pytest.mark.parametrize(
    "url",
    [
        "https://foundation-models.api.cloud.ru.evil.example/v1",
        "https://foundation-models.api.cloud.ru@evil.example/v1",
        "ftp://foundation-models.api.cloud.ru/v1",
        "foundation-models.api.cloud.ru/v1",
        "",
        "   ",
    ],
)
def test_gateway_url_must_be_absolute_approved_http_url(url: str) -> None:
    """Хост нельзя обойти схемой, userinfo, относительным URL или пустым значением."""
    with pytest.raises(ValueError, match="FM_BASE_URL|Недопустимый хост шлюза"):
        Settings(fm_base_url=url)


def test_gateway_host_is_case_insensitive() -> None:
    s = Settings(fm_base_url="https://HUB.GIGASCHOOL.RU/api/v1/llm/v1")
    assert s.fm_base_url == "https://HUB.GIGASCHOOL.RU/api/v1/llm/v1"


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


@pytest.mark.parametrize("value", [0, 3, 4, 64])
def test_strict_concurrency_limit(value: int) -> None:
    """Попытка задать concurrency вне 1..2 отклоняется валидатором."""
    with pytest.raises(ValueError):
        Settings(llm_concurrency=value)


@pytest.mark.parametrize("value", [0, 4097, 8192])
def test_strict_token_limits(value: int) -> None:
    """max_tokens всегда задан и не превышает 4096; 0 не отключает лимит."""
    with pytest.raises(ValueError):
        Settings(llm_max_output_tokens=value)


def test_allowlist_cannot_expand_approved_models() -> None:
    """MODEL_ALLOWLIST — только сужение, а не обход белого списка."""
    with pytest.raises(ValueError, match="неизвестные модели"):
        Settings(model_allowlist="foreign-model", model_struct="foreign-model")


def test_allowlist_narrows_allowed_models() -> None:
    s = Settings(
        model_struct="GigaChat/GigaChat-3-Pro",
        model_bulk="GigaChat/GigaChat-3-Pro",
        model_embed="",
        model_rerank="",
        model_struct_backup="GigaChat/Reasoning",
        model_allowlist="GigaChat/GigaChat-3-Pro,GigaChat/Reasoning",
    )
    assert set(s.allowed_models) == {"GigaChat/GigaChat-3-Pro", "GigaChat/Reasoning"}


def test_empty_allowlist_values_fall_back_to_configured_models() -> None:
    """Пустые элементы allowlist не отключают защиту и не расширяют список."""
    s = Settings(
        model_allowlist=" , ,, ",
        model_struct="GigaChat/GigaChat-3-Pro",
        model_bulk="GigaChat/GigaChat-3-Pro",
        model_embed="",
        model_rerank="",
        model_struct_backup="GigaChat/Reasoning",
    )
    assert set(s.allowed_models) == {"GigaChat/GigaChat-3-Pro", "GigaChat/Reasoning"}


def test_default_allowlist_includes_backup_models() -> None:
    """Без MODEL_ALLOWLIST резервная модель должна быть вызываемой."""
    s = Settings(
        model_struct="GigaChat/GigaChat-3-Pro",
        model_bulk="GigaChat/GigaChat-3-Pro",
        model_embed="",
        model_rerank="",
        model_struct_backup="GigaChat/Reasoning",
    )
    assert "GigaChat/Reasoning" in s.allowed_models


def test_allowlist_must_contain_configured_primary_model() -> None:
    """Явный allowlist, не содержащий основную модель, — ошибка старта, а не 500 в прогоне."""
    with pytest.raises(ValueError, match="MODEL_STRUCT.*MODEL_ALLOWLIST"):
        Settings(
            model_allowlist="GigaChat/Reasoning",
            model_struct="GigaChat/GigaChat-3-Pro",
            model_bulk="GigaChat/GigaChat-3-Pro",
            model_embed="",
            model_rerank="",
        )


def test_allowlist_must_contain_configured_backup_model() -> None:
    with pytest.raises(ValueError, match="MODEL_STRUCT_BACKUP.*MODEL_ALLOWLIST"):
        Settings(
            model_allowlist="GigaChat/GigaChat-3-Pro",
            model_struct="GigaChat/GigaChat-3-Pro",
            model_bulk="GigaChat/GigaChat-3-Pro",
            model_embed="",
            model_rerank="",
            model_struct_backup="GigaChat/Reasoning",
        )


def test_unknown_backup_model_raises_error() -> None:
    with pytest.raises(ValueError, match="MODEL_STRUCT_BACKUP"):
        Settings(
            model_struct_backup="foreign-model",
            model_struct="GigaChat/GigaChat-3-Pro",
            model_bulk="GigaChat/GigaChat-3-Pro",
            model_embed="",
            model_rerank="",
        )


def test_real_reasoning_model_is_accepted() -> None:
    """Точный id рассуждающей модели из хаба входит в белый список."""
    s = Settings(model_struct="ai-sage/GigaChat3.5-432B-A28B-Reasoning")
    assert s.model_struct == "ai-sage/GigaChat3.5-432B-A28B-Reasoning"


@pytest.mark.parametrize("key", sorted(RESERVED_EXTRA_BODY_KEYS))
def test_extra_body_cannot_override_service_fields(key: str) -> None:
    """LLM_EXTRA_BODY_JSON не должен переопределять model/max_tokens/response_format."""
    with pytest.raises(ValueError, match="служебные поля"):
        Settings(llm_extra_body_json=json.dumps({key: "evil"}))


def test_extra_body_allows_non_service_options() -> None:
    s = Settings(llm_extra_body_json='{"reasoning": {"enabled": false}}')
    assert "reasoning" in s.llm_extra_body_json


def test_reserved_extra_body_covers_max_completion_tokens_alias() -> None:
    assert "max_completion_tokens" in RESERVED_EXTRA_BODY_KEYS
    assert "GigaChat/GigaChat-3-Pro" in APPROVED_MODELS


def test_prod_rejects_placeholder_jwt_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="prod", jwt_secret="change-me-in-prod")


def test_llm_env_aliases_configure_gateway(monkeypatch) -> None:
    """ВМ хакатона задаёт LLM_BASE_URL/LLM_API_KEY: шлюз должен считаться настроенным."""
    from karkas.settings import Settings

    for name in ("FM_BASE_URL", "FM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://hub.gigaschool.ru/api/v1/llm/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    s = Settings(_env_file=None)
    assert s.fm_base_url == "https://hub.gigaschool.ru/api/v1/llm/v1"
    assert s.fm_api_key == "test-key"
