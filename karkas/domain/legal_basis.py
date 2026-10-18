"""Нормативная основа программы из реестра НПА и шаблона вида (ДОП / ДПП ПК)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from karkas.domain.kit import LegalBasis, VerifyStatus
from karkas.domain.validators.template import load_template


def _find_act(acts: Iterable[dict[str, Any]], number: str) -> dict[str, Any] | None:
    key = number.strip().casefold()
    for act in acts:
        if str(act.get("number") or "").strip().casefold() == key:
            return act
    return None


def _act_line(act: dict[str, Any]) -> str:
    issuer = str(act.get("issuer") or "").strip()
    number = str(act.get("number") or "").strip()
    signed = act.get("signed_on")
    date_part = f" от {signed}" if signed else ""
    title = str(act.get("title") or "").strip()
    if "фз" in number.casefold() or number.endswith("-ФЗ"):
        return f"Федеральный закон {number}{date_part} «{title}»"
    return f"{issuer} № {number}{date_part} «{title}»"


def _status_for_act(act: dict[str, Any], today: date) -> VerifyStatus:
    valid_to = act.get("valid_to")
    valid_from = act.get("valid_from")
    if valid_to:
        try:
            end = date.fromisoformat(str(valid_to)[:10])
            if today > end:
                return "outdated"
        except ValueError:
            pass
    if valid_from:
        try:
            start = date.fromisoformat(str(valid_from)[:10])
            if today < start:
                return "not_found"
        except ValueError:
            pass
    return "verified"


def build_program_legal_basis(
    kind: str,
    normative_acts: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> list[LegalBasis]:
    """Заполнить раздел 1.4: 273-ФЗ + приказ по шаблону (266 / 629)."""
    today = today or date.today()
    template = load_template(kind)
    basis_text = str(template.get("normative_basis") or "").strip()
    numbers: list[str] = ["273-ФЗ"]
    if kind == "dpp_pk":
        numbers.append("266")
    elif kind == "dop":
        numbers.append("629")
    items: list[LegalBasis] = []
    for index, number in enumerate(numbers, start=1):
        act = _find_act(normative_acts, number)
        if act is None:
            act_text = basis_text if number in ("266", "629") and basis_text else f"НПА № {number}"
            items.append(LegalBasis(ref=f"LB-{index}", act=act_text, status="not_found"))
            continue
        items.append(
            LegalBasis(
                ref=f"LB-{index}",
                act=_act_line(act),
                status=_status_for_act(act, today),
            )
        )
    return items
