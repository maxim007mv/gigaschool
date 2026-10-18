"""karkas.agent.llm_gateway — единственный выход к Cloud.ru Foundation Models (Д1 §7).

Возможности шлюза:

- allowlist моделей (ЗАД-13): вызов модели вне ``MODEL_ALLOWLIST`` запрещён;
- structured output: ``response_format=json_object`` + Pydantic-валидация с
  «ремонтом» невалидного/обрезанного JSON (до ``LLM_MAX_REPAIRS`` раз);
- кэш ответов: ключ ``sha256(model | schema | messages | params)``, TTL
  ``LLM_CACHE_TTL_H``; попадание не тратит токены;
- ретраи временных ошибок 429/5xx/timeout с экспоненциальным backoff и джиттером;
- circuit breaker на модель: ``LLM_CIRCUIT_FAILURES`` ошибок за окно
  ``LLM_CIRCUIT_WINDOW_S`` → пауза ``LLM_CIRCUIT_COOLDOWN_S`` с переключением
  на резервную модель того же класса (если задана ``backup_models``);
- учёт каждого вызова через ``meter`` (таблица llm_call) и семафор параллелизма
  ``LLM_CONCURRENCY``.

Запросы идут ТОЛЬКО на ``FM_BASE_URL`` (Cloud.ru). Модели OpenAI/Anthropic/Google
не допускаются даже при доступности в каталоге провайдера.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from karkas.agent.skills._base import (
    CacheProtocol,
    InMemoryCache,
    MeterProtocol,
    NullMeter,
    maybe_await,
)
from karkas.logging_setup import get_logger
from karkas.settings import Settings, get_settings

logger = get_logger("karkas.llm")

#: Классы задач, которые маршрутизируются на LLM (Д1 §7).
ModelClass = Literal["struct", "bulk"]

#: Температура по классу задачи: структура — 0,15; содержание — 0,5.
TEMPERATURE: dict[str, float] = {"struct": 0.15, "bulk": 0.5}

#: Число попыток одного вызова модели при временных ошибках (Д1 §7).
RETRY_ATTEMPTS: int = 3

#: Разброс джиттера backoff относительно базовой задержки.
JITTER_RANGE: tuple[float, float] = (0.5, 1.5)

#: Имена исключений клиента, которые считаются временными (429/сеть/timeout).
_TRANSIENT_NAMES: frozenset[str] = frozenset(
    {
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
        "RemoteProtocolError",
    }
)


class LlmError(Exception):
    """Базовая ошибка LLM-шлюза."""


class LlmBadOutput(LlmError):
    """Модель не вернула валидный ответ по схеме даже после «ремонта»."""


class TransientError(LlmError):
    """Временный сбой провайдера (429/5xx/timeout) — вызов имеет смысл повторить."""


class ModelNotAllowedError(LlmBadOutput, ValueError):
    """Модель отсутствует в allowlist (ЗАД-13). Является и LlmBadOutput, и ValueError."""


class LlmUnavailableError(LlmBadOutput):
    """Клиент к Cloud.ru FM не сконфигурирован (нет ключа/фабрики клиентов)."""


class LlmRequestError(LlmBadOutput):
    """Невосстановимая ошибка провайдера (например, 400 на конкретном запросе)."""


class CircuitOpenError(TransientError):
    """Предохранитель модели разомкнут: вызов не делается до конца cooldown."""


@dataclass
class _ModelCircuit:
    """Состояние предохранителя одной модели."""

    failures: list[float] = field(default_factory=list)
    opened_at: float | None = None


# ---------------------------------------------------------------------------
# Помощники разбора ответа (совместимы с объектами openai и с моками-словарями)
# ---------------------------------------------------------------------------


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _lenient_coerce(data: Any, schema: Any) -> Any:
    """Мягкое приведение JSON от GigaChat к Pydantic-схеме до валидации."""
    import types
    import typing

    from pydantic import BaseModel as _BM

    def _unwrap(ann: Any) -> Any:
        origin = typing.get_origin(ann)
        if origin in (typing.Union, types.UnionType):
            args = [a for a in typing.get_args(ann) if a is not type(None)]
            return args[0] if len(args) == 1 else ann
        return ann

    def _as_text(v: Any) -> str:
        if isinstance(v, dict):
            for key in ("text", "value", "description", "name", "title"):
                if isinstance(v.get(key), str) and v[key].strip():
                    return v[key]
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, list):
            return "; ".join(_as_text(x) for x in v)
        return str(v)

    def _coerce(value: Any, ann: Any) -> Any:
        ann = _unwrap(ann)
        origin = typing.get_origin(ann)
        if isinstance(ann, type) and issubclass(ann, _BM) and isinstance(value, dict):
            return _model(value, ann)
        if origin is list:
            args = typing.get_args(ann)
            inner = args[0] if args else Any
            if isinstance(value, str):
                value = [value] if value.strip() else []
            if isinstance(value, list):
                return [_coerce(v, inner) for v in value if v is not None]
            return value
        if ann is str and isinstance(value, (dict, list)):
            return _as_text(value)
        if ann is str and isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return value

    def _model(obj: dict, model: Any) -> dict:
        out = dict(obj)
        for name, model_field in model.model_fields.items():
            key = model_field.alias or name
            if key not in out:
                continue
            if out[key] is None and not model_field.is_required():
                if _unwrap(model_field.annotation) is not model_field.annotation:
                    continue
                del out[key]
                continue
            out[key] = _coerce(out[key], model_field.annotation)
        return out

    try:
        if isinstance(data, dict) and isinstance(schema, type) and issubclass(schema, _BM):
            return _model(data, schema)
    except Exception:  # noqa: BLE001
        return data
    return data


def _extract_content(response: Any) -> str:
    """Текст ответа модели; пустая строка, если сообщение пустое."""
    choices = _attr(response, "choices") or []
    if not choices:
        return ""
    content = _attr(_attr(choices[0], "message"), "content")
    return content if isinstance(content, str) else ""


def _finish_reason(response: Any) -> str | None:
    choices = _attr(response, "choices") or []
    if not choices:
        return None
    reason = _attr(choices[0], "finish_reason")
    return reason if isinstance(reason, str) else None


def _extract_usage(response: Any) -> tuple[int, int]:
    usage = _attr(response, "usage")
    prompt = int(_attr(usage, "prompt_tokens", 0) or 0)
    completion = int(_attr(usage, "completion_tokens", 0) or 0)
    return prompt, completion


def _is_transient(exc: BaseException) -> bool:
    """Классификация ошибки: повторяемая (429/5xx/timeout) или нет."""
    if isinstance(exc, (TransientError, TimeoutError)):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    return type(exc).__name__ in _TRANSIENT_NAMES


def _is_json_mode_rejection(exc: BaseException) -> bool:
    """Похоже ли, что модель отвергла именно параметр response_format.

    Только такие ошибки — повод отключить JSON-режим; 400 «context length»,
    401/403/404 и прочие не должны маскироваться под «модель без JSON».
    """
    status = getattr(exc, "status_code", None)
    if status not in (400, 404, 422):
        return False
    message = str(exc).lower()
    markers = (
        "response_format",
        "json_object",
        "unknown parameter",
        "unsupported parameter",
        "invalid parameter",
    )
    return any(marker in message for marker in markers)


def _repair_message(exc: BaseException) -> str:
    """Сообщение «ремонта»: что именно не прошло валидацию."""
    if isinstance(exc, ValidationError):
        detail = json.dumps(exc.errors()[:5], ensure_ascii=False, default=str)
    else:
        detail = str(exc)
    return f"Исправь JSON по схеме. Ошибки: {detail}"[:2000]


def _build_default_client(settings: Settings) -> Any | None:
    """Клиент Cloud.ru FM по умолчанию; без ключа — None (ошибка на вызове)."""
    if not settings.fm_api_key:
        return None
    return AsyncOpenAI(
        base_url=settings.fm_base_url,
        api_key=settings.fm_api_key,
        timeout=settings.llm_timeout_s,
        max_retries=0,
    )


class LlmGateway:
    """Шлюз structured output: маршрутизация, кэш, ретраи, предохранитель, учёт."""

    def __init__(
        self,
        client: Any | None = None,
        cache: CacheProtocol | None = None,
        meter: MeterProtocol | None = None,
        *,
        client_factory: Callable[[str], Any] | None = None,
        backup_models: Mapping[str, str] | None = None,
        settings: Settings | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] | None = None,
        semaphore: asyncio.Semaphore | None = None,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._extra_body: dict[str, Any] = json.loads(self._settings.llm_extra_body_json or "{}")
        self._client = client if client is not None else _build_default_client(self._settings)
        self._cache: CacheProtocol = cache if cache is not None else InMemoryCache()
        self._meter: MeterProtocol = meter if meter is not None else NullMeter()
        self._client_factory = client_factory
        self._backup_models: dict[str, str] = dict(backup_models or {})
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._clock = clock if clock is not None else time.monotonic
        self._semaphore = semaphore
        self._circuits: dict[str, _ModelCircuit] = {}
        self._clients: dict[str, Any] = {}
        #: Модели, у которых выяснилось, что response_format не поддерживается (JSON в промпте).
        self._json_mode: dict[str, bool] = {}
        if self._client is not None:
            for model_class in ("struct", "bulk"):
                model_id = self._settings.model_for(model_class)
                if model_id:
                    self._clients.setdefault(model_id, self._client)

    # --- Публичный API -----------------------------------------------------

    async def complete_json(
        self,
        skill: str,
        model_class: ModelClass,
        messages: list[dict[str, Any]],
        schema: type[BaseModel],
        temperature: float | None = None,
    ) -> BaseModel:
        """Получить ответ модели, валидированный Pydantic-схемой ``schema``.

        Порядок: allowlist → кэш → вызов под семафором (с ретраями) →
        валидация с «ремонтом» → кэш и учёт. Все ошибки типизированы:
        ``TransientError`` — можно повторить выше, ``LlmBadOutput`` — нельзя.
        """
        if model_class not in TEMPERATURE:
            raise ValueError(f"{skill}: неизвестный класс задачи {model_class!r}")
        temp = self._temperature(model_class, temperature)
        model = self._route(model_class)
        key = self._cache_key(model, schema, messages, temp, model_class)

        cached = await maybe_await(self._cache.get(key))
        if cached is not None:
            try:
                obj = schema.model_validate(cached)
            except ValidationError:
                obj = None  # схема изменилась — считаем промахом
            if obj is not None:
                await self._record(skill, model, 0, 0, 0.0, ok=True, cache_hit=True)
                return obj

        attempt_messages = list(messages)
        repairs_done = 0
        while True:
            response = await self._call_with_retries(model, attempt_messages, temp, skill)
            raw_content = ""
            try:
                raw_content = _extract_content(response) or ""
            except Exception:  # noqa: BLE001
                raw_content = ""
            try:
                if _finish_reason(response) == "length":
                    raise ValueError("ответ обрезан по лимиту токенов (finish_reason=length)")
                try:
                    parsed = json.loads(raw_content)
                    obj = schema.model_validate(_lenient_coerce(parsed, schema))
                except ValueError:
                    obj = schema.model_validate_json(raw_content)
            except ValueError as exc:  # ValidationError и json.JSONDecodeError — тоже ValueError
                if repairs_done >= self._settings.llm_max_repairs:
                    raise LlmBadOutput(
                        f"{skill}: ответ модели {model} не соответствует схеме "
                        f"{schema.__name__} после {repairs_done} ремонтов: {exc}"
                    ) from exc
                repairs_done += 1
                logger.warning(
                    "llm.repair",
                    skill=skill,
                    model=model,
                    attempt=repairs_done,
                    error=str(exc)[:600],
                    raw_head=raw_content[:300],
                )
                attempt_messages = attempt_messages + [
                    {"role": "assistant", "content": raw_content or "{}"},
                    {"role": "user", "content": _repair_message(exc)},
                ]
                continue
            await maybe_await(self._cache.put(key, obj.model_dump(mode="json"), self._cache_ttl_s()))
            return obj

    # --- Внутренняя механика ----------------------------------------------

    def _temperature(self, model_class: str, temperature: float | None) -> float:
        if temperature is not None:
            return float(temperature)
        return TEMPERATURE[model_class]

    def _cache_ttl_s(self) -> float:
        return float(self._settings.llm_cache_ttl_h) * 3600.0

    def _cache_key(
        self,
        model: str,
        schema: type[BaseModel],
        messages: list[dict[str, Any]],
        temperature: float,
        model_class: str,
    ) -> str:
        key_parts: dict[str, Any] = {
            "model": model,
            "schema": schema.__name__,
            "messages": messages,
            "temperature": temperature,
            "model_class": model_class,
            "response_format": {"type": "json_object"},
        }
        # Опции режима влияют на ответ: без них кэш отдал бы ответ прежнего режима.
        # Ключ меняется только когда опции заданы, чтобы не инвалидировать прежний кэш.
        if self._extra_body:
            key_parts["extra_body"] = self._extra_body
        if self._settings.llm_max_output_tokens:
            key_parts["max_tokens"] = self._settings.llm_max_output_tokens
        payload = json.dumps(key_parts, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _assert_allowed(self, model: str) -> None:
        if model and model in self._settings.allowed_models:
            return
        allowed = ", ".join(self._settings.allowed_models) or "<пусто>"
        raise ModelNotAllowedError(
            f"модель {model!r} не входит в MODEL_ALLOWLIST ({allowed}) — вызов запрещён (ЗАД-13)"
        )

    def _circuit(self, model: str) -> _ModelCircuit:
        return self._circuits.setdefault(model, _ModelCircuit())

    def _route(self, model_class: ModelClass) -> str:
        """Выбор модели: основная, резервная (при разомкнутом предохранителе) или ошибка."""
        primary = self._settings.model_for(model_class)
        self._assert_allowed(primary)
        now = self._clock()
        state = self._circuit(primary)
        if state.opened_at is None:
            return primary
        cooldown = float(self._settings.llm_circuit_cooldown_s)
        if now - state.opened_at >= cooldown:
            # cooldown истёк — пробная попытка на основной модели (half-open).
            state.opened_at = None
            state.failures.clear()
            return primary
        backup = self._backup_for(model_class)
        if backup:
            self._assert_allowed(backup)
            backup_state = self._circuit(backup)
            if backup_state.opened_at is None or now - backup_state.opened_at >= cooldown:
                return backup
        left = max(0.0, cooldown - (now - state.opened_at))
        raise CircuitOpenError(
            f"модель {primary}: предохранитель разомкнут ({len(state.failures)} ошибок), "
            f"резервная модель недоступна — повтор через {left:.0f} с"
        )

    def _backup_for(self, model_class: ModelClass) -> str | None:
        backup = self._backup_models.get(model_class)
        primary = self._settings.model_for(model_class)
        if not backup or backup == primary:
            return None
        if self._client_factory is None and self._clients.get(backup) is None:
            return None  # нечем вызвать резервную модель
        return backup

    def _client_for(self, model: str) -> Any:
        client = self._clients.get(model)
        if client is None and self._client_factory is not None:
            client = self._client_factory(model)
            if client is not None:
                self._clients[model] = client
        if client is None:
            raise LlmUnavailableError(
                "LLM-клиент не сконфигурирован: задайте FM_API_KEY или передайте client/client_factory"
            )
        return client

    def _limiter(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._settings.llm_concurrency)
        return self._semaphore

    def _register_failure(self, model: str) -> None:
        """Зафиксировать ошибку модели; при переполнении окна — разомкнуть предохранитель."""
        now = self._clock()
        window = float(self._settings.llm_circuit_window_s)
        state = self._circuit(model)
        state.failures = [t for t in state.failures if now - t <= window]
        state.failures.append(now)
        if len(state.failures) >= self._settings.llm_circuit_failures and state.opened_at is None:
            state.opened_at = now

    def _backoff_delay(self, attempt: int) -> float:
        base = float(self._settings.llm_backoff_base_s) * (2**attempt)
        return base * random.uniform(*JITTER_RANGE)

    async def _record(
        self,
        skill: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        *,
        ok: bool,
        cache_hit: bool,
    ) -> None:
        await maybe_await(
            self._meter.record(skill, model, prompt_tokens, completion_tokens, float(latency_ms), ok, cache_hit)
        )
        if ok and not cache_hit and (prompt_tokens or completion_tokens):
            logger.info(
                "llm.usage",
                skill=skill,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=round(float(latency_ms), 1),
            )

    async def _call_with_retries(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        skill: str,
    ) -> Any:
        """Один вызов модели с ретраями временных ошибок и учётом каждого обращения.

        Если провайдер отвечает на ``response_format`` ошибкой 4xx (модель без
        JSON-режима), флаг снимается для этой модели и вызов повторяется без
        ``response_format`` — JSON остаётся обязательным по промпту и валидации.
        """
        client = self._client_for(model)  # конфигурационная ошибка не маскируется ретраями
        last_error: BaseException | None = None
        attempt = 0
        while attempt < RETRY_ATTEMPTS:
            use_json_mode = self._json_mode.get(model, True)
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if self._settings.llm_max_output_tokens:
                kwargs["max_tokens"] = self._settings.llm_max_output_tokens
            if self._extra_body:
                kwargs["extra_body"] = self._extra_body
            started = self._clock()
            try:
                async with self._limiter():
                    response = await client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 — классифицируется ниже
                latency_ms = (self._clock() - started) * 1000.0
                await self._record(skill, model, 0, 0, latency_ms, ok=False, cache_hit=False)
                if not _is_transient(exc):
                    if use_json_mode and _is_json_mode_rejection(exc):
                        # Проба: модель не поддерживает response_format (Д1 §7).
                        # Отключаем JSON-режим ТОЛЬКО при ошибке про сам параметр:
                        # 400 «context length exceeded»/401/404 не должны навсегда
                        # переводить модель в режим «JSON только промптом».
                        self._json_mode[model] = False
                        continue
                    raise LlmRequestError(f"{skill}: ошибка модели {model}: {exc}") from exc
                self._register_failure(model)
                last_error = exc
                attempt += 1
                if attempt >= RETRY_ATTEMPTS:
                    break
                await self._sleep(self._backoff_delay(attempt - 1))
                continue
            prompt_tokens, completion_tokens = _extract_usage(response)
            latency_ms = (self._clock() - started) * 1000.0
            await self._record(skill, model, prompt_tokens, completion_tokens, latency_ms, ok=True, cache_hit=False)
            return response
        raise TransientError(
            f"{skill}: модель {model} недоступна после {RETRY_ATTEMPTS} попыток: {last_error}"
        ) from last_error


__all__ = [
    "CircuitOpenError",
    "LlmBadOutput",
    "LlmError",
    "LlmGateway",
    "LlmRequestError",
    "LlmUnavailableError",
    "ModelNotAllowedError",
    "ModelClass",
    "RETRY_ATTEMPTS",
    "TEMPERATURE",
    "TransientError",
]
