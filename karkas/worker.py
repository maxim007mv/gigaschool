"""karkas.worker — цикл воркера: захват задач, исполнение навыков, ретраи (Д4 §9).

Запуск: python -m karkas.worker --concurrency 8
Захват задачи — конкурентно-безопасный SQL (FOR UPDATE SKIP LOCKED, Д2 §11 Q3).
События прогресса публикуются в SSE-шину; каждый навык сохраняет результат,
поэтому перезапуск продолжается с последнего успешного шага.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

import karkas.infra.exporters.bootstrap  # noqa: F401 — регистрация export_program_docx для V-ACR в воркере
from karkas.api.sse import bus
from karkas.infra.db import get_session_factory
from karkas.infra.repos import jobs as jobs_repo
from karkas.logging_setup import get_logger
from karkas.settings import settings

logger = get_logger("karkas.worker")

#: Таймауты по видам задач (Д4 §9, таблица «Типы задач»).
TIMEOUTS_S: dict[str, int] = {
    "intake": 60,
    "framework": settings.framework_slo_s,
    "kit": settings.kit_timeout_min * 60,
    "edit": 300,
    "export": 120,
    "actualize": 600,
    "adapt": 600,
    "maintenance": 3600,
    "agent_run": settings.agent_run_timeout_s,
}


async def _dispatch(job: dict[str, Any], on_progress: Callable[[dict[str, Any]], Any]) -> None:
    """Ленивый импорт пайплайна: навыки собираются отдельно от очереди."""
    from karkas.agent.pipeline import dispatch_job

    await dispatch_job(job, on_progress=on_progress)


async def _backoff_delay(attempts: int) -> float:
    """Экспоненциальная задержка 1 → 2 → 4 с с джиттером."""
    import random

    base = settings.llm_backoff_base_s * (2 ** max(0, attempts - 1))
    return base + random.uniform(0, 0.5)


async def process_one(worker_id: str) -> bool:
    """Обработать одну задачу. Возвращает False, если очередь пуста."""
    factory = get_session_factory()
    async with factory() as session:
        job = await jobs_repo.claim(session, worker_id)
        await session.commit()
    if job is None:
        return False

    job_id = str(job["id"])
    kind = job["kind"]
    program_id = str(job["program_id"]) if job["program_id"] else None
    logger.info("job.claimed", job_id=job_id, kind=kind, program_id=program_id, attempts=job["attempts"])

    async def on_progress(payload: dict[str, Any]) -> None:
        async with factory() as progress_session:
            await jobs_repo.set_progress(progress_session, job_id, payload)
            await progress_session.commit()
        await bus.publish(program_id, "progress", {"job_id": job_id, **payload})

    try:
        async with asyncio.timeout(TIMEOUTS_S.get(kind, 600)):
            await _dispatch(job, on_progress)
        async with factory() as done_session:
            current_status = (
                await done_session.execute(
                    text("SELECT status FROM job WHERE id = CAST(:jid AS uuid)"), {"jid": job_id}
                )
            ).scalar_one_or_none()
            if current_status == "cancelled":
                # Задачу отменили во время выполнения: не перезаписываем статус
                # и не трогаем статус программы (его уже откатил API отмены).
                logger.info("job.cancelled_after_run", job_id=job_id, kind=kind)
                return True
            await jobs_repo.succeed(done_session, job_id)
            await done_session.commit()
        logger.info("job.succeeded", job_id=job_id, kind=kind, program_id=program_id)
        return True
    except Exception as exc:  # noqa: BLE001 — на границе воркера обрабатываем всё
        transient = _is_transient(exc)
        error = {"code": type(exc).__name__, "detail": str(exc)[:2000], "transient": transient}
        attempts = int(job["attempts"] or 1)
        max_attempts = int(job["max_attempts"] or 3)
        async with factory() as error_session:
            if transient and attempts < max_attempts:
                delay = await _backoff_delay(attempts)
                await jobs_repo.retry(error_session, job_id, delay_s=delay, error=error)
                will_retry = True
            else:
                await jobs_repo.fail(error_session, job_id, error)
                will_retry = False
                await _restore_status_after_failure(error_session, job)
            await error_session.commit()
        logger.error(
            "job.failed",
            job_id=job_id,
            kind=kind,
            program_id=program_id,
            code=error["code"],
            will_retry=will_retry,
            exc_info=not will_retry,
        )
        await bus.publish(
            program_id,
            "job_failed",
            {"job_id": job_id, "code": error["code"], "detail": error["detail"], "will_retry": will_retry},
        )
        return True


def _is_transient(exc: Exception) -> bool:
    """Транзиентные ошибки (429/5xx/таймаут модели) — повторяем; остальные — нет."""
    from karkas.agent.llm_gateway import TransientError  # ленивый импорт

    return isinstance(exc, (TransientError, asyncio.TimeoutError, TimeoutError))


#: Технические статусы, которые откатываются при окончательном провале задачи.
GENERATING_STATUSES: dict[str, tuple[str, ...]] = {
    "framework": ("framework_generating",),
    "kit": ("kit_generating",),
}


async def _restore_status_after_failure(session: Any, job: dict[str, Any]) -> None:
    """Не оставлять программу залипшей в *_generating после провала задачи (Д1 §14).

    Предыдущий статус кладётся в payload при постановке задачи (prev_status).
    """
    kind = job.get("kind")
    expected = GENERATING_STATUSES.get(kind)
    payload = job.get("payload") or {}
    prev_status = payload.get("prev_status")
    if not expected or not prev_status or not job.get("program_id"):
        return
    restored = await jobs_repo.restore_program_status(
        session,
        program_id=str(job["program_id"]),
        prev_status=str(prev_status),
        expected_current=expected,
    )
    if restored:
        logger.info("program.status_restored", program_id=str(job["program_id"]), to=prev_status, job_kind=kind)
    # Правка, упавшая навсегда, не должна «висеть» в статусе running.
    if kind == "edit" and payload.get("edit_id"):
        await session.execute(
            text("UPDATE edit_request SET status = 'failed' WHERE id = CAST(:eid AS uuid)"),
            {"eid": str(payload["edit_id"])},
        )


async def loop(worker_id: str, *, poll_interval_s: float = 2.0) -> None:
    """Основной цикл воркера: захват задач (LISTEN/NOTIFY job_ready шлётся
    постановщиком, воркер опрашивает очередь с шагом poll_interval_s)."""

    async def _tick() -> None:
        while True:
            processed = await process_one(worker_id)
            if not processed:
                await _update_queue_metrics()
                await asyncio.sleep(poll_interval_s)

    await _tick()


async def _update_queue_metrics() -> None:
    """Обновить karkas_queue_depth (по ней в профиле B масштабируется worker)."""
    from karkas.infra.metrics import queue_depth as queue_depth_gauge

    factory = get_session_factory()
    try:
        async with factory() as session:
            depth = await jobs_repo.queue_depth(session)
        queue_depth_gauge.set(depth)
    except Exception:
        pass  # метрика не должна ломать цикл


async def maintenance_once() -> None:
    """Обслуживание воркера: возврат зависших задач, секции, кэш (Д1 §14, Д2 §8)."""
    factory = get_session_factory()
    async with factory() as session:
        recovered, failed = await jobs_repo.recover_stuck(session)
        await session.commit()
    if recovered or failed:
        logger.info("maintenance.recovered", recovered=recovered, failed=failed)
    # Секции llm_call/audit_log на 3 месяца и очистка просроченного кэша моделей.
    from karkas.agent.pipeline import maintenance_core

    async with factory() as session:
        try:
            result = await maintenance_core(session, {})
            await session.commit()
            logger.info("maintenance.done", **result)
        except Exception:
            await session.rollback()
            logger.exception("maintenance.failed")


def worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="КАРКАС: воркер очереди задач")
    parser.add_argument("--concurrency", type=int, default=1, help="число параллельных задач")
    args = parser.parse_args()

    from karkas.logging_setup import configure_logging

    configure_logging()

    async def _run() -> None:
        await maintenance_once()
        wid = worker_id()
        concurrency = max(1, args.concurrency)
        logger.info("worker.started", worker_id=wid, concurrency=concurrency)
        # Один процесс воркера, до concurrency параллельных захватов задач (общий worker_id).
        await asyncio.gather(*[loop(wid) for _ in range(concurrency)])

    asyncio.run(_run())


if __name__ == "__main__":
    main()
