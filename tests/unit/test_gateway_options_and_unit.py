"""Опции запроса LLM (extra_body, max_tokens), ключ кэша и явная кратность занятия."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from karkas.agent.llm_gateway import LlmGateway
from karkas.agent.pipeline import _constraints_dict
from karkas.settings import Settings


class Out(BaseModel):
    name: str
    n: int


class _RecordingCompletions:
    def __init__(self) -> None:
        self.kwargs: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> dict[str, Any]:
        self.kwargs.append(kwargs)
        return {
            "choices": [{"message": {"content": '{"name": "a", "n": 1}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        }


class _RecordingClient:
    def __init__(self) -> None:
        self.chat = type("Chat", (), {})()
        self.chat.completions = _RecordingCompletions()


def _settings(**overrides: Any) -> Settings:
    base = dict(
        environment="test",
        fm_api_key="k",
        model_struct="m-struct",
        model_bulk="m-bulk",
        llm_cache_ttl_h=1,
        llm_max_repairs=0,
    )
    base.update(overrides)
    return Settings(**base)


async def _call(gateway: LlmGateway) -> None:
    await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)


async def test_extra_body_and_max_tokens_sent_when_configured() -> None:
    client = _RecordingClient()
    settings = _settings(
        llm_extra_body_json='{"reasoning": {"enabled": false}}',
        llm_max_output_tokens=777,
    )
    gateway = LlmGateway(client=client, settings=settings)
    await _call(gateway)
    sent = client.chat.completions.kwargs[0]
    assert sent["extra_body"] == {"reasoning": {"enabled": False}}
    assert sent["max_tokens"] == 777


async def test_default_max_tokens_is_always_sent() -> None:
    client = _RecordingClient()
    gateway = LlmGateway(client=client, settings=_settings())
    await _call(gateway)
    sent = client.chat.completions.kwargs[0]
    assert sent["max_tokens"] == 4096  # лимит хаба не отключается конфигом
    assert "extra_body" not in sent


async def test_gateway_filters_reserved_extra_body_keys() -> None:
    """Даже если настройку поменяли в обход валидатора, служебные поля не уходят."""
    client = _RecordingClient()
    settings = _settings()
    settings.llm_extra_body_json = '{"max_tokens": 99999, "model": "evil", "reasoning": {"enabled": false}}'
    gateway = LlmGateway(client=client, settings=settings)
    await _call(gateway)
    sent = client.chat.completions.kwargs[0]
    assert sent["max_tokens"] == 4096
    assert sent["extra_body"] == {"reasoning": {"enabled": False}}


def test_explicit_unit_is_passed_as_is() -> None:
    # Кратность задаёт методист (API/UI): солвер получает её без подмены.
    program = {"total_hours": 16, "final_att_hours": 2, "constraints": {"unit_hours": 4}}
    assert _constraints_dict(program, {})["unit"] == 4


def test_unit_defaults_to_one() -> None:
    assert _constraints_dict({"total_hours": 16}, {})["unit"] == 1


def test_cache_key_changes_with_options_and_is_stable_without() -> None:
    messages = [{"role": "user", "content": "x"}]
    plain = LlmGateway(client=_RecordingClient(), settings=_settings())
    tuned = LlmGateway(
        client=_RecordingClient(),
        settings=_settings(llm_extra_body_json='{"reasoning": {"enabled": false}}'),
    )
    key_plain = plain._cache_key("m", Out, messages, 0.1, "struct")
    assert key_plain == plain._cache_key("m", Out, messages, 0.1, "struct")
    assert key_plain != tuned._cache_key("m", Out, messages, 0.1, "struct")


@pytest.mark.parametrize("bad", ["[]", "5", "{oops"])
def test_extra_body_must_be_json_object(bad: str) -> None:
    with pytest.raises(ValueError):
        _settings(llm_extra_body_json=bad)
