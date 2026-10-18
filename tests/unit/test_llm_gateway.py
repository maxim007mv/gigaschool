"""Тесты LLM-шлюза (Д1 §7): allowlist, кэш, ремонт JSON, ретраи, предохранитель, параллелизм."""

from __future__ import annotations

import asyncio
import time

import pytest
from pydantic import BaseModel

from karkas.agent.llm_gateway import (
    CircuitOpenError,
    LlmBadOutput,
    LlmGateway,
    LlmRequestError,
    ModelNotAllowedError,
    TransientError,
)
from karkas.settings import Settings


class Out(BaseModel):
    """Тестовая схема ответа навыка."""

    name: str
    n: int


class ApiError(Exception):
    """Ошибка провайдера с HTTP-статусом (эмулирует openai.APIStatusError)."""

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
    def __init__(self, client: "FakeClient") -> None:
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
    def __init__(self, client: "FakeClient") -> None:
        self.completions = _FakeCompletions(client)


class FakeClient:
    """AsyncOpenAI-совместимый клиент, отвечающий по сценарию.

    Элемент сценария: строка (content), (content, finish_reason),
    Exception (будет брошено) или async-функция (model, messages, temperature).
    """

    def __init__(self, script: list | None = None, *, delay: float = 0.0) -> None:
        self.script = list(script or [])
        self.calls: list[dict] = []
        self.active = 0
        self.max_active = 0
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
        self.max_active = max(self.max_active, self.active)
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
        llm_concurrency=4,
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
    await gateway.complete_json(
        "S11", "bulk", [{"role": "user", "content": "3"}], Out, temperature=0.9
    )
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


async def test_parallelism_limited_by_semaphore() -> None:
    client = FakeClient(['{"name": "a", "n": 1}'] * 10, delay=0.01)
    gateway = LlmGateway(
        client=client,
        cache=NoCache(),
        settings=make_settings(llm_concurrency=3),
        sleep=noop_sleep,
    )
    await asyncio.gather(
        *(
            gateway.complete_json("S01", "struct", [{"role": "user", "content": f"q{i}"}], Out)
            for i in range(10)
        )
    )
    assert client.max_active <= 3
    assert client.max_active >= 2


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
