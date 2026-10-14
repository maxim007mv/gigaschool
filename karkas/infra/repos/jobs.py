"""karkas.infra.repos.jobs — очередь задач на PostgreSQL (Д2 §11 Q3, Д4 §9).

Захват задачи: SELECT … FOR UPDATE SKIP LOCKED + LISTEN/NOTIFY job_ready.
Зависшие задачи возвращаются в очередь; каждая задача хранит прогресс и попытки.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CLAIM_SQL = """
WITH next AS (
    SELECT id FROM job
    WHERE status IN ('queued', 'retry_wait') AND run_after <= now()
    ORDER BY priority, run_after
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
UPDATE job j
SET status = 'running', locked_by = :worker_id, locked_at = now(), attempts = j.attempts + 1
FROM next
WHERE j.id = next.id
RETURNING j.id, j.program_id, j.kind, j.priority, j.payload, j.progress, j.attempts, j.max_attempts
"""


async def enqueue(
    session: AsyncSession,
    *,
    kind: str,
    program_id: str | None = None,
    payload: dict[str, Any] | None = None,
    priority: int = 5,
    idempotency_key: str | None = None,
    run_after_s: int = 0,
) -> str:
    """Поставить задачу. При повторном idempotency_key возвращает существующий job_id.

    Ключ уникален в таблице job: повторное использование того же ключа для НОВОЙ
    попытки невозможно — вызывающий код обязан генерировать уникальный ключ на
    попытку (дедупликацию двойных кликов обеспечивает has_active/HTTP-ключ).
    """
    row = (
        await session.execute(
            text(
                """
                INSERT INTO job (program_id, kind, priority, payload, idempotency_key, run_after)
                VALUES (CAST(:pid AS uuid), :kind, :priority, CAST(:payload AS jsonb), :idem,
                        now() + make_interval(secs => :delay))
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """
            ),
            {
                "pid": program_id,
                "kind": kind,
                "priority": priority,
                "payload": json.dumps(payload or {}, ensure_ascii=False),
                "idem": idempotency_key,
                "delay": run_after_s,
            },
        )
    ).scalar_one_or_none()
    if row is not None:
        from karkas.infra.metrics import jobs_enqueued_total

        jobs_enqueued_total.labels(kind=kind).inc()
        await session.execute(text("NOTIFY job_ready"))
        return str(row)
    existing = (
        await session.execute(
            text("SELECT id FROM job WHERE idempotency_key = :idem"),
            {"idem": idempotency_key},
        )
    ).scalar_one()
    return str(existing)


async def find_by_idempotency(
    session: AsyncSession, idempotency_key: str, *, org_id: str | None = None
) -> dict[str, Any] | None:
    """Найти задачу по ключу идемпотентности (HTTP Idempotency-Key, TTL 24 ч).

    При передаче org_id результат ограничивается программами этой организации —
    чужой ключ не может раскрыть метаданные другого тенанта.
    """
    sql = """
        SELECT j.*, p.status AS program_status, p.title AS program_title
        FROM job j LEFT JOIN program p ON p.id = j.program_id
        WHERE j.idempotency_key = :idem AND j.created_at > now() - interval '24 hours'
    """
    params: dict[str, Any] = {"idem": idempotency_key}
    if org_id is not None:
        sql += " AND p.org_id = :org_id"
        params["org_id"] = org_id
    row = (await session.execute(text(sql), params)).mappings().first()
    return dict(row) if row else None


async def claim(session: AsyncSession, worker_id: str) -> dict[str, Any] | None:
    """Конкурентно-безопасный захват следующей задачи."""
    row = (await session.execute(text(CLAIM_SQL), {"worker_id": worker_id})).mappings().first()
    return dict(row) if row else None


async def get_job(session: AsyncSession, job_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT j.*, p.org_id AS program_org_id FROM job j
                LEFT JOIN program p ON p.id = j.program_id
                WHERE j.id = CAST(:jid AS uuid)
                """
            ),
            {"jid": job_id},
        )
    ).mappings().first()
    return dict(row) if row else None


async def set_progress(session: AsyncSession, job_id: str, progress: dict[str, Any]) -> None:
    await session.execute(
        text("UPDATE job SET progress = CAST(:progress AS jsonb) WHERE id = CAST(:jid AS uuid)"),
        {"jid": job_id, "progress": json.dumps(progress, ensure_ascii=False)},
    )


async def succeed(session: AsyncSession, job_id: str) -> None:
    await session.execute(
        text(
            """
            UPDATE job SET status = 'succeeded', finished_at = now(), locked_by = NULL, locked_at = NULL
            WHERE id = CAST(:jid AS uuid)
            """
        ),
        {"jid": job_id},
    )


async def fail(session: AsyncSession, job_id: str, error: dict[str, Any]) -> None:
    await session.execute(
        text(
            """
            UPDATE job SET status = 'failed', error = CAST(:error AS jsonb),
                           finished_at = now(), locked_by = NULL, locked_at = NULL
            WHERE id = CAST(:jid AS uuid)
            """
        ),
        {"jid": job_id, "error": json.dumps(error, ensure_ascii=False, default=str)},
    )


async def retry(session: AsyncSession, job_id: str, *, delay_s: float, error: dict[str, Any]) -> None:
    await session.execute(
        text(
            """
            UPDATE job SET status = 'retry_wait', error = CAST(:error AS jsonb),
                           run_after = now() + make_interval(secs => :delay),
                           locked_by = NULL, locked_at = NULL
            WHERE id = CAST(:jid AS uuid)
            """
        ),
        {"jid": job_id, "delay": delay_s, "error": json.dumps(error, ensure_ascii=False, default=str)},
    )


async def cancel(session: AsyncSession, job_id: str) -> bool:
    row = (
        await session.execute(
            text(
                """
                UPDATE job SET status = 'cancelled', finished_at = now()
                WHERE id = CAST(:jid AS uuid) AND status IN ('queued', 'retry_wait', 'running')
                RETURNING id
                """
            ),
            {"jid": job_id},
        )
    ).scalar_one_or_none()
    return row is not None


#: Порог «зависла» по видам задач — 2 × таймаут вида (Д4 §9).
KIND_STUCK_SECONDS: dict[str, int] = {
    "intake": 120,
    "framework": 360,
    "kit": 2400,
    "edit": 600,
    "export": 240,
    "actualize": 1200,
    "adapt": 1200,
    "maintenance": 7200,
}

#: Технические статусы программы, откатываемые при «зависании» задачи.
_GENERATING_STATUSES: dict[str, tuple[str, ...]] = {
    "framework": ("framework_generating",),
    "kit": ("kit_generating",),
}


async def recover_stuck(session: AsyncSession, *, kind_timeouts: dict[str, int] | None = None) -> tuple[int, int]:
    """Вернуть зависшие задачи в очередь; исчерпавшие попытки — в failed.

    Порог зависания — по виду задачи (раньше был единый 360 с: kit с таймаутом
    20 мин «восстанавливался» раньше времени и запускался вторым воркером).
    Возвращает (возвращено_в_очередь, помечено_failed).
    """
    timeouts = {**KIND_STUCK_SECONDS, **(kind_timeouts or {})}
    recovered = 0
    failed = 0
    for kind, age_seconds in timeouts.items():
        result = await session.execute(
            text(
                """
                UPDATE job SET status = 'retry_wait', locked_by = NULL, locked_at = NULL,
                               run_after = now()
                WHERE status = 'running' AND kind = :kind AND attempts < max_attempts
                  AND locked_at < now() - make_interval(secs => :age)
                """
            ),
            {"kind": kind, "age": age_seconds},
        )
        recovered += int(result.rowcount or 0)

        exhausted = await session.execute(
            text(
                """
                UPDATE job SET status = 'failed', finished_at = now(),
                               locked_by = NULL, locked_at = NULL,
                               error = jsonb_build_object(
                                   'code', 'STUCK',
                                   'detail', 'Задача потеряла воркер, попытки исчерпаны — поставьте её заново',
                                   'transient', false)
                WHERE status = 'running' AND kind = :kind AND attempts >= max_attempts
                  AND locked_at < now() - make_interval(secs => :age)
                RETURNING program_id, payload
                """
            ),
            {"kind": kind, "age": age_seconds},
        )
        for row in exhausted.mappings().all():
            failed += 1
            # Не оставляем программу в *_generating (dead-end без выхода через API).
            expected = _GENERATING_STATUSES.get(kind)
            payload = row["payload"] or {}
            prev_status = payload.get("prev_status")
            if expected and prev_status and row["program_id"]:
                await restore_program_status(
                    session,
                    program_id=str(row["program_id"]),
                    prev_status=str(prev_status),
                    expected_current=expected,
                )
    return recovered, failed


async def restore_program_status(
    session: AsyncSession, *, program_id: str, prev_status: str, expected_current: tuple[str, ...]
) -> bool:
    """Откатить статус программы после провала/отмены задачи (выход из *_generating).

    Возвращает True, если статус был откатан. Откат выполняется только если
    программа всё ещё в ожидаемом «техническом» статусе.
    """
    result = await session.execute(
        text(
            """
            UPDATE program SET status = CAST(:prev AS program_status)
            WHERE id = CAST(:pid AS uuid) AND status = ANY(:expected)
            """
        ),
        {"pid": program_id, "prev": prev_status, "expected": list(expected_current)},
    )
    return bool(result.rowcount)


async def has_active(session: AsyncSession, *, program_id: str, kind: str) -> bool:
    """Есть ли уже выполняемая/ожидающая задача того же типа по программе (409 JOB_IN_PROGRESS)."""
    count = (
        await session.execute(
            text(
                """
                SELECT count(*) FROM job
                WHERE program_id = CAST(:pid AS uuid) AND kind = :kind
                  AND status IN ('queued', 'running', 'retry_wait')
                """
            ),
            {"pid": program_id, "kind": kind},
        )
    ).scalar_one()
    return int(count) > 0


async def queue_depth(session: AsyncSession) -> int:
    """Число задач, ожидающих обработки (для метрики karkas_queue_depth / HPA)."""
    count = (
        await session.execute(
            text("SELECT count(*) FROM job WHERE status IN ('queued', 'retry_wait')")
        )
    ).scalar_one()
    return int(count)
