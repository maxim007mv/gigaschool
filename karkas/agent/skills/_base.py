"""karkas.agent.skills._base — контракты слоя навыков агента (Д4 §4).

Здесь живёт всё, что общее для 23 навыков S01–S23:

- ``SkillSpec`` — паспорт навыка (код, каталог, класс модели, зависимости);
- ``SkillContext`` — окружение шага (LLM-шлюз, настройки, чекпоинты, extra);
- протоколы ``CacheProtocol`` / ``MeterProtocol`` / ``CheckpointStore``;
- реализации по умолчанию: ``InMemoryCache``, ``NullMeter``,
  ``InMemoryCheckpointStore``;
- ``render_prompt()`` — рендер ``prompt.jinja`` из каталога навыка.

Каталог навыков (``karkas/agent/skills/__init__.py``) собирает ``SKILLS`` из
``METADATA`` всех ``run.py``, а ``karkas.agent.skill_runner.SkillRunner``
исполняет их по графу ``depends_on``.
"""

from __future__ import annotations

import copy
import inspect
import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from karkas.domain.hours import Constraints, ModuleIn, Plan, TopicIn
from karkas.domain.kit import KitV1
from karkas.domain.validators import (
    LaborFunction,
    NormativeAct,
    ProfStandard,
    RegistryBundle,
    ServiceRecord,
)
from karkas.settings import Settings, get_settings

#: Класс задачи навыка: структурная модель, массовая генерация или чистый код.
SkillModelClass = Literal["struct", "bulk", "none"]

#: Каталог со всеми навыками: karkas/agent/skills/.
SKILLS_DIR: Path = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class SkillSpec:
    """Паспорт навыка (метаданные ``METADATA`` в run.py).

    ``dir`` — имя каталога внутри ``karkas/agent/skills`` (например,
    ``S06_competency_map``); из него и импортируется ``run``.
    """

    code: str
    name: str
    dir: str
    model_class: SkillModelClass = "none"
    depends_on: tuple[str, ...] = ()
    timeout_s: float | None = None

    @property
    def is_llm(self) -> bool:
        """Использует ли навык LLM-шлюз."""
        return self.model_class in ("struct", "bulk")


# ---------------------------------------------------------------------------
# Протоколы (их реализуют инфраструктурные адаптеры: БД, метрики, очередь)
# ---------------------------------------------------------------------------


@dataclass
class SkillContext:
    """Окружение шага: шлюз, настройки, чекпоинты и произвольный контекст.

    ``extra`` несёт доменные данные, которые не являются входом-схемой:
    ``kit``, ``registries``, ``program_id``, ``checkpoint_prefix`` и т. п.
    """

    gateway: Any | None = None
    settings: Settings = field(default_factory=get_settings)
    checkpoint: CheckpointStore = field(default_factory=lambda: InMemoryCheckpointStore())
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LlmGatewayProtocol(Protocol):
    """Минимальный контракт LLM-шлюза, достаточный навыкам (см. llm_gateway.py)."""

    async def complete_json(
        self,
        skill: str,
        model_class: Literal["struct", "bulk"],
        messages: list[dict[str, Any]],
        schema: type[BaseModel],
        temperature: float | None = None,
    ) -> BaseModel: ...


@runtime_checkable
class CacheProtocol(Protocol):
    """Кэш ответов модели и промежуточных результатов."""

    async def get(self, key: str) -> dict[str, Any] | None: ...

    async def put(self, key: str, value: dict[str, Any], ttl_s: float | None = None) -> None: ...


@runtime_checkable
class MeterProtocol(Protocol):
    """Учёт вызовов модели (пишется в llm_call, Д1 §7)."""

    async def record(
        self,
        skill: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        ok: bool,
        cache_hit: bool,
    ) -> None: ...


@runtime_checkable
class CheckpointStore(Protocol):
    """Чекпоинты шагов: перезапуск продолжается с последнего успешного шага."""

    async def save(self, key: str, output: dict[str, Any]) -> None: ...

    async def load(self, key: str) -> dict[str, Any] | None: ...


# ---------------------------------------------------------------------------
# Реализации по умолчанию
# ---------------------------------------------------------------------------


class InMemoryCache:
    """TTL-кэш в памяти процесса (тесты, локальный запуск, кэш промптов).

    Значения отдаются копией: вызывающий код не может случайно изменить
    закэшированный ответ модели.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= self._clock():
            self._items.pop(key, None)
            return None
        return copy.deepcopy(value)

    async def put(self, key: str, value: dict[str, Any], ttl_s: float | None = None) -> None:
        if ttl_s is None:
            self._items[key] = (float("inf"), copy.deepcopy(value))
            return
        self._items[key] = (self._clock() + float(ttl_s), copy.deepcopy(value))

    def __len__(self) -> int:
        return len(self._items)


class NullMeter:
    """Заглушка учёта токенов (ничего не пишет)."""

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
        return None


class InMemoryCheckpointStore:
    """Чекпоинты шагов в памяти (по умолчанию для SkillContext)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def save(self, key: str, output: dict[str, Any]) -> None:
        self._data[key] = copy.deepcopy(output)

    async def load(self, key: str) -> dict[str, Any] | None:
        item = self._data.get(key)
        return copy.deepcopy(item) if item is not None else None

    def keys(self) -> tuple[str, ...]:
        """Сохранённые ключи (диагностика и тесты)."""
        return tuple(self._data)


# ---------------------------------------------------------------------------
# Вспомогательные функции для навыков
# ---------------------------------------------------------------------------

_JINJA_ENV: Environment | None = None


def _jinja_env() -> Environment:
    global _JINJA_ENV
    if _JINJA_ENV is None:
        _JINJA_ENV = Environment(
            loader=FileSystemLoader(str(SKILLS_DIR)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
    return _JINJA_ENV


@lru_cache(maxsize=256)
def _render_prompt_cached(skill_dir: str, variables_json: str) -> str:
    variables = json.loads(variables_json)
    return _jinja_env().get_template(f"{skill_dir}/prompt.jinja").render(**variables)


def render_prompt(skill_dir: str, **variables: Any) -> str:
    """Отрендерить ``<skill_dir>/prompt.jinja`` с переменными навыка (кэш по содержимому)."""
    variables_json = json.dumps(variables, ensure_ascii=False, sort_keys=True, default=str)
    return _render_prompt_cached(skill_dir, variables_json)


def make_messages(user: str, system: str | None = None) -> list[dict[str, Any]]:
    """Собрать messages для HTTP-вызова к шлюзу Cloud.ru FM."""
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return messages


def to_json(value: Any, *, indent: int | None = None) -> str:
    """JSON для вставки в промпт (компактный по умолчанию — экономия токенов)."""
    if indent is None:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return json.dumps(value, ensure_ascii=False, indent=indent, default=str)


def clamp(value: float, low: float, high: float) -> float:
    """Ограничить число диапазоном [low, high]."""
    return max(low, min(high, value))


def require_gateway(ctx: SkillContext, skill: str) -> LlmGatewayProtocol:
    """Вернуть LLM-шлюз или объяснить, почему шаг невозможен."""
    if ctx.gateway is None:
        raise RuntimeError(f"{skill}: LLM-шлюз не передан в SkillContext")
    return ctx.gateway


async def maybe_await(value: Any) -> Any:
    """Дождаться «может-быть-awaitable» (терпимость к sync-адаптерам кэша/метра)."""
    if inspect.isawaitable(value):
        return await value
    return value


async def complete_structured(
    ctx: SkillContext,
    spec: SkillSpec,
    schema: type[BaseModel],
    **variables: Any,
) -> BaseModel:
    """Отрендерить prompt.jinja навыка, вызвать LLM и вернуть ответ по схеме.

    Единая точка входа для LLM-навыков: промпт берётся из каталога навыка,
    вызов идёт через шлюз (allowlist, кэш, ретраи, ремонт JSON).
    """
    if spec.model_class not in ("struct", "bulk"):
        raise ValueError(f"{spec.code}: навык {spec.model_class!r} не является LLM-шагом")
    gateway = require_gateway(ctx, spec.code)
    prompt = render_prompt(spec.dir, **variables)
    return await gateway.complete_json(spec.code, spec.model_class, make_messages(prompt), schema)


# ---------------------------------------------------------------------------
# Доменные адаптеры: JSON из шагов конвейера → замороженные типы domain
# ---------------------------------------------------------------------------


def as_date(value: Any) -> Any:
    """ISO-строку → date; остальное (date/None) — как есть."""
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def registry_bundle(raw: Any) -> RegistryBundle | None:
    """Привести вход реестров (dict из JSON или RegistryBundle) к RegistryBundle."""
    if raw is None:
        return None
    if isinstance(raw, RegistryBundle):
        return raw
    if not isinstance(raw, Mapping):
        raise TypeError("registries: ожидался dict или RegistryBundle")

    def _items(cls: type, key: str) -> list[Any]:
        result = []
        for item in raw.get(key) or []:
            if not isinstance(item, Mapping):
                continue
            fields = {k: v for k, v in item.items() if k in cls.__dataclass_fields__}
            if cls is NormativeAct:
                for name in ("signed_on", "valid_from", "valid_to"):
                    fields[name] = as_date(fields.get(name))
            result.append(cls(**fields))  # type: ignore[arg-type]
        return result

    return RegistryBundle(
        normative_acts=_items(NormativeAct, "normative_acts"),
        prof_standards=_items(ProfStandard, "prof_standards"),
        labor_functions=_items(LaborFunction, "labor_functions"),
        services=_items(ServiceRecord, "services"),
    )


def hours_share(raw: Mapping[str, Any], name: str) -> float:
    """Доля из входа: поддерживаются ``name`` (0…1) и ``name_pct`` (0…100)."""
    if f"{name}_pct" in raw:
        return float(raw[f"{name}_pct"]) / 100.0
    return float(raw.get(name, 0.0) or 0.0)


def hours_constraints(raw: Mapping[str, Any]) -> Constraints:
    """Ограничения солвера из JSON-входа (total/total_hours и т. п.)."""
    total = raw.get("total", raw.get("total_hours"))
    if total is None:
        raise ValueError("constraints: не задан объём часов (total)")
    total_int = int(total)
    if total_int <= 0:
        raise ValueError(f"constraints: объём часов должен быть положительным, получено {total_int}")
    return Constraints(
        total=total_int,
        final_att=max(0, int(raw.get("final_att", raw.get("final_attestation_hours", 2)) or 2)),
        unit=max(1, int(raw.get("unit", raw.get("unit_hours", 1)) or 1)),
        self_study_only=bool(raw.get("self_study_only", False)),
        min_practice_share=hours_share(raw, "min_practice_share"),
        self_study_share=hours_share(raw, "self_study_share"),
        distance_share=hours_share(raw, "distance_share"),
    )


def hours_modules(raw_modules: Any) -> list[ModuleIn]:
    """Модули солвера из JSON-входа (S07): веса, практичность, признак лабораторной."""
    modules: list[ModuleIn] = []
    for module in raw_modules or []:
        topics = [
            TopicIn(
                ref=str(topic["ref"]),
                weight=max(0.1, float(topic.get("weight", 1.0) or 1.0)),
                practicality=min(1.0, max(0.0, float(topic.get("practicality", 0.5) or 0.0))),
                has_lab=bool(topic.get("has_lab", False)),
            )
            for topic in module.get("topics") or []
        ]
        modules.append(
            ModuleIn(
                ref=str(module["ref"]),
                weight=max(0.1, float(module.get("weight", 1.0) or 1.0)),
                topics=topics,
            )
        )
    if not modules:
        raise ValueError("modules: пустой список модулей")
    return modules


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    """Plan (dataclass) → JSON-совместимый словарь: rows/distance/module_of/proof."""
    return {
        "rows": {ref: dict(row) for ref, row in plan.rows.items()},
        "distance": dict(plan.distance),
        "module_of": dict(plan.module_of),
        "proof": [{"rule": rule, "ok": bool(ok), "message": message} for rule, ok, message in plan.proof],
    }


def kit_from_inputs(inputs: Mapping[str, Any], ctx: SkillContext, skill: str) -> KitV1:
    """Каркас/комплект из входа шага или из extra контекста (KitV1 либо JSON)."""
    raw = inputs.get("kit") or ctx.extra.get("kit")
    if raw is None:
        raise ValueError(f"{skill}: не передан комплект KitV1")
    if isinstance(raw, KitV1):
        return raw
    if isinstance(raw, Mapping):
        return KitV1.model_validate(dict(raw))
    raise TypeError(f"{skill}: kit должен быть KitV1 или объектом JSON")


def today_from_inputs(inputs: Mapping[str, Any]) -> date:
    """Дата проверки: ISO-строка из входа или текущая дата."""
    parsed = as_date(inputs.get("today"))
    return parsed if isinstance(parsed, date) else date.today()
