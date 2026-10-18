"""karkas.api.routers.clarify — уточняющие вопросы (Д4 §6.3).

Не более 5 вопросов; ответ «на ваше усмотрение» записывается в допущения.
Пока обязательные слоты пусты — сборка каркаса запрещена (409 CLARIFICATION_REQUIRED).
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.api import schemas
from karkas.api.deps import CurrentPrincipal, enforce_rate_limit, require_roles
from karkas.api.errors import BadRequest, Forbidden, NotFound
from karkas.domain.intake_slots import validate_clarification_answer
from karkas.api.routers.programs import assert_access, get_program_or_404
from karkas.infra.db import get_session
from karkas.infra.repos import programs as programs_repo

router = APIRouter(
    prefix="/programs", tags=["clarify"], dependencies=[Depends(enforce_rate_limit)]
)

REQUIRED_SLOTS = ("kind", "total_hours", "audience", "entry_level", "form", "final_attestation")

# Значения по умолчанию для ответа «на ваше усмотрение» (Д4 §5.2).
DEFAULTS: dict[str, str] = {
    "kind": "Повышение квалификации",
    "total_hours": "72",
    "audience": "Взрослые слушатели",
    "entry_level": "Базовый уровень — определит агент",
    "form": "Очно-заочная",
    "final_attestation": "Итоговый тест",
    "schedule": "Не более 6 академических часов в день",
}


def _question_out(row: dict[str, Any]) -> schemas.QuestionOut:
    options = row.get("options") or []
    if isinstance(options, str):
        options = json.loads(options)
    why_map = {
        "kind": "От этого зависят шаблон и документ об обучении",
        "total_hours": "«Около месяца» не задаёт объём в часах",
        "audience": "От слушателей зависит язык, примеры и глубина материала",
        "entry_level": "Чтобы результаты были реалистичными",
        "form": "Очно, очно-заочно или дистанционно — влияет на часы и график",
        "final_attestation": "Как проверить результат в конце обучения",
        "schedule": "Сколько часов в день и сколько недель",
    }
    return schemas.QuestionOut(
        id=str(row["id"]),
        slot=row["slot"],
        ord=row["ord"],
        text=row["question"],
        why=why_map.get(row["slot"], ""),
        options=list(options),
        allow_default=True,
        allow_free_text=row["slot"] in ("total_hours", "audience", "entry_level"),
    )


@router.get("/{program_id}/questions", response_model=schemas.QuestionsOut)
async def get_questions(
    program_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.QuestionsOut:
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    rows = await programs_repo.get_questions(session, program_id)
    profile = program["profile"] or {}
    detected = {
        "kind": profile.get("kind"),
        "total_hours": profile.get("total_hours"),
        "audience": profile.get("audience"),
        "duration_hint": profile.get("duration_hint"),
    }
    return schemas.QuestionsOut(
        status=program["status"],
        detected=detected,
        questions=[_question_out(r) for r in rows],
    )


@router.post("/{program_id}/answers", response_model=schemas.AnswersOut, status_code=202)
async def submit_answers(
    program_id: str,
    payload: schemas.AnswersIn,
    principal: Annotated[CurrentPrincipal, Depends(require_roles("methodist", "admin"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> schemas.AnswersOut:
    """Ответы на вопросы: значение из вариантов или свободный текст ≤ 1000 символов."""
    program = await get_program_or_404(session, program_id, principal)
    assert_access(principal, program)
    if program["status"] not in ("draft", "clarifying"):
        raise Forbidden("Ответы принимаются только на этапе уточнений")

    questions = {str(q["id"]): q for q in await programs_repo.get_questions(session, program_id)}
    if not questions:
        raise NotFound("У программы нет вопросов")

    answers: dict[str, str | None] = {}
    use_default: set[str] = set()
    assumptions: list[str] = []
    for answer in payload.answers:
        if answer.id not in questions:
            raise NotFound(f"Вопрос {answer.id} не найден")
        slot = questions[answer.id]["slot"]
        if answer.use_default or answer.value is None:
            value = DEFAULTS.get(slot, "Значение по умолчанию")
            use_default.add(answer.id)
            assumptions.append(f"«{slot}»: принято значение по умолчанию — {value}")
            await programs_repo.record_slot_default(session, program_id=program_id, slot=slot, value=value)
        else:
            value = (answer.value or "")[:1000]
            err = validate_clarification_answer(slot, value)
            if err:
                raise BadRequest(err)
        answers[answer.id] = value

    await programs_repo.save_answers(
        session,
        program_id=program_id,
        answers=answers,
        use_default=use_default,
        answered_by=principal.user_id,
    )

    all_rows = await programs_repo.get_questions(session, program_id)
    required_answered = all(
        r["answer"] is not None for r in all_rows if r["slot"] in REQUIRED_SLOTS
    )
    ready = required_answered and all(r["answer"] is not None for r in all_rows)

    if ready and program["status"] == "clarifying":
        await programs_repo.set_status(session, program_id=program_id, status="draft")

    await programs_repo.audit(
        session,
        org_id=program["org_id"],
        action="clarification.answers",
        actor_id=principal.user_id,
        program_id=program_id,
        details={"answered": len(answers), "defaults": len(use_default)},
    )
    await session.commit()
    return schemas.AnswersOut(
        status="draft" if ready else program["status"],
        ready_for_framework=ready,
        assumptions=assumptions,
    )
