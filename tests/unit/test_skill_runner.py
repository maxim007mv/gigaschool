"""Тесты раннера навыков: зависимости, параллелизм, таймауты, ретраи, чекпоинты, прогресс."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from karkas.agent.llm_gateway import TransientError
from karkas.agent.skill_runner import SkillFailed, SkillResult, SkillRunner
from karkas.agent.skills._base import InMemoryCheckpointStore, SkillContext, SkillSpec
from karkas.settings import Settings


def make_settings(**overrides) -> Settings:
    base = dict(environment="test", llm_concurrency=2, llm_backoff_base_s=0.01)
    base.update(overrides)
    return Settings(**base)


def make_ctx(
    prefix: str = "test:",
    checkpoint: InMemoryCheckpointStore | None = None,
    **extra: Any,
) -> SkillContext:
    return SkillContext(
        settings=make_settings(),
        checkpoint=checkpoint if checkpoint is not None else InMemoryCheckpointStore(),
        extra={"checkpoint_prefix": prefix, **extra},
    )


def add_skill(
    runner: SkillRunner,
    code: str,
    func,
    deps: tuple[str, ...] = (),
    timeout_s: float | None = None,
) -> SkillSpec:
    spec = SkillSpec(
        code=code,
        name=f"Навык {code}",
        dir=f"{code}_test",
        depends_on=deps,
        timeout_s=timeout_s,
    )
    runner.register(spec, func)
    return spec


def make_runner(**overrides) -> SkillRunner:
    return SkillRunner(settings=make_settings(), **overrides)


async def test_dependencies_run_before_dependent() -> None:
    calls: list[str] = []
    seen_inputs: dict[str, dict] = {}

    async def make(name: str):
        async def impl(inputs: dict, ctx: SkillContext) -> dict:
            calls.append(name)
            seen_inputs[name] = inputs
            return {"name": name}

        return impl

    runner = make_runner()
    add_skill(runner, "SA", await make("A"))
    add_skill(runner, "SB", await make("B"), deps=("SA",))
    add_skill(runner, "SC", await make("C"), deps=("SB",))

    result = await runner.run("SC", {"brief": "x"}, make_ctx())

    assert calls == ["A", "B", "C"]
    assert isinstance(result, SkillResult)
    assert result.code == "SC"
    assert result.attempts == 1
    assert result.output == {"name": "C"}
    assert result.duration_ms >= 0
    assert seen_inputs["B"]["SA"] == {"name": "A"}
    assert seen_inputs["C"]["SB"] == {"name": "B"}
    assert seen_inputs["C"]["brief"] == "x"


async def test_independent_dependencies_run_in_parallel() -> None:
    async def slow_a(inputs: dict, ctx: SkillContext) -> dict:
        await asyncio.sleep(0.05)
        return {"a": 1}

    async def slow_b(inputs: dict, ctx: SkillContext) -> dict:
        await asyncio.sleep(0.05)
        return {"b": 2}

    async def root(inputs: dict, ctx: SkillContext) -> dict:
        return {"ok": True}

    runner = make_runner()
    add_skill(runner, "SA", slow_a)
    add_skill(runner, "SB", slow_b)
    add_skill(runner, "SR", root, deps=("SA", "SB"))

    started = time.monotonic()
    await runner.run("SR", {}, make_ctx())
    elapsed = time.monotonic() - started

    assert elapsed < 0.095  # последовательно было бы ≥ 0.10


async def test_shared_dependency_executed_once() -> None:
    counter = {"n": 0}

    async def shared(inputs: dict, ctx: SkillContext) -> dict:
        counter["n"] += 1
        await asyncio.sleep(0.01)
        return {"shared": True}

    async def left(inputs: dict, ctx: SkillContext) -> dict:
        return {"left": inputs["SD"]}

    async def right(inputs: dict, ctx: SkillContext) -> dict:
        return {"right": inputs["SD"]}

    async def root(inputs: dict, ctx: SkillContext) -> dict:
        return {"ok": True}

    runner = make_runner()
    add_skill(runner, "SD", shared)
    add_skill(runner, "SL", left, deps=("SD",))
    add_skill(runner, "SR", right, deps=("SD",))
    add_skill(runner, "SX", root, deps=("SL", "SR"))

    await runner.run("SX", {}, make_ctx())
    assert counter["n"] == 1


async def test_timeout_wrapped_in_skill_failed() -> None:
    async def slow(inputs: dict, ctx: SkillContext) -> dict:
        await asyncio.sleep(0.2)
        return {}

    runner = make_runner()
    add_skill(runner, "SX", slow)

    with pytest.raises(SkillFailed) as excinfo:
        await runner.run("SX", {}, make_ctx(), timeout_s=0.02)
    assert excinfo.value.code == "SX"
    assert "таймаут" in str(excinfo.value)


async def test_timeout_from_spec_is_used() -> None:
    async def slow(inputs: dict, ctx: SkillContext) -> dict:
        await asyncio.sleep(0.2)
        return {}

    runner = make_runner()
    add_skill(runner, "SX", slow, timeout_s=0.02)

    with pytest.raises(SkillFailed):
        await runner.run("SX", {}, make_ctx())


async def test_retry_on_transient_error() -> None:
    attempts = {"n": 0}
    delays: list[float] = []

    async def flaky(inputs: dict, ctx: SkillContext) -> dict:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TransientError("429")
        return {"ok": True}

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    runner = make_runner(sleep=fake_sleep, backoff_base_s=0.05)
    add_skill(runner, "SX", flaky)

    result = await runner.run("SX", {}, make_ctx())

    assert result.attempts == 3
    assert result.output == {"ok": True}
    assert delays == [0.05, 0.1]


async def test_transient_exhausted_becomes_skill_failed() -> None:
    async def always_transient(inputs: dict, ctx: SkillContext) -> dict:
        raise TransientError("провайдер недоступен")

    runner = make_runner()
    add_skill(runner, "SX", always_transient)

    with pytest.raises(SkillFailed) as excinfo:
        await runner.run("SX", {}, make_ctx())
    assert excinfo.value.code == "SX"
    assert "после 3 попыток" in str(excinfo.value)


async def test_checkpoint_resume_skips_completed_steps() -> None:
    calls = {"a": 0, "b": 0}

    async def first_a(inputs: dict, ctx: SkillContext) -> dict:
        calls["a"] += 1
        return {"value": 1}

    async def first_b(inputs: dict, ctx: SkillContext) -> dict:
        calls["b"] += 1
        return {"from": inputs["SA"]}

    store = InMemoryCheckpointStore()
    ctx = make_ctx(checkpoint=store)

    runner1 = make_runner()
    add_skill(runner1, "SA", first_a)
    add_skill(runner1, "SB", first_b, deps=("SA",))
    result1 = await runner1.run("SB", {}, ctx)
    assert calls == {"a": 1, "b": 1}
    assert set(store.keys()) == {"test:SA", "test:SB"}

    async def must_not_run(inputs: dict, ctx: SkillContext) -> dict:
        raise AssertionError("шаг не должен выполняться при возобновлении")

    runner2 = make_runner()
    add_skill(runner2, "SA", must_not_run)
    add_skill(runner2, "SB", must_not_run, deps=("SA",))
    result2 = await runner2.run("SB", {}, ctx)

    assert calls == {"a": 1, "b": 1}
    assert result2.output == result1.output
    assert result2.attempts == 0


async def test_progress_events_sequence() -> None:
    events: list[tuple[str, int, int, str]] = []

    def on_progress(code: str, done: int, total: int, label: str) -> None:
        events.append((code, done, total, label))

    async def step(inputs: dict, ctx: SkillContext) -> dict:
        return {}

    runner = make_runner()
    add_skill(runner, "SA", step)
    add_skill(runner, "SB", step, deps=("SA",))

    await runner.run("SB", {}, make_ctx(), on_progress=on_progress)

    assert [(e[0], e[1]) for e in events] == [("SA", 0), ("SA", 1), ("SB", 1), ("SB", 2)]
    assert all(e[2] == 2 for e in events)
    assert "старт" in events[0][3] and "готово" in events[1][3]


async def test_missing_dependency_fails_with_code() -> None:
    async def step(inputs: dict, ctx: SkillContext) -> dict:
        return {}

    runner = make_runner()
    add_skill(runner, "SX", step, deps=("S99",))

    with pytest.raises(SkillFailed) as excinfo:
        await runner.run("SX", {}, make_ctx())
    assert excinfo.value.code == "S99"


async def test_cycle_detection() -> None:
    async def step(inputs: dict, ctx: SkillContext) -> dict:
        return {}

    runner = make_runner()
    add_skill(runner, "SA", step, deps=("SB",))
    add_skill(runner, "SB", step, deps=("SA",))

    with pytest.raises(SkillFailed) as excinfo:
        await runner.run("SA", {}, make_ctx())
    assert "циклическая" in str(excinfo.value)


async def test_unknown_skill_fails() -> None:
    runner = make_runner()
    with pytest.raises(SkillFailed) as excinfo:
        await runner.run("S00", {}, make_ctx())
    assert excinfo.value.code == "S00"


async def test_duplicate_registration_rejected() -> None:
    async def step(inputs: dict, ctx: SkillContext) -> dict:
        return {}

    runner = make_runner()
    add_skill(runner, "SX", step)
    with pytest.raises(ValueError):
        add_skill(runner, "SX", step)


async def test_skill_error_wrapped_with_cause() -> None:
    async def boom(inputs: dict, ctx: SkillContext) -> dict:
        raise ValueError("плохие данные")

    runner = make_runner()
    add_skill(runner, "SX", boom)

    with pytest.raises(SkillFailed) as excinfo:
        await runner.run("SX", {}, make_ctx())
    assert excinfo.value.code == "SX"
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert "плохие данные" in str(excinfo.value)


async def test_non_dict_output_rejected() -> None:
    async def bad(inputs: dict, ctx: SkillContext) -> list:
        return [1, 2, 3]

    runner = make_runner()
    add_skill(runner, "SX", bad)

    with pytest.raises(SkillFailed) as excinfo:
        await runner.run("SX", {}, make_ctx())
    assert "ожидался dict" in str(excinfo.value)


async def test_semaphore_limits_parallel_skills() -> None:
    active = {"now": 0, "max": 0}

    async def worker(inputs: dict, ctx: SkillContext) -> dict:
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return {}

    async def root(inputs: dict, ctx: SkillContext) -> dict:
        return {}

    runner = make_runner(concurrency=2)
    codes = [f"S{i}" for i in range(5)]
    for code in codes:
        add_skill(runner, code, worker)
    add_skill(runner, "SR", root, deps=tuple(codes))

    await runner.run("SR", {}, make_ctx())
    assert active["max"] <= 2
