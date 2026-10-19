"""Тесты эмбеддингов: батчи, отсутствие Matryoshka-параметра и учёт токенов."""

from __future__ import annotations

from typing import Any

import pytest

import karkas.infra.embeddings as embeddings
from karkas.settings import Settings


class _Response:
    def __init__(self, count: int) -> None:
        self.status_code = 200
        self._count = count
        self.text = ""

    def json(self) -> dict[str, Any]:
        return {
            "data": [{"embedding": [float(index)] * 1024} for index in range(self._count)],
            "usage": {"prompt_tokens": self._count},
        }


class _Client:
    instances: list[_Client] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        self.payloads: list[dict[str, Any]] = []
        _Client.instances.append(self)

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> _Response:
        self.payloads.append(json)
        return _Response(len(json["input"]))


class _Meter:
    def __init__(self) -> None:
        self.records: list[tuple[Any, ...]] = []

    async def record(self, *args: Any) -> None:
        self.records.append(args)


@pytest.fixture
def embedding_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    _Client.instances.clear()
    settings = Settings(
        environment="test",
        fm_base_url="https://hub.gigaschool.ru/api/v1/llm/v1",
        fm_api_key="test-key",
        model_embed="ai-sage/Giga-Embeddings-instruct-3B",
    )
    monkeypatch.setattr(embeddings, "settings", settings)
    monkeypatch.setattr(embeddings.httpx, "AsyncClient", _Client)
    return settings


@pytest.mark.asyncio
async def test_embeddings_process_all_batches_and_omit_dimensions(
    embedding_settings: Settings,
) -> None:
    assert embedding_settings.model_embed
    meter = _Meter()
    vectors = await embeddings.embed_texts([f"text-{i}" for i in range(20)], batch_size=16, meter=meter)

    assert len(vectors) == 20
    assert all(len(vector) == 1024 for vector in vectors)
    client = _Client.instances[0]
    assert len(client.payloads) == 2
    assert all("dimensions" not in payload for payload in client.payloads)
    assert [payload["input"] for payload in client.payloads] == [
        [f"text-{i}" for i in range(16)],
        [f"text-{i}" for i in range(16, 20)],
    ]
    assert len(meter.records) == 2
    assert sum(record[2] for record in meter.records) == 20
