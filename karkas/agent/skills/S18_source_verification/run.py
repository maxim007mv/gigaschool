"""S18 · Детерминированная верификация источников (Д4 §5.7)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from karkas.agent.skills._base import SkillContext, SkillSpec, registry_bundle, today_from_inputs
from karkas.domain.source_domains import url_on_allowlist
from karkas.domain.validators import NormativeAct, RegistryBundle, ServiceRecord

DIR = "S18_source_verification"
METADATA = SkillSpec(code="S18", name="Верификация источников", dir=DIR, depends_on=("S17",))

STATUSES: tuple[str, ...] = ("verified", "partially_verified", "unverified", "not_found", "outdated")

_PLACEHOLDER_AUTHOR_RE = re.compile(
    r"\b(иванов\s+и\.?\s*и\.?|петров\s+п\.?\s*п\.?)\b",
    re.IGNORECASE,
)
# ISBN из примеров промптов (S17 и ранних версий): модель копирует их в реальные списки.
_PROMPT_EXAMPLE_ISBNS: frozenset[str] = frozenset({"9785446112340", "9785091123456"})


def _isbn_digits(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit() or ch in "Xx")


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
    return bool(act.valid_from is not None and today < act.valid_from)


def _find_service(source: dict[str, Any], bundle: RegistryBundle | None) -> ServiceRecord | None:
    if bundle is None:
        return None
    citation = str(source.get("citation") or "").casefold()
    for service in bundle.services:
        name = str(service.name or "").strip().casefold()
        if name and name in citation:
            return service
    return None


def _citation_known_verified(citation: str) -> bool:
    from karkas.domain.verified_registry import load_file_verified

    cite = citation.strip().lower()
    if not cite:
        return False
    known = load_file_verified().source_citations
    return any(cite == row or row in cite or cite in row for row in known)


def verify_source(source: dict[str, Any], bundle: RegistryBundle | None, today: date) -> dict[str, Any]:
    """Статус одного источника + доказательство проверки (evidence)."""
    section = str(source.get("section") or "main")
    status = "unverified"
    evidence: dict[str, Any] = dict(source.get("evidence") or {})
    citation = str(source.get("citation") or "")
    example_isbn = _isbn_digits(source.get("isbn")) in _PROMPT_EXAMPLE_ISBNS or any(
        isbn in _isbn_digits(citation) for isbn in _PROMPT_EXAMPLE_ISBNS
    )
    if section in ("main", "additional") and (_PLACEHOLDER_AUTHOR_RE.search(citation) or example_isbn):
        status = "unverified"
        evidence["reason"] = (
            "ISBN скопирован из примера промпта — требуется подтверждение по каталогу"
            if example_isbn
            else "типовой автор-заглушка — требуется подтверждение по каталогу"
        )
        result = dict(source)
        result["status"] = status
        result["evidence"] = evidence
        return result
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
        if _citation_known_verified(citation):
            status = "verified"
            evidence["reason"] = "издание в локальном проверенном каталоге"
        elif isbn_valid(value):
            status = "unverified"
            evidence["isbn_check"] = "ok"
            evidence["reason"] = (
                "контрольная сумма ISBN верна, но издание не подтверждено каталогом — помечено «не проверено»"
            )
        else:
            status = "not_found"
            evidence["isbn_check"] = "failed"
            evidence["reason"] = "контрольная цифра ISBN не сходится"
    elif section in ("main", "additional"):
        status = "unverified"
        evidence["reason"] = "ISBN не указан — подтверждение по каталогу невозможно"
    elif section == "internet":
        allowed, host = url_on_allowlist(str(source.get("url") or ""))
        evidence["http_checked"] = False
        if not source.get("url"):
            status = "unverified"
            evidence["reason"] = "URL не указан"
        elif allowed:
            status = "verified"
            evidence["domain_allowlisted"] = True
            evidence["host"] = host
            evidence["reason"] = "домен в белом списке (без сетевой проверки)"
        else:
            status = "not_found"
            evidence["host"] = host
            evidence["reason"] = "домен не в белом списке доверенных источников"
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
        if status not in summary:
            summary[status] = 0
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
        "checked_at": datetime.now(UTC).isoformat(),
    }
