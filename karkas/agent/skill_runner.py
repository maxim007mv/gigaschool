"""karkas.agent.skill_runner — исполнение навыков S01–S23 по графу зависимостей.

Раннер — «DAG навыков» из Д1 §6: он не знает содержания шагов, но отвечает за
порядок и надёжность:

- зависимости навыка (``depends_on``) выполняются до него; независимые ветви —
  параллельно (``asyncio.gather``) под общим семафором;
- результат каждого шага сохраняется в чекпоинт (``CheckpointStore``), при
  повторном запуске с тем же префиксом шаг не перевыполняется;
- временные ошибки (``TransientError``) повторяются до 3 раз с backoff;
- на каждый шаг действует таймаут (аргумент ``timeout_s`` или ``SkillSpec.timeout_s``);
- прогресс отдаётся колбэком ``on_progress(code, done, total, label)``.

Выход зависимости доступен зависимым навыкам под ключом её кода:
``inputs["S07"] → output навыка S07``.
"""

from __future__ import annotations

import asyncio
import importlib
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from karkas.agent.llm_gateway import TransientError
from karkas.agent.skills._base import SkillContext, SkillSpec, maybe_await
from karkas.settings import Settings, get_settings

#: Колбэк прогресса: код шага, готовых шагов, всего шагов, человекочитаемая метка.
ProgressCallback = Callable[[str, int, int, str], Any]

#: Функция навыка: (inputs, ctx) → JSON-совместимый словарь.
SkillFunc = Callable[[dict[str, Any], SkillContext], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class SkillResult:
    """Результат выполнения навыка (корня запроса)."""

    code: str
    output: dict[str, Any]
    duration_ms: int
    attempts: int


class SkillFailed(Exception):
    """Навык не выполнен; ``code`` — код шага, ``cause`` — исходная ошибка."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class _RunState:
    """Состояние одного запуска раннера (общее для всех параллельных ветвей)."""

    total: int
    prefix: str
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    tasks: dict[str, asyncio.Task[dict[str, Any]]] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    done: int = 0


class SkillRunner:
    """Реестр навыков и их исполнение по зависимостям."""

    def __init__(
        self,
        skills: Iterable[SkillSpec] | None = None,
        *,
        settings: Settings | None = None,
        concurrency: int | None = None,
        retries: int = 3,
        backoff_base_s: float | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings if settings is not None else get_settings()
        self._concurrency = int(concurrency or self._settings.llm_concurrency)
        self._retries = max(1, int(retries))
        self._backoff_base_s = (
            float(self._settings.llm_backoff_base_s) if backoff_base_s is None else float(backoff_base_s)
        )
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._clock = clock if clock is not None else time.monotonic
        self._registry: dict[str, SkillSpec] = {}
        self._funcs: dict[str, SkillFunc] = {}
        self._semaphore: asyncio.Semaphore | None = None
        for spec in skills or ():
            self.register(spec)

    # --- Реестр ------------------------------------------------------------

    def register(self, skill: SkillSpec, func: SkillFunc | None = None) -> None:
        """Зарегистрировать навык; ``func`` — тестовый/альтернативный обработчик."""
        if not skill.code:
            raise ValueError("SkillSpec.code не может быть пустым")
        if skill.code in self._registry:
            raise ValueError(f"навык {skill.code} уже зарегистрирован")
        self._registry[skill.code] = skill
        if func is not None:
            self._funcs[skill.code] = func

    @property
    def skills(self) -> dict[str, SkillSpec]:
        """Зарегистрированные навыки (код → паспорт)."""
        return dict(self._registry)

    def _spec(self, code: str) -> SkillSpec:
        spec = self._registry.get(code)
        if spec is None:
            raise SkillFailed(code, "навык не зарегистрирован в раннере")
        return spec

    def _func_for(self, spec: SkillSpec) -> SkillFunc:
        func = self._funcs.get(spec.code)
        if func is not None:
            return func
        module = importlib.import_module(f"karkas.agent.skills.{spec.dir}.run")
        func = getattr(module, "run", None)
        if func is None or not callable(func):
            raise SkillFailed(spec.code, f"в {spec.dir}/run.py нет callable run()")
        self._funcs[spec.code] = func
        return func

    # --- Исполнение ---------------------------------------------------------

    async def run(
        self,
        code: str,
        inputs: dict[str, Any],
        ctx: SkillContext,
        on_progress: ProgressCallback | None = None,
        timeout_s: float | None = None,
    ) -> SkillResult:
        """Выполнить навык ``code`` со всеми зависимостями и вернуть результат.

        Префикс чекпоинтов берётся из ``ctx.extra["checkpoint_prefix"]`` (или
        ``program_id``): в него обязан входить идентификатор программы и версии
        задачи, иначе результаты предыдущего прогона будут переиспользованы.
        """
        spec = self._spec(code)
        plan = self._plan(spec)
        state = _RunState(total=len(plan), prefix=self._checkpoint_prefix(ctx))
        started = self._clock()
        try:
            output = await self._ensure(code, dict(inputs), ctx, state, on_progress, timeout_s)
        except asyncio.CancelledError:
            for task in state.tasks.values():  # отмена job не оставляет «висящих» шагов
                task.cancel()
            raise
        duration_ms = int((self._clock() - started) * 1000)
        return SkillResult(
            code=code,
            output=output,
            duration_ms=duration_ms,
            attempts=state.attempts.get(code, 0),
        )

    def _plan(self, root: SkillSpec) -> list[SkillSpec]:
        """Топологический порядок зависимостей (циклы и пропуски — SkillFailed)."""
        order: list[SkillSpec] = []
        marks: dict[str, int] = {}

        def visit(spec: SkillSpec) -> None:
            mark = marks.get(spec.code)
            if mark == 1:
                return
            if mark == 0:
                raise SkillFailed(spec.code, "циклическая зависимость навыков")
            marks[spec.code] = 0
            for dep in spec.depends_on:
                visit(self._spec(dep))
            marks[spec.code] = 1
            order.append(spec)

        visit(root)
        return order

    @staticmethod
    def _checkpoint_prefix(ctx: SkillContext) -> str:
        prefix = ctx.extra.get("checkpoint_prefix")
        if prefix:
            return str(prefix)
        program_id = ctx.extra.get("program_id")
        return f"{program_id}:" if program_id else ""

    async def _ensure(
        self,
        code: str,
        inputs: dict[str, Any],
        ctx: SkillContext,
        state: _RunState,
        on_progress: ProgressCallback | None,
        timeout_s: float | None,
    ) -> dict[str, Any]:
        """Единая точка исполнения шага: одна задача на код, повторные ожидания бесплатны."""
        task = state.tasks.get(code)
        if task is None:
            task = asyncio.ensure_future(self._execute(code, inputs, ctx, state, on_progress, timeout_s))
            state.tasks[code] = task
        return await task

    async def _execute(
        self,
        code: str,
        inputs: dict[str, Any],
        ctx: SkillContext,
        state: _RunState,
        on_progress: ProgressCallback | None,
        timeout_s: float | None,
    ) -> dict[str, Any]:
        spec = self._spec(code)
        checkpoint_key = f"{state.prefix}{code}"
        saved = await maybe_await(ctx.checkpoint.load(checkpoint_key))
        if saved is not None:
            state.outputs[code] = saved
            state.done += 1
            self._progress(on_progress, code, state, f"готово: {spec.name} (из сохранённого)")
            return saved

        if spec.depends_on:
            results = await asyncio.gather(
                *(self._ensure(dep, inputs, ctx, state, on_progress, None) for dep in spec.depends_on),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result  # первая по порядку ошибка; остальные задачи уже дождались
        merged = dict(inputs)
        for dep in spec.depends_on:
            merged[dep] = state.outputs[dep]

        effective_timeout = timeout_s if timeout_s is not None else spec.timeout_s
        self._progress(on_progress, code, state, f"старт: {spec.name}")
        output = await self._call(code, spec, merged, ctx, state, effective_timeout)
        state.outputs[code] = output
        state.done += 1
        await maybe_await(ctx.checkpoint.save(checkpoint_key, output))
        self._progress(on_progress, code, state, f"готово: {spec.name}")
        return output

    async def _call(
        self,
        code: str,
        spec: SkillSpec,
        inputs: dict[str, Any],
        ctx: SkillContext,
        state: _RunState,
        timeout_s: float | None,
    ) -> dict[str, Any]:
        func = self._func_for(spec)
        last_error: BaseException | None = None
        for attempt in range(1, self._retries + 1):
            state.attempts[code] = attempt
            try:
                async with self._limiter():
                    coro = func(inputs, ctx)
                    if timeout_s is not None:
                        output = await asyncio.wait_for(coro, timeout=float(timeout_s))
                    else:
                        output = await coro
            except TimeoutError as exc:  # asyncio.TimeoutError — алиас встроенного
                raise SkillFailed(code, f"таймаут {timeout_s} с") from exc
            except TransientError as exc:
                last_error = exc
                if attempt >= self._retries:
                    raise SkillFailed(code, f"временная ошибка после {attempt} попыток: {exc}") from exc
                await self._sleep(self._backoff_delay(attempt - 1))
                continue
            except SkillFailed:
                raise
            except Exception as exc:  # noqa: BLE001 — любая ошибка навыка оборачивается в SkillFailed
                raise SkillFailed(code, f"{type(exc).__name__}: {exc}") from exc
            if not isinstance(output, dict):
                raise SkillFailed(code, f"навык вернул {type(output).__name__}, ожидался dict")
            return output
        raise SkillFailed(code, f"исчерпаны попытки: {last_error}")

    def _limiter(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._concurrency)
        return self._semaphore

    def _backoff_delay(self, attempt: int) -> float:
        return self._backoff_base_s * (2**attempt)

    def _progress(
        self,
        on_progress: ProgressCallback | None,
        code: str,
        state: _RunState,
        label: str,
    ) -> None:
        if on_progress is not None:
            on_progress(code, state.done, state.total, label)


__all__ = ["ProgressCallback", "SkillFailed", "SkillResult", "SkillRunner"]
