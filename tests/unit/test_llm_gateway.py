"""Тесты LLM-шлюза (Д1 §7): allowlist, кэш, ремонт JSON, ретраи, предохранитель, параллелизм."""

from __future__ import annotations

import asyncio
import time
from decimal import Decimal

import pytest
from pydantic import BaseModel

from karkas.agent.llm_gateway import (
    CircuitOpenError,
    CloudRuFMClient,
    CloudRuHttpError,
    DailyBudgetExceededError,
    LlmBadOutput,
    LlmGateway,
    LlmRequestError,
    ModelNotAllowedError,
    TransientError,
)
from karkas.agent.skills._base import InMemoryCache
from karkas.settings import Settings


class Out(BaseModel):
    """Тестовая схема ответа навыка."""

    name: str
    n: int


class ApiError(Exception):
    """Ошибка провайдера с HTTP-статусом (эмулирует CloudRuHttpError)."""

    def __init__(self, status: int, message: str | None = None) -> None:
        super().__init__(message or f"HTTP {status}")
        self.status_code = status


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str, finish_reason: str) -> None:
        self.message = _Message(content)
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, content: str, finish_reason: str) -> None:
        self.choices = [_Choice(content, finish_reason)]
        self.usage = _Usage(10, 5)


class _FakeCompletions:
    def __init__(self, client: FakeClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        response_format: dict | None = None,
        **kwargs: object,
    ) -> _Response:
        return await self._client.create(model, messages, temperature, response_format, **kwargs)


class _FakeChat:
    def __init__(self, client: FakeClient) -> None:
        self.completions = _FakeCompletions(client)


class _ConcurrencyTracker:
    """Общий счётчик одновременных вызовов для нескольких клиентов."""

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0


class FakeClient:
    """HTTP-клиент Cloud.ru FM, отвечающий по сценарию.

    Элемент сценария: строка (content), (content, finish_reason),
    Exception (будет брошено) или async-функция (model, messages, temperature).
    """

    def __init__(
        self, script: list | None = None, *, delay: float = 0.0, tracker: _ConcurrencyTracker | None = None
    ) -> None:
        self.script = list(script or [])
        self.calls: list[dict] = []
        self.active = 0
        self.max_active = 0
        self._tracker = tracker
        self.delay = delay
        self.chat = _FakeChat(self)

    async def create(
        self,
        model: str,
        messages: list[dict],
        temperature: float,
        response_format: dict | None,
        **kwargs: object,
    ) -> _Response:
        self.active += 1
        if self._tracker is None:
            self.max_active = max(self.max_active, self.active)
        else:
            self._tracker.active += 1
            self._tracker.max_active = max(self._tracker.max_active, self._tracker.active)
        try:
            self.calls.append(
                {
                    "model": model,
                    "messages": [dict(m) for m in messages],
                    "temperature": temperature,
                    "response_format": response_format,
                    **kwargs,
                }
            )
            if self.delay:
                await asyncio.sleep(self.delay)
            action = self.script.pop(0) if self.script else None
            if callable(action):
                action = await action(model, messages, temperature)
            if isinstance(action, BaseException):
                raise action
            if action is None:
                raise AssertionError("FakeClient: сценарий исчерпан")
            content, finish_reason = action if isinstance(action, tuple) else (action, "stop")
            return _Response(content, finish_reason)
        finally:
            self.active -= 1
            if self._tracker is not None:
                self._tracker.active -= 1


class FakeMeter:
    """Записывает все вызовы meter.record (проверка учёта и cache_hit)."""

    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record(
        self,
        skill: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        ok: bool,
        cache_hit: bool,
    ) -> None:
        self.records.append(
            {
                "skill": skill,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "ok": ok,
                "cache_hit": cache_hit,
            }
        )


class NoCache:
    """Кэш-заглушка (для тестов параллелизма и ретраев)."""

    async def get(self, key: str) -> dict | None:
        return None

    async def put(self, key: str, value: dict, ttl_s: float | None = None) -> None:
        return None


async def noop_sleep(_delay: float) -> None:
    return None


def make_settings(**overrides) -> Settings:
    base = dict(
        environment="test",
        fm_api_key="test-key",
        model_struct="model-struct",
        model_bulk="model-bulk",
        model_allowlist="model-struct,model-bulk,model-backup",
        llm_concurrency=2,
        llm_timeout_s=5,
        llm_cache_ttl_h=1,
        llm_max_repairs=2,
        llm_backoff_base_s=1.0,
        llm_circuit_failures=5,
        llm_circuit_window_s=30,
        llm_circuit_cooldown_s=20,
    )
    base.update(overrides)
    return Settings(**base)


def make_gateway(client: FakeClient, meter: FakeMeter | None = None, **overrides) -> LlmGateway:
    return LlmGateway(
        client=client,
        meter=meter if meter is not None else FakeMeter(),
        settings=make_settings(**overrides),
        sleep=noop_sleep,
    )


class _FakeHttpResponse:
    def __init__(self, status_code: int, text: str = "", payload: object = None) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class _FakeAsyncClient:
    """Подмена httpx.AsyncClient: запоминает URL/заголовки/JSON и отдаёт сценарий."""

    instances: list[_FakeAsyncClient] = []
    requests: list[dict] = []
    responses: list[_FakeHttpResponse] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout
        type(self).instances.append(self)

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, *, json: dict, headers: dict) -> _FakeHttpResponse:
        type(self).requests.append({"url": url, "json": json, "headers": headers})
        return type(self).responses.pop(0)


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> type[_FakeAsyncClient]:
    import karkas.agent.llm_gateway as gateway_module

    _FakeAsyncClient.instances = []
    _FakeAsyncClient.requests = []
    _FakeAsyncClient.responses = []
    monkeypatch.setattr(gateway_module.httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


async def test_cloudru_client_posts_expected_request(fake_httpx: type[_FakeAsyncClient]) -> None:
    fake_httpx.responses = [
        _FakeHttpResponse(
            200, '{"choices": []}', {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}
        )
    ]
    client = CloudRuFMClient(
        "https://foundation-models.api.cloud.ru/v1/",
        "secret-key",
        timeout=42,
        max_output_tokens=4096,
    )
    result = await client.chat.completions.create(
        model="GigaChat/GigaChat-3-Pro",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
        response_format={"type": "json_object"},
        max_tokens=1024,
        extra_body={"reasoning": {"enabled": False}},
    )
    assert result["usage"]["prompt_tokens"] == 1
    request = fake_httpx.requests[0]
    assert request["url"] == "https://foundation-models.api.cloud.ru/v1/chat/completions"
    assert request["headers"] == {
        "Authorization": "Bearer secret-key",
        "Content-Type": "application/json",
    }
    assert request["json"] == {
        "model": "GigaChat/GigaChat-3-Pro",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "max_tokens": 1024,
        "reasoning": {"enabled": False},
    }
    assert fake_httpx.instances[0].timeout == 42.0


async def test_cloudru_client_http_error_redacts_key(fake_httpx: type[_FakeAsyncClient]) -> None:
    fake_httpx.responses = [_FakeHttpResponse(400, "bad request, key secret-key leaked")]
    client = CloudRuFMClient("https://foundation-models.api.cloud.ru/v1", "secret-key")
    with pytest.raises(CloudRuHttpError) as excinfo:
        await client.chat.completions.create(model="m", messages=[])
    message = str(excinfo.value)
    assert message.startswith("HTTP 400:")
    assert "bad request" in message
    assert "secret-key" not in message
    assert "***" in message


@pytest.mark.parametrize("status", [200, 400, 502])
async def test_cloudru_client_empty_body_has_clear_error(fake_httpx: type[_FakeAsyncClient], status: int) -> None:
    fake_httpx.responses = [_FakeHttpResponse(status, "")]
    client = CloudRuFMClient("https://foundation-models.api.cloud.ru/v1", "secret-key")
    with pytest.raises(CloudRuHttpError, match="пустой ответ шлюза"):
        await client.chat.completions.create(model="m", messages=[])


async def test_cloudru_client_invalid_json_has_clear_error(fake_httpx: type[_FakeAsyncClient]) -> None:
    fake_httpx.responses = [_FakeHttpResponse(200, "not-json")]
    client = CloudRuFMClient("https://foundation-models.api.cloud.ru/v1", "secret-key")
    with pytest.raises(CloudRuHttpError, match="невалидный JSON"):
        await client.chat.completions.create(model="m", messages=[])


async def test_cloudru_client_extra_body_cannot_override_service_fields(
    fake_httpx: type[_FakeAsyncClient],
) -> None:
    fake_httpx.responses = [_FakeHttpResponse(200, "{}", {})]
    client = CloudRuFMClient("https://foundation-models.api.cloud.ru/v1", "secret-key")
    await client.chat.completions.create(
        model="good-model",
        messages=[{"role": "user", "content": "x"}],
        max_tokens=1000,
        response_format={"type": "json_object"},
        extra_body={
            "model": "evil-model",
            "messages": [{"role": "user", "content": "evil"}],
            "max_tokens": 99999,
            "max_completion_tokens": 99999,
            "response_format": {"type": "text"},
            "temperature": 9.9,
            "stream": True,
            "reasoning": {"enabled": False},
        },
    )
    sent = fake_httpx.requests[0]["json"]
    assert sent["model"] == "good-model"
    assert sent["messages"] == [{"role": "user", "content": "x"}]
    assert sent["max_tokens"] == 1000
    assert sent["response_format"] == {"type": "json_object"}
    assert "temperature" not in sent
    assert "stream" not in sent
    assert "max_completion_tokens" not in sent
    assert sent["reasoning"] == {"enabled": False}


async def test_cloudru_client_clamps_max_tokens(fake_httpx: type[_FakeAsyncClient]) -> None:
    fake_httpx.responses = [_FakeHttpResponse(200, "{}", {}), _FakeHttpResponse(200, "{}", {})]
    client = CloudRuFMClient("https://foundation-models.api.cloud.ru/v1", "secret-key", max_output_tokens=1000)
    await client.chat.completions.create(model="m", messages=[], max_tokens=99999)
    await client.chat.completions.create(model="m", messages=[])
    assert fake_httpx.requests[0]["json"]["max_tokens"] == 1000
    assert fake_httpx.requests[1]["json"]["max_tokens"] == 1000


@pytest.mark.parametrize(
    ("base_url", "api_key", "max_tokens"),
    [
        ("https://evil.example/v1", "key", 4096),
        ("ftp://foundation-models.api.cloud.ru/v1", "key", 4096),
        ("/v1", "key", 4096),
        ("https://foundation-models.api.cloud.ru/v1", "  ", 4096),
        ("https://foundation-models.api.cloud.ru/v1", "key", 0),
        ("https://foundation-models.api.cloud.ru/v1", "key", 5000),
    ],
)
def test_cloudru_client_rejects_unsafe_configuration(base_url: str, api_key: str, max_tokens: int) -> None:
    with pytest.raises(ValueError):
        CloudRuFMClient(base_url, api_key, max_output_tokens=max_tokens)


async def test_valid_answer_first_try() -> None:
    client = FakeClient(['{"name": "a", "n": 1}'])
    meter = FakeMeter()
    gateway = make_gateway(client, meter)
    result = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "hi"}], Out)
    assert isinstance(result, Out) and result.name == "a" and result.n == 1
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "model-struct"
    assert call["temperature"] == pytest.approx(0.15)
    assert call["response_format"] == {"type": "json_object"}
    record = meter.records[-1]
    assert record["ok"] is True and record["cache_hit"] is False
    assert record["prompt_tokens"] == 10 and record["completion_tokens"] == 5
    assert record["skill"] == "S01" and record["model"] == "model-struct"


async def test_temperature_by_class_and_override() -> None:
    client = FakeClient(['{"name": "a", "n": 1}', '{"name": "b", "n": 2}', '{"name": "c", "n": 3}'])
    gateway = make_gateway(client)
    await gateway.complete_json("S01", "struct", [{"role": "user", "content": "1"}], Out)
    await gateway.complete_json("S11", "bulk", [{"role": "user", "content": "2"}], Out)
    await gateway.complete_json("S11", "bulk", [{"role": "user", "content": "3"}], Out, temperature=0.9)
    assert client.calls[0]["model"] == "model-struct"
    assert client.calls[1]["model"] == "model-bulk"
    assert client.calls[0]["temperature"] == pytest.approx(0.15)
    assert client.calls[1]["temperature"] == pytest.approx(0.5)
    assert client.calls[2]["temperature"] == pytest.approx(0.9)


async def test_repair_cycle_second_answer_valid() -> None:
    client = FakeClient(["это не JSON", '{"name": "b", "n": 2}'])
    meter = FakeMeter()
    gateway = make_gateway(client, meter)
    result = await gateway.complete_json("S06", "struct", [{"role": "user", "content": "x"}], Out)
    assert result.name == "b"
    assert len(client.calls) == 2
    repair = client.calls[1]["messages"][-1]
    assert repair["role"] == "user"
    assert "Исправь JSON по схеме" in repair["content"]
    assert meter.records[-1]["ok"] is True


async def test_repair_exhausted_raises_bad_output() -> None:
    client = FakeClient(["мусор", "опять мусор", "и это мусор"])
    gateway = make_gateway(client)  # llm_max_repairs=2 → 3 вызова всего
    with pytest.raises(LlmBadOutput) as excinfo:
        await gateway.complete_json("S06", "struct", [{"role": "user", "content": "x"}], Out)
    assert "Out" in str(excinfo.value)
    assert len(client.calls) == 3


async def test_truncated_answer_is_repaired() -> None:
    client = FakeClient([('{"name": "a", "n"', "length"), '{"name": "a", "n": 1}'])
    gateway = make_gateway(client)
    result = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert result.n == 1
    assert len(client.calls) == 2
    assert "обрезан" in client.calls[1]["messages"][-1]["content"]


async def test_empty_choices_answer_is_repaired() -> None:
    client = FakeClient(["", '{"name": "a", "n": 1}'])
    gateway = make_gateway(client)
    result = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert result.n == 1
    assert len(client.calls) == 2


async def test_cache_hit_does_not_call_client() -> None:
    client = FakeClient(['{"name": "a", "n": 1}'])
    meter = FakeMeter()
    gateway = make_gateway(client, meter)
    messages = [{"role": "user", "content": "одинаковый запрос"}]
    first = await gateway.complete_json("S01", "struct", messages, Out)
    second = await gateway.complete_json("S01", "struct", messages, Out)
    assert first == second
    assert len(client.calls) == 1
    assert meter.records[-1]["cache_hit"] is True
    assert meter.records[-1]["prompt_tokens"] == 0


async def test_cache_key_depends_on_messages() -> None:
    client = FakeClient(['{"name": "a", "n": 1}', '{"name": "b", "n": 2}'])
    gateway = make_gateway(client)
    await gateway.complete_json("S01", "struct", [{"role": "user", "content": "1"}], Out)
    await gateway.complete_json("S01", "struct", [{"role": "user", "content": "2"}], Out)
    assert len(client.calls) == 2


async def test_allowlist_blocks_unknown_model() -> None:
    gateway = LlmGateway(
        client=FakeClient([]),
        settings=make_settings(
            model_struct="model-evil",
            model_allowlist="model-struct,model-bulk",
        ),
        sleep=noop_sleep,
    )
    with pytest.raises(ModelNotAllowedError) as excinfo:
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert "MODEL_ALLOWLIST" in str(excinfo.value)
    assert isinstance(excinfo.value, LlmBadOutput)
    assert isinstance(excinfo.value, ValueError)


async def test_retry_transient_then_success_with_backoff() -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    client = FakeClient([ApiError(429), ApiError(500), '{"name": "ok", "n": 3}'])
    gateway = LlmGateway(client=client, settings=make_settings(), sleep=fake_sleep)
    result = await gateway.complete_json("S05", "struct", [{"role": "user", "content": "x"}], Out)
    assert result.n == 3
    assert len(client.calls) == 3
    assert 0.5 <= sleeps[0] <= 1.5  # base * 2^0 * джиттер
    assert 1.0 <= sleeps[1] <= 3.0  # base * 2^1 * джиттер


async def test_backoff_uses_asyncio_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[float] = []

    async def fake_sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    client = FakeClient([ApiError(429), ApiError(429), '{"name": "a", "n": 1}'])
    gateway = LlmGateway(client=client, settings=make_settings())
    await gateway.complete_json("S05", "struct", [{"role": "user", "content": "x"}], Out)
    assert len(recorded) == 2


async def test_retry_exhausted_raises_transient() -> None:
    client = FakeClient([ApiError(429), ApiError(429), ApiError(429)])
    gateway = make_gateway(client)
    with pytest.raises(TransientError):
        await gateway.complete_json("S05", "struct", [{"role": "user", "content": "x"}], Out)
    assert len(client.calls) == 3


async def test_non_transient_error_is_not_retried() -> None:
    # Отказ именно по response_format: одна проба без JSON-режима, затем ошибка.
    client = FakeClient([ApiError(400, "unknown parameter: response_format"), ApiError(400)])
    gateway = make_gateway(client)
    with pytest.raises(LlmRequestError):
        await gateway.complete_json("S05", "struct", [{"role": "user", "content": "x"}], Out)
    # первая проба с response_format, вторая — без него (модель может его не поддерживать)
    assert len(client.calls) == 2
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    assert client.calls[1]["response_format"] is None


async def test_generic_400_does_not_disable_json_mode() -> None:
    """Обычный 400 (контекст/лимит) не маскируется под «модель без JSON-режима»."""
    client = FakeClient([ApiError(400), '{"name": "a", "n": 1}'])
    gateway = make_gateway(client)
    with pytest.raises(LlmRequestError):
        await gateway.complete_json("S05", "struct", [{"role": "user", "content": "x"}], Out)
    assert len(client.calls) == 1
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    # Флаг не сброшен: следующий вызов снова пробует JSON-режим.
    result = await gateway.complete_json("S05", "struct", [{"role": "user", "content": "y"}], Out)
    assert result.name == "a"
    assert client.calls[1]["response_format"] == {"type": "json_object"}


async def test_json_mode_flag_is_remembered_per_model() -> None:
    client = FakeClient(
        [ApiError(400, "response_format is not supported"), '{"name": "a", "n": 1}', '{"name": "b", "n": 2}']
    )
    gateway = make_gateway(client)
    first = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "1"}], Out)
    second = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "2"}], Out)
    assert first.name == "a" and second.name == "b"
    assert len(client.calls) == 3
    assert client.calls[0]["response_format"] == {"type": "json_object"}
    assert client.calls[1]["response_format"] is None
    assert client.calls[2]["response_format"] is None  # флаг запомнен для модели


async def test_meter_records_every_call() -> None:
    client = FakeClient([ApiError(429), '{"name": "a", "n": 1}'])
    meter = FakeMeter()
    gateway = make_gateway(client, meter)
    await gateway.complete_json("S06", "struct", [{"role": "user", "content": "x"}], Out)
    assert [r["ok"] for r in meter.records] == [False, True]
    assert all(r["cache_hit"] is False for r in meter.records)


async def test_circuit_breaker_opens_and_recloses_after_cooldown() -> None:
    now = [1000.0]
    client = FakeClient([ApiError(429), ApiError(429), ApiError(429), '{"name": "a", "n": 1}'])
    settings = make_settings(llm_circuit_failures=3, llm_circuit_window_s=30, llm_circuit_cooldown_s=20)
    gateway = LlmGateway(client=client, settings=settings, sleep=noop_sleep, clock=lambda: now[0])

    with pytest.raises(TransientError):
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    calls_after_failure = len(client.calls)
    assert calls_after_failure == 3  # предохранитель разомкнут на 3-й ошибке

    with pytest.raises(CircuitOpenError):
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert len(client.calls) == calls_after_failure  # вызова клиента не было

    now[0] += 21  # cooldown истёк
    result = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert result.n == 1
    assert len(client.calls) == calls_after_failure + 1


async def test_circuit_breaker_switches_to_backup_model() -> None:
    now = [0.0]
    primary = FakeClient([ApiError(429), ApiError(429), ApiError(429)])
    backup = FakeClient(['{"name": "backup", "n": 9}'])
    created: list[str] = []

    def factory(model: str):
        created.append(model)
        return backup

    settings = make_settings(
        llm_circuit_failures=3,
        llm_circuit_cooldown_s=100,
        model_allowlist="model-struct,model-bulk,model-backup",
    )
    gateway = LlmGateway(
        client=primary,
        client_factory=factory,
        backup_models={"struct": "model-backup"},
        settings=settings,
        sleep=noop_sleep,
        clock=lambda: now[0],
    )
    with pytest.raises(TransientError):
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    result = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert result.name == "backup"
    assert created == ["model-backup"]
    assert backup.calls[0]["model"] == "model-backup"
    assert len(primary.calls) == 3


async def test_backup_model_works_with_single_default_client() -> None:
    """make_gateway не передаёт client_factory: backup обязан использовать тот же клиент."""
    now = [0.0]
    client = FakeClient([ApiError(429), ApiError(429), ApiError(429), '{"name": "backup", "n": 9}'])
    settings = make_settings(
        llm_circuit_failures=3,
        llm_circuit_cooldown_s=100,
        model_struct_backup="model-backup",
    )
    gateway = LlmGateway(
        client=client,
        backup_models={"struct": "model-backup"},
        settings=settings,
        sleep=noop_sleep,
        clock=lambda: now[0],
    )
    with pytest.raises(TransientError):
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    result = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert result.name == "backup"
    assert client.calls[-1]["model"] == "model-backup"
    assert len(client.calls) == 4


async def test_parallelism_limited_by_semaphore() -> None:
    client = FakeClient(['{"name": "a", "n": 1}'] * 10, delay=0.01)
    gateway = LlmGateway(
        client=client,
        cache=NoCache(),
        settings=make_settings(llm_concurrency=2),
        sleep=noop_sleep,
    )
    await asyncio.gather(
        *(gateway.complete_json("S01", "struct", [{"role": "user", "content": f"q{i}"}], Out) for i in range(10))
    )
    assert client.max_active <= 2
    assert client.max_active >= 1


async def test_concurrency_limit_is_shared_between_gateway_instances() -> None:
    """Несколько LlmGateway не должны в сумме превышать LLM_CONCURRENCY."""
    tracker = _ConcurrencyTracker()
    clients = [
        FakeClient(['{"name": "a", "n": 1}'] * 6, delay=0.01, tracker=tracker),
        FakeClient(['{"name": "b", "n": 2}'] * 6, delay=0.01, tracker=tracker),
    ]
    settings = make_settings(llm_concurrency=2)
    gateways = [LlmGateway(client=client, cache=NoCache(), settings=settings, sleep=noop_sleep) for client in clients]
    await asyncio.gather(
        *(
            gateway.complete_json("S01", "struct", [{"role": "user", "content": f"q{i}"}], Out)
            for i, gateway in enumerate(gateways * 6)
        )
    )
    assert tracker.max_active <= 2
    assert tracker.max_active >= 1


async def test_missing_client_raises_unavailable() -> None:
    gateway = LlmGateway(client=None, settings=make_settings(fm_api_key=""), sleep=noop_sleep)
    with pytest.raises(LlmBadOutput) as excinfo:
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert "FM_API_KEY" in str(excinfo.value)


async def test_latency_is_measured() -> None:
    client = FakeClient(['{"name": "a", "n": 1}'])
    meter = FakeMeter()
    gateway = make_gateway(client, meter)
    await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert meter.records[-1]["latency_ms"] >= 0.0
    assert time.monotonic() > 0


def test_read_error_is_transient() -> None:
    """Обрыв соединения (httpx.ReadError) должен ретраиться, а не падать сразу."""
    import httpx

    from karkas.agent.llm_gateway import _is_transient

    assert _is_transient(httpx.ReadError("connection reset"))


class BudgetMeter(FakeMeter):
    """Meter с общим счётчиком расходов за сутки (как PgMeter)."""

    def __init__(self, spent: Decimal) -> None:
        super().__init__()
        self.spent = spent

    async def spent_today_rub(self) -> Decimal:
        return self.spent


async def test_daily_budget_uses_shared_meter_counter() -> None:
    """Лимит проверяется по общему счётчику БД, а не только по памяти gateway."""
    client = FakeClient(['{"name": "a", "n": 1}'])
    meter = BudgetMeter(Decimal("101.0"))
    gateway = make_gateway(client, meter, daily_budget_rub=Decimal("100.0"))
    with pytest.raises(DailyBudgetExceededError, match="Превышен дневной бюджет"):
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert client.calls == []


async def test_daily_budget_limit_blocks_excessive_calls() -> None:
    """Превышение дневного бюджета блокирует дальнейшие вызовы."""
    client = FakeClient(['{"name": "a", "n": 1}'])
    gateway = LlmGateway(
        client=client,
        cache=NoCache(),
        settings=make_settings(daily_budget_rub=Decimal("0.0")),
        sleep=noop_sleep,
    )
    with pytest.raises(DailyBudgetExceededError, match="Превышен дневной бюджет"):
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert client.calls == []


class FailingBudgetMeter(FakeMeter):
    """Учёт в БД недоступен: запрос расхода падает."""

    async def spent_today_rub(self) -> Decimal:
        raise RuntimeError("db down")


async def test_budget_db_failure_falls_back_to_local_counter() -> None:
    """Недоступная БД не блокирует генерацию, но локальный счётчик продолжает работать."""
    client = FakeClient(['{"name": "a", "n": 1}'])
    gateway = make_gateway(client, FailingBudgetMeter(), daily_budget_rub=Decimal("100.0"))
    result = await gateway.complete_json("S01", "struct", [{"role": "user", "content": "x"}], Out)
    assert result.name == "a"
    gateway._total_spent_rub = Decimal("100.0")
    with pytest.raises(DailyBudgetExceededError, match="Превышен дневной бюджет"):
        await gateway.complete_json("S01", "struct", [{"role": "user", "content": "y"}], Out)
    assert len(client.calls) == 1


async def test_budget_takes_max_of_local_and_db_not_sum() -> None:
    """Локальный счётчик и сумма в БД — один и тот же расход, не двойной счёт."""
    gateway = make_gateway(FakeClient([]), BudgetMeter(Decimal("50.0")))
    gateway._total_spent_rub = Decimal("40.0")
    assert await gateway._spent_today_rub() == Decimal("50.0")
    gateway._total_spent_rub = Decimal("70.0")
    assert await gateway._spent_today_rub() == Decimal("70.0")


async def test_cache_hit_is_served_after_budget_exhausted() -> None:
    """Кэш не тратит токены, поэтому отдаётся даже при исчерпанном бюджете."""
    cache = InMemoryCache()
    settings = make_settings(daily_budget_rub=Decimal("100.0"))
    messages = [{"role": "user", "content": "same"}]
    first_gateway = LlmGateway(
        client=FakeClient(['{"name": "cached", "n": 1}']),
        cache=cache,
        meter=BudgetMeter(Decimal("0")),
        settings=settings,
        sleep=noop_sleep,
    )
    first = await first_gateway.complete_json("S01", "struct", messages, Out)

    second_gateway = LlmGateway(
        client=FakeClient([]),
        cache=cache,
        meter=BudgetMeter(Decimal("100.0")),
        settings=settings,
        sleep=noop_sleep,
    )
    second = await second_gateway.complete_json("S01", "struct", messages, Out)
    assert first == second
    assert second.name == "cached"


async def test_pg_meter_returns_zero_when_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from karkas.agent import pipeline

    class BrokenSession:
        async def __aenter__(self) -> None:
            raise OSError("db down")

        async def __aexit__(self, *args: object) -> None:
            return None

    def broken_factory():
        return BrokenSession()

    monkeypatch.setattr(pipeline, "get_session_factory", lambda: broken_factory)
    meter = pipeline.PgMeter(org_id="00000000-0000-0000-0000-000000000001")
    assert await meter.spent_today_rub() == Decimal("0")


async def test_org_spent_today_counts_only_today_and_org(monkeypatch: pytest.MonkeyPatch) -> None:
    """SQL lite-режима: сутки по МСК и только своя организация."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from karkas.infra.repos import usage as usage_repo

    monkeypatch.setattr(usage_repo, "uses_sqlite", lambda: True)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE llm_call (created_at TEXT NOT NULL, org_id TEXT NOT NULL, cost_rub REAL NOT NULL)")
        )
        await conn.execute(
            text(
                "INSERT INTO llm_call (created_at, org_id, cost_rub) VALUES "
                "(datetime('now'), 'org-1', 1.0), (datetime('now'), 'org-1', 0.25), "
                "(datetime('now', '-1 day'), 'org-1', 5.0), (datetime('now'), 'org-2', 10.0)"
            )
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        spent = await usage_repo.org_spent_today(session, "org-1")
    await engine.dispose()
    assert spent == Decimal("1.25")
