"""karkas.infra.repos.programs — программы, уточнения, версии, аудит.

Соответствует таблицам program, clarification, program_version, audit_log (Д2 §5.1).
Инварианты Human Gate обеспечиваются триггером БД program_gate; роутеры делают
предварительные проверки для понятных ошибок (HOURS_MISMATCH, GATE_NOT_PASSED).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.infra.sql_dialect import json_param, uses_sqlite, uuid_param

STATUS_GATE = ("framework_approved", "kit_generating", "kit_review", "kit_updating")


def _coerce_json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value or "{}")
    if isinstance(value, dict):
        return value
    return {}


async def create_program(
    session: AsyncSession,
    *,
    org_id: str,
    owner_id: str,
    title: str = "Новая программа",
    profile: dict[str, Any] | None = None,
    brief: str | None = None,
) -> str:
    """Создать черновик программы; возвращает id."""
    profile_payload = dict(profile or {})
    if brief is not None:
        profile_payload.setdefault("brief", brief)
    program_id = str(uuid.uuid4())
    prof = json_param("profile")
    if uses_sqlite():
        sql = f"""
            INSERT INTO program (id, org_id, owner_id, title, profile)
            VALUES (:id, :org_id, :owner_id, :title, {prof})
        """
        params = {
            "id": program_id,
            "org_id": org_id,
            "owner_id": owner_id,
            "title": title,
            "profile": json.dumps(profile_payload, ensure_ascii=False),
        }
        await session.execute(text(sql), params)
        return program_id
    row = (
        await session.execute(
            text(
                f"""
                INSERT INTO program (org_id, owner_id, title, profile)
                VALUES (:org_id, :owner_id, :title, {prof})
                RETURNING id
                """
            ),
            {
                "org_id": org_id,
                "owner_id": owner_id,
                "title": title,
                "profile": json.dumps(profile_payload, ensure_ascii=False),
            },
        )
    ).scalar_one()
    return str(row)


async def get_program(session: AsyncSession, program_id: str, org_id: str | None = None) -> dict[str, Any] | None:
    sql = """
        SELECT p.*, o.name AS org_name, o.requisites AS org_requisites
        FROM program p JOIN organization o ON o.id = p.org_id
        WHERE p.id = :pid
    """
    params: dict[str, Any] = {"pid": program_id}
    if org_id is not None:
        sql += " AND p.org_id = :org_id"
        params["org_id"] = org_id
    row = (await session.execute(text(sql), params)).mappings().first()
    if not row:
        return None
    data = dict(row)
    if "profile" in data:
        data["profile"] = _coerce_json(data["profile"])
    if "constraints" in data:
        data["constraints"] = _coerce_json(data["constraints"])
    return data


async def list_programs(
    session: AsyncSession,
    *,
    org_id: str,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> list[dict[str, Any]]:
    """Курсорная пагинация по (updated_at DESC, id).

    Cursor — строка `"<iso-timestamp>|<uuid>"`; приводится к типам datetime/uuid
    до подстановки (asyncpg не принимает строку в timestamptz-параметр).
    """
    from datetime import datetime as datetime_type

    sql = """
        SELECT id, title, kind, total_hours, status, updated_at
        FROM program
        WHERE org_id = :org_id
    """
    params: dict[str, Any] = {"org_id": org_id, "limit": limit}
    # UI шлёт status=all / kind=all как «без фильтра»; в enum такого значения нет.
    if status and status != "all":
        sql += " AND status = :status" if uses_sqlite() else " AND status = CAST(:status AS program_status)"
        params["status"] = status
    if kind and kind != "all":
        sql += " AND kind = :kind" if uses_sqlite() else " AND kind = CAST(:kind AS program_kind)"
        params["kind"] = kind
    if cursor:
        cursor_ts, _, cursor_id = cursor.partition("|")
        try:
            params["cursor_ts"] = datetime_type.fromisoformat(cursor_ts)
            params["cursor_id"] = uuid.UUID(cursor_id)
        except (ValueError, TypeError) as exc:
            raise ValueError("Некорректный cursor пагинации") from exc
        sql += " AND (updated_at, id) < (:cursor_ts, :cursor_id)"
    sql += " ORDER BY updated_at DESC, id DESC LIMIT :limit"
    rows = (await session.execute(text(sql), params)).mappings().all()
    return [dict(r) for r in rows]


def make_cursor(row: dict[str, Any]) -> str:
    return f"{row['updated_at'].isoformat()}|{row['id']}"


async def update_program(
    session: AsyncSession,
    *,
    program_id: str,
    fields: dict[str, Any],
    org_id: str | None = None,
    expected_lock_version: int | None = None,
) -> int | None:
    """Обновить поля программы; lock_version и updated_at инкрементирует триггер БД.

    ``expected_lock_version`` превращает проверку If-Match в атомарный CAS:
    UPDATE выполняется только если версия не изменилась (иначе None → 412).
    Возвращает новый lock_version или None, если программа не найдена/версия устарела.
    """
    allowed = {"title", "kind", "form", "total_hours", "final_att_hours", "final_att_form", "goal", "profile", "constraints"}
    sets: list[str] = []
    params: dict[str, Any] = {"pid": program_id}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"Поле {key} нельзя обновлять через update_program")
        param = f"v_{key}"  # уникальное имя параметра на каждое поле
        if key in ("profile", "constraints"):
            sets.append(f"{key} = CAST(:{param} AS jsonb)")
            params[param] = json.dumps(value, ensure_ascii=False)
        elif key == "kind":
            sets.append(f"{key} = CAST(:{param} AS program_kind)")
            params[param] = value
        elif key == "form":
            sets.append(f"{key} = CAST(:{param} AS program_form)")
            params[param] = value
        else:
            sets.append(f"{key} = :{param}")
            params[param] = value
    if not sets:
        return None
    sql = f"UPDATE program SET {', '.join(sets)} WHERE id = :pid"
    if org_id is not None:
        sql += " AND org_id = :org_id"
        params["org_id"] = org_id
    if expected_lock_version is not None:
        sql += " AND lock_version = :expected_lock_version"
        params["expected_lock_version"] = expected_lock_version
    sql += " RETURNING lock_version"
    row = (await session.execute(text(sql), params)).scalar_one_or_none()
    return int(row) if row is not None else None


async def set_status(
    session: AsyncSession,
    *,
    program_id: str,
    status: str,
    approved_by: str | None = None,
    expected_lock_version: int | None = None,
) -> int | None:
    """Смена статуса. Триггер program_gate сам проверит Human Gate и бросит исключение.

    ``expected_lock_version`` — атомарный CAS для approve (If-Match).
    """
    sql = """
        UPDATE program
        SET status = CAST(:status AS program_status),
            approved_by = CASE WHEN :status = 'framework_approved' THEN CAST(:approved_by AS uuid) ELSE approved_by END,
            approved_at = CASE WHEN :status = 'framework_approved' THEN now() ELSE approved_at END
        WHERE id = :pid
    """
    params: dict[str, Any] = {"pid": program_id, "status": status, "approved_by": approved_by}
    if expected_lock_version is not None:
        sql += " AND lock_version = :expected_lock_version"
        params["expected_lock_version"] = expected_lock_version
    sql += " RETURNING lock_version"
    row = (await session.execute(text(sql), params)).scalar_one_or_none()
    return int(row) if row is not None else None


async def reopen(session: AsyncSession, *, program_id: str) -> int | None:
    sql = """
        UPDATE program
        SET status = 'framework_review', approved_by = NULL, approved_at = NULL
        WHERE id = :pid AND status IN ('framework_approved', 'kit_review', 'kit_updating')
        RETURNING lock_version
    """
    row = (await session.execute(text(sql), {"pid": program_id})).scalar_one_or_none()
    return int(row) if row is not None else None


async def hours_issues(session: AsyncSession, program_id: str) -> list[dict[str, str]]:
    """Нарушения часов программы (V-HRS-01..05) через функцию БД check_program_hours."""
    if uses_sqlite():
        from karkas.domain.validators import ValidationContext, run_validation
        from karkas.infra.repos import framework as framework_repo

        program = await get_program(session, program_id)
        kit = await framework_repo.load_kit(session, program_id)
        if program is None or kit is None:
            return [{"rule_code": "V-HRS-01", "entity_ref": None, "message": "Каркас не найден"}]
        issues: list[dict[str, str]] = []
        if kit.grand_total() != int(program.get("total_hours") or 0):
            issues.append(
                {
                    "rule_code": "V-HRS-01",
                    "entity_ref": None,
                    "message": f"Сумма {kit.grand_total()} из {program.get('total_hours')} ч",
                }
            )
        report = run_validation(ValidationContext(kit=kit, stage="framework"))
        for item in report.errors:
            if item.rule_code.startswith("V-HRS"):
                issues.append(
                    {
                        "rule_code": item.rule_code,
                        "entity_ref": item.entity_ref,
                        "message": item.message,
                    }
                )
        return issues
    pid = uuid_param("pid")
    rows = (
        await session.execute(
            text(f"SELECT rule_code, entity_ref, message FROM check_program_hours({pid})"),
            {"pid": program_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


# --- Уточнения ---------------------------------------------------------------


async def replace_questions(
    session: AsyncSession, *, program_id: str, questions: list[dict[str, Any]]
) -> None:
    """Обновить уточняющие вопросы (≤ 5, ord 1..5).

    Отвеченные вопросы НЕ удаляются (ответы пользователя сохраняются при повторном
    intake); незакрытые слоты добавляются на свободные позиции ord.
    Принимает и `text`, и `question` (формат выхода S03).
    """
    rows = (
        await session.execute(
            text("SELECT slot, ord, answer FROM clarification WHERE program_id = :pid"),
            {"pid": program_id},
        )
    ).mappings().all()
    answered_slots = {row["slot"] for row in rows if row["answer"] is not None}
    await session.execute(
        text("DELETE FROM clarification WHERE program_id = :pid AND answer IS NULL"), {"pid": program_id}
    )
    remaining = [row for row in rows if row["answer"] is not None]
    used_ords = {row["ord"] for row in remaining}
    used_slots = {row["slot"] for row in remaining}

    for q in questions[:5]:
        slot = str(q.get("slot") or "").strip()
        text_value = str(q.get("text") or q.get("question") or "").strip()
        if not slot or not text_value or slot in used_slots or slot in answered_slots:
            continue
        free_ord = next((ord_value for ord_value in range(1, 6) if ord_value not in used_ords), None)
        if free_ord is None:
            break
        qid = str(uuid.uuid4())
        opts = json_param("options")
        if uses_sqlite():
            await session.execute(
                text(
                    f"""
                    INSERT INTO clarification (id, program_id, slot, question, options, ord)
                    VALUES (:qid, :pid, :slot, :question, {opts}, :ord)
                    """
                ),
                {
                    "qid": qid,
                    "pid": program_id,
                    "slot": slot,
                    "question": text_value,
                    "options": json.dumps(q.get("options", []), ensure_ascii=False),
                    "ord": free_ord,
                },
            )
        else:
            await session.execute(
                text(
                    f"""
                    INSERT INTO clarification (program_id, slot, question, options, ord)
                    VALUES (:pid, :slot, :question, {opts}, :ord)
                    RETURNING id
                    """
                ),
                {
                    "pid": program_id,
                    "slot": slot,
                    "question": text_value,
                    "options": json.dumps(q.get("options", []), ensure_ascii=False),
                    "ord": free_ord,
                },
            )
        used_ords.add(free_ord)
        used_slots.add(slot)


async def get_questions(session: AsyncSession, program_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT c.*, c.options AS options
                FROM clarification c
                WHERE c.program_id = :pid
                ORDER BY c.ord
                """
            ),
            {"pid": program_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def save_answers(
    session: AsyncSession,
    *,
    program_id: str,
    answers: dict[str, str | None],
    use_default: set[str],
    answered_by: str | None = None,
) -> None:
    """Записать ответы: {вопрос_id: значение}. use_default → is_default=true."""
    for question_id, value in answers.items():
        await session.execute(
            text(
                """
                UPDATE clarification
                SET answer = :answer,
                    is_default = :is_default,
                    answered_by = CAST(:answered_by AS uuid),
                    answered_at = now()
                WHERE id = CAST(:qid AS uuid) AND program_id = :pid
                """
            ),
            {
                "answer": value,
                "is_default": question_id in use_default,
                "answered_by": answered_by,
                "qid": question_id,
                "pid": program_id,
            },
        )


async def open_questions_count(session: AsyncSession, program_id: str) -> int:
    return int(
        (
            await session.execute(
                text("SELECT count(*) FROM clarification WHERE program_id = :pid AND answer IS NULL"),
                {"pid": program_id},
            )
        ).scalar_one()
    )


async def required_slots_filled(session: AsyncSession, program_id: str) -> bool:
    """Обязательные слоты заполнены: ответами на вопросы или зафиксированными допущениями.

    Вопросов не больше 5 (CHECK ord 1..5), а обязательных слотов шесть, поэтому
    часть слотов закрывается значениями по умолчанию — они записываются в
    program.profile.slot_defaults (и попадают в допущения отчёта, Д4 §5.2).
    """
    required = ("kind", "total_hours", "audience", "entry_level", "form", "final_attestation")
    slot_filter = (
        "slot IN ('kind','total_hours','audience','entry_level','form','final_attestation')"
        if uses_sqlite()
        else "slot = ANY(:slots)"
    )
    slot_params: dict[str, Any] = {"pid": program_id}
    if not uses_sqlite():
        slot_params["slots"] = list(required)
    answered = set(
        (
            await session.execute(
                text(
                    f"""
                    SELECT slot FROM clarification
                    WHERE program_id = :pid AND answer IS NOT NULL AND {slot_filter}
                    """
                ),
                slot_params,
            )
        ).scalars().all()
    )
    unanswered = int(
        (
            await session.execute(
                text(
                    f"""
                    SELECT count(*) FROM clarification
                    WHERE program_id = :pid AND answer IS NULL AND {slot_filter}
                    """
                ),
                slot_params,
            )
        ).scalar_one()
    )
    if unanswered:
        return False
    profile_raw = (
        await session.execute(
            text("SELECT profile FROM program WHERE id = :pid"), {"pid": program_id}
        )
    ).scalar_one_or_none()
    profile = _coerce_json(profile_raw)
    defaults = set(profile.get("slot_defaults", {}).keys())
    return set(required).issubset(answered | defaults)


async def record_slot_default(
    session: AsyncSession, *, program_id: str, slot: str, value: str
) -> None:
    """Зафиксировать значение по умолчанию для слота («на ваше усмотрение»)."""
    if uses_sqlite():
        profile_raw = (
            await session.execute(
                text("SELECT profile FROM program WHERE id = :pid"), {"pid": program_id}
            )
        ).scalar_one_or_none()
        profile = _coerce_json(profile_raw)
        slot_defaults = dict(profile.get("slot_defaults") or {})
        slot_defaults[slot] = value
        profile["slot_defaults"] = slot_defaults
        await session.execute(
            text("UPDATE program SET profile = :profile WHERE id = :pid"),
            {"pid": program_id, "profile": json.dumps(profile, ensure_ascii=False)},
        )
        return
    entry = json_param("entry")
    await session.execute(
        text(
            f"""
            UPDATE program
            SET profile = jsonb_set(profile, '{{slot_defaults}}',
                                    coalesce(profile->'slot_defaults', '{{}}'::jsonb) || {entry}, true)
            WHERE id = :pid
            """
        ),
        {"pid": program_id, "entry": json.dumps({slot: value}, ensure_ascii=False)},
    )


# --- Версии и аудит ----------------------------------------------------------


async def save_version(
    session: AsyncSession,
    *,
    program_id: str,
    reason: str,
    snapshot: dict[str, Any],
    created_by: str | None = None,
) -> int:
    """Неизменяемый снимок KitV1. Номер = current_version + 1."""
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    version = int(
        (
            await session.execute(
                text("UPDATE program SET current_version = current_version + 1 WHERE id = :pid RETURNING current_version"),
                {"pid": program_id},
            )
        ).scalar_one()
    )
    await session.execute(
        text(
            """
            INSERT INTO program_version (program_id, version, reason, snapshot, snapshot_hash, created_by)
            VALUES (:pid, :version, :reason, CAST(:snapshot AS jsonb), :hash, CAST(:created_by AS uuid))
            """
        ),
        {
            "pid": program_id,
            "version": version,
            "reason": reason,
            "snapshot": payload,
            "hash": digest,
            "created_by": created_by,
        },
    )
    return version


async def list_versions(session: AsyncSession, program_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """
                SELECT version, reason, created_at, created_by
                FROM program_version
                WHERE program_id = :pid
                ORDER BY version DESC
                LIMIT :limit
                """
            ),
            {"pid": program_id, "limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def get_version(session: AsyncSession, program_id: str, version: int) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT version, reason, snapshot, created_at, created_by
                FROM program_version
                WHERE program_id = :pid AND version = :version
                """
            ),
            {"pid": program_id, "version": version},
        )
    ).mappings().first()
    return dict(row) if row else None


async def audit(
    session: AsyncSession,
    *,
    org_id: str,
    action: str,
    actor_id: str | None = None,
    program_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO audit_log (org_id, actor_id, program_id, action, details)
            VALUES (:org_id, CAST(:actor_id AS uuid), CAST(:program_id AS uuid), :action, CAST(:details AS jsonb))
            """
        ),
        {
            "org_id": org_id,
            "actor_id": actor_id,
            "program_id": program_id,
            "action": action,
            "details": json.dumps(details or {}, ensure_ascii=False),
        },
    )


def new_uuid() -> str:
    return str(uuid.uuid4())
