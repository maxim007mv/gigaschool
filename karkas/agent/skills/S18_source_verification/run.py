"""S18 · Детерминированная верификация источников (Д4 §5.7)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from karkas.agent.skills._base import SkillContext, SkillSpec, registry_bundle, today_from_inputs
from karkas.domain.validators import NormativeAct, RegistryBundle, ServiceRecord

DIR = "S18_source_verification"
METADATA = SkillSpec(code="S18", name="Верификация источников", dir=DIR, depends_on=("S17",))

STATUSES: tuple[str, ...] = ("verified", "unverified", "not_found", "outdated")


def isbn13_valid(value: str) -> bool:
    """Контрольная цифра ISBN-13 (вес 1/3 по позиции)."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 13:
        return False
    total = sum((1 if index % 2 == 0 else 3) * int(ch) for index, ch in enumerate(digits))
    return total % 10 == 0


def isbn10_valid(value: str) -> bool:
    """Контрольная цифра ISBN-10 (последний знак — цифра или X)."""
    digits = "".join(ch for ch in value.upper() if ch.isdigit() or ch == "X")
    if len(digits) != 10:
        return False
    total = 0
    for index, ch in enumerate(digits):
        if ch == "X":
            if index != 9:
                return False
            weight = 10
        else:
            weight = int(ch)
        total += (10 - index) * weight
    return total % 11 == 0


def isbn_valid(value: str) -> bool:
    """Любой из форматов ISBN; пробелы и дефисы игнорируются."""
    text = (value or "").strip()
    return isbn13_valid(text) or isbn10_valid(text)


def _find_act(source: dict[str, Any], bundle: RegistryBundle | None) -> NormativeAct | None:
    if bundle is None:
        return None
    ref = str(source.get("normative_act_ref") or "").strip().casefold()
    citation = str(source.get("citation") or "").casefold()
    for act in bundle.normative_acts:
        number = str(act.number or "").strip().casefold()
        issuer = str(act.issuer or "").strip().casefold()
        variants = {number, f"{issuer} {number}", f"{issuer} № {number}"}
        if ref and ref in variants:
            return act
    if citation:
        for act in bundle.normative_acts:
            number = str(act.number or "").strip().casefold()
            if number and number in citation:
                return act
    return None


def _is_outdated(act: NormativeAct, today: date) -> bool:
    if act.replaced_by_number:
        return True
    if act.valid_to is not None and today > act.valid_to:
        return True
    if act.valid_from is not None and today < act.valid_from:
        return True
    return False


def _find_service(source: dict[str, Any], bundle: RegistryBundle | None) -> ServiceRecord | None:
    if bundle is None:
        return None
    citation = str(source.get("citation") or "").casefold()
    for service in bundle.services:
        name = str(service.name or "").strip().casefold()
        if name and name in citation:
            return service
    return None


def verify_source(source: dict[str, Any], bundle: RegistryBundle | None, today: date) -> dict[str, Any]:
    """Статус одного источника + доказательство проверки (evidence)."""
    section = str(source.get("section") or "main")
    status = "unverified"
    evidence: dict[str, Any] = dict(source.get("evidence") or {})
    if section == "normative":
        act = _find_act(source, bundle)
        if act is None:
            status = "not_found"
            evidence["reason"] = "НПА не найден в реестре — код не выводится (V-SRC-01)"
        elif _is_outdated(act, today):
            status = "outdated"
            evidence["reason"] = "акт не действует на дату программы"
            if act.replaced_by_number:
                evidence["replaced_by"] = act.replaced_by_number
        else:
            status = "verified"
            evidence["matched"] = f"{act.issuer} № {act.number}".strip()
    elif section in ("main", "additional") and source.get("isbn"):
        value = str(source["isbn"])
        if isbn_valid(value):
            status = "unverified"
            evidence["isbn_check"] = "ok"
            evidence["reason"] = "ISBN корректен; подтверждение по каталогу библиотек недоступно"
        else:
            status = "not_found"
            evidence["isbn_check"] = "failed"
            evidence["reason"] = "контрольная цифра ISBN не сходится"
    elif section in ("main", "additional"):
        status = "unverified"
        evidence["reason"] = "ISBN не указан — подтверждение по каталогу невозможно"
    elif section == "internet":
        status = "unverified"
        evidence["http_checked"] = False
        evidence["reason"] = "HTTP-проверка отключена в этом шаге (заглушка allowlist)"
    elif section == "software":
        service = _find_service(source, bundle)
        if service is None:
            status = "unverified"
            evidence["reason"] = "сервис не найден в каталоге service_catalog"
        elif getattr(service, "available_ru", True) is False:
            status = "not_found"
            evidence["reason"] = "сервис недоступен в РФ (V-SVC-01)"
        elif getattr(service, "lifecycle", "current") != "current":
            status = "outdated"
            evidence["reason"] = "жизненный цикл сервиса завершён — заменить"
        else:
            status = "verified"
    result = dict(source)
    result["status"] = status
    result["evidence"] = evidence
    return result


def verify_sources(
    sources: list[dict[str, Any]], bundle: RegistryBundle | None, today: date
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Проверить все источники и посчитать сводку по статусам."""
    updated = [verify_source(dict(source), bundle, today) for source in sources]
    summary = {status: 0 for status in STATUSES}
    for source in updated:
        status = str(source.get("status") or "unverified")
        summary[status] = summary.get(status, 0) + 1
    return updated, summary


def today_from(inputs: dict[str, Any]) -> date:
    """Дата проверки: ISO-строка из входа или текущая дата."""
    return today_from_inputs(inputs)


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Присвоить источникам статусы verified/unverified/not_found/outdated."""
    s17 = inputs.get("S17") if isinstance(inputs.get("S17"), dict) else {}
    sources = inputs.get("sources") or s17.get("sources") or []
    if not sources:
        raise ValueError("S18: нет источников для верификации")
    bundle = registry_bundle(inputs.get("registries") or ctx.extra.get("registries"))
    updated, summary = verify_sources([dict(source) for source in sources], bundle, today_from(inputs))
    return {
        "sources": updated,
        "summary": summary,
        "unconfirmed": [str(source.get("ref")) for source in updated if source.get("status") != "verified"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
