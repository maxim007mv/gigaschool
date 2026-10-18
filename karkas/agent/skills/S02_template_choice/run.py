"""S02 · Выбор шаблона: правила таблицы 4.2 + LLM-арбитр (Д4 §5.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S02_template_choice"
METADATA = SkillSpec(code="S02", name="Выбор шаблона", dir=DIR, model_class="struct", depends_on=("S01",))

CONFIDENCE_THRESHOLD = 0.8

QUESTION = "Уточните тип программы: повышение квалификации (ДПП ПК) или общеразвивающая (ДОП)?"

_DPP_PK_STRONG: tuple[str, ...] = (
    "повышение квалификации",
    "повышения квалификации",
    "профессиональная переподготовка",
    "профессиональной переподготовк",
    "стажировка",
    "удостоверение",
    "работник",
    "специалист",
    "учител",
    "преподавател",
    "педагог",
    "госслужащ",
    "служащ",
)
_DOP_STRONG: tuple[str, ...] = (
    "общеразвивающ",
    "школьник",
    "детей",
    "дети",
    "детск",
    "подростк",
    "кружк",
    "лагер",
    "профориентац",
)
_DPP_PK_MEDIUM: tuple[str, ...] = ("профстандарт", "трудовые функции", "квалификационные требования")
_DOP_MEDIUM: tuple[str, ...] = ("студент", "студенты")


@dataclass
class RuleDecision:
    """Вердикт правил: вид, уверенность, основания и признак «нужен вопрос»."""

    kind: str | None
    confidence: float
    reasons: list[str] = field(default_factory=list)
    conflict: bool = False
    need_question: bool = False

    @property
    def signals(self) -> int:
        return len(self.reasons)


def _hits(text: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker in text]


def classify(text: str, attached_templates: list[str]) -> RuleDecision:
    """Оценка вида программы по таблице 4.2 (детерминированно)."""
    lowered = text.lower().replace("ё", "е")
    pk_strong = _hits(lowered, _DPP_PK_STRONG)
    dop_strong = _hits(lowered, _DOP_STRONG)
    if re.search(r"\bдпп\b", lowered):
        pk_strong.append("ДПП")
    if re.search(r"\bдоп\b", lowered):
        dop_strong.append("ДОП")
    for name in attached_templates:
        template = name.lower().replace("ё", "е")
        if "дпп" in template or "dpp" in template or re.search(r"\bпк\b", template):
            return RuleDecision("dpp_pk", 0.95, [f"приложен шаблон ДПП ПК: {name}"])
        if "доп" in template or "dop" in template or "общеразв" in template:
            return RuleDecision("dop", 0.95, [f"приложен шаблон ДОП: {name}"])
    if pk_strong and dop_strong:
        return RuleDecision(
            None,
            0.5,
            [f"конфликт сильных признаков: {', '.join(pk_strong)} ↔ {', '.join(dop_strong)}"],
            conflict=True,
        )
    if pk_strong:
        confidence = min(0.98, 0.9 + 0.02 * (len(pk_strong) - 1))
        return RuleDecision("dpp_pk", confidence, [f"признак ДПП ПК: «{m}»" for m in pk_strong])
    if dop_strong:
        confidence = min(0.98, 0.9 + 0.02 * (len(dop_strong) - 1))
        return RuleDecision("dop", confidence, [f"признак ДОП: «{m}»" for m in dop_strong])
    pk_medium = _hits(lowered, _DPP_PK_MEDIUM)
    if pk_medium:
        return RuleDecision("dpp_pk", 0.7, [f"слабый признак ДПП ПК: «{m}»" for m in pk_medium])
    if _hits(lowered, _DOP_MEDIUM):
        return RuleDecision(
            None,
            0.4,
            ["студенты СПО/вуза без явного вида программы — нужно уточнение"],
            need_question=True,
        )
    return RuleDecision(
        None,
        0.2,
        ["признаков вида программы в брифе нет"],
        need_question=True,
    )


class ArbiterOut(BaseModel):
    kind: Literal["dpp_pk", "dop"]
    confidence: float = 0.6
    rationale: str = ""


def _result(
    kind: str | None,
    confidence: float,
    source: str,
    reasons: list[str],
    question: str | None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "source": source,
        "reasons": reasons,
        "question": question,
    }


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Выбрать вид программы: правила, при неоднозначности — арбитр, иначе — вопрос."""
    brief = str(inputs.get("brief") or "").strip()
    s01 = inputs.get("S01") if isinstance(inputs.get("S01"), dict) else {}
    profile = inputs.get("profile") if isinstance(inputs.get("profile"), dict) else {}
    if not profile:
        profile = s01.get("profile") if isinstance(s01.get("profile"), dict) else {}
    signs = [str(sign) for sign in (inputs.get("signs") or s01.get("template_signs") or []) if str(sign).strip()]
    text = " ".join(
        [
            brief,
            str(profile.get("audience") or ""),
            str(profile.get("entry_level") or ""),
            str(profile.get("notes") or ""),
            *signs,
        ]
    )
    attached = [str(name) for name in (inputs.get("attached_templates") or []) if str(name).strip()]
    decision = classify(text, attached)

    if decision.kind and decision.confidence >= CONFIDENCE_THRESHOLD:
        return _result(decision.kind, decision.confidence, "rules", decision.reasons, None)
    if decision.need_question or not decision.reasons:
        return _result(None, decision.confidence, "question", decision.reasons, QUESTION)

    arbiter = cast(
        ArbiterOut,
        await complete_structured(
            ctx,
            METADATA,
            ArbiterOut,
            brief=brief or text,
            profile_json=to_json(profile),
            rule_signals=to_json(decision.reasons),
        ),
    )
    if arbiter.kind not in ("dpp_pk", "dop"):
        return _result(None, 0.3, "question", decision.reasons, QUESTION)
    reasons = list(decision.reasons)
    if arbiter.rationale.strip():
        reasons.append(f"арбитр: {arbiter.rationale.strip()}")
    return _result(arbiter.kind, max(0.6, arbiter.confidence), "llm", reasons, None)
