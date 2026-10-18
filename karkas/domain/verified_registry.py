"""Локальный файл проверенных кодов (data/registries/verified.json).

Коды профстандартов и ТФ, не попавшие в файл, помечаются для методиста как
«требует проверки»; в промпты агента попадают только записи из файла + БД с
флагом file_verified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from karkas.domain.kit import Competency, LaborFunctionRef, ProfStandardRef, Source

VERIFIED_JSON = Path(__file__).resolve().parents[2] / "data" / "registries" / "verified.json"
NEEDS_REVIEW = "требует проверки"


@dataclass(frozen=True, slots=True)
class FileVerifiedRegistry:
    prof_standard_codes: frozenset[str]
    labor_functions: frozenset[tuple[str, str]]
    normative_numbers: frozenset[str]
    source_citations: frozenset[str]

    def prof_ok(self, code: str) -> bool:
        return code.strip() in self.prof_standard_codes

    def lf_ok(self, prof_code: str, lf_code: str) -> bool:
        return (prof_code.strip(), lf_code.strip()) in self.labor_functions


@lru_cache(maxsize=1)
def load_file_verified() -> FileVerifiedRegistry:
    if not VERIFIED_JSON.is_file():
        return FileVerifiedRegistry(
            prof_standard_codes=frozenset(),
            labor_functions=frozenset(),
            normative_numbers=frozenset(),
            source_citations=frozenset(),
        )
    try:
        raw = json.loads(VERIFIED_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return FileVerifiedRegistry(
            prof_standard_codes=frozenset(),
            labor_functions=frozenset(),
            normative_numbers=frozenset(),
            source_citations=frozenset(),
        )
    ps = frozenset(str(item["code"]).strip() for item in raw.get("prof_standards") or [] if item.get("code"))
    lf = frozenset(
        (str(item["prof_standard_code"]).strip(), str(item["code"]).strip())
        for item in raw.get("labor_functions") or []
        if item.get("prof_standard_code") and item.get("code")
    )
    acts = frozenset(str(item["number"]).strip() for item in raw.get("normative_acts") or [] if item.get("number"))
    cites = frozenset(
        str(item["citation"]).strip().lower()
        for item in raw.get("sources") or []
        if item.get("citation")
    )
    return FileVerifiedRegistry(
        prof_standard_codes=ps,
        labor_functions=lf,
        normative_numbers=acts,
        source_citations=cites,
    )


def merge_file_prof_standards(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Дополнить список кандидатов записями из файла, если их нет в БД."""
    verified = load_file_verified()
    by_code = {str(row.get("code") or "").strip(): row for row in existing if row.get("code")}
    raw = json.loads(VERIFIED_JSON.read_text(encoding="utf-8"))
    for item in raw.get("prof_standards") or []:
        code = str(item.get("code") or "").strip()
        if not code or code in by_code:
            continue
        by_code[code] = {
            "code": code,
            "title": item.get("title") or "",
            "status": item.get("status") or "active",
            "labor_functions": [
                lf
                for lf in raw.get("labor_functions") or []
                if str(lf.get("prof_standard_code") or "").strip() == code
            ],
        }
    return [annotate_prof_candidate(row, verified) for row in by_code.values()]


def annotate_prof_candidate(row: dict[str, Any], verified: FileVerifiedRegistry | None = None) -> dict[str, Any]:
    verified = verified or load_file_verified()
    code = str(row.get("code") or "").strip()
    out = dict(row)
    out["file_verified"] = verified.prof_ok(code)
    lfs = []
    for lf in row.get("labor_functions") or []:
        if not isinstance(lf, dict):
            continue
        lf_code = str(lf.get("code") or "").strip()
        item = dict(lf)
        item["file_verified"] = verified.lf_ok(code, lf_code)
        lfs.append(item)
    out["labor_functions"] = lfs
    return out


def annotate_registries_dict(registries: dict[str, Any]) -> dict[str, Any]:
    """Пометить кандидатов реестра флагом file_verified (для S05/S06)."""
    verified = load_file_verified()
    out = dict(registries)
    out["prof_standards"] = [
        annotate_prof_candidate(row, verified) if isinstance(row, dict) else row
        for row in registries.get("prof_standards") or []
    ]
    out["labor_functions"] = [
        {
            **row,
            "file_verified": verified.lf_ok(
                str(row.get("prof_standard_code") or ""),
                str(row.get("code") or ""),
            ),
        }
        if isinstance(row, dict)
        else row
        for row in registries.get("labor_functions") or []
    ]
    out["verified_registry_path"] = str(VERIFIED_JSON)
    return out


def verification_assumptions_for_competencies(competencies: list[Competency]) -> list[str]:
    """Сообщения методисту по кодам вне локального verified-файла."""
    verified = load_file_verified()
    notes: list[str] = []
    for comp in competencies:
        ps = comp.prof_standard
        if ps is not None and not verified.prof_ok(ps.code):
            notes.append(f"Профстандарт {ps.code} — {NEEDS_REVIEW}")
        for lf in comp.labor_functions:
            ps_code = ps.code if ps else ""
            if ps_code and not verified.lf_ok(ps_code, lf.code):
                notes.append(f"Трудовая функция {lf.code} (профстандарт {ps_code}) — {NEEDS_REVIEW}")
    return notes


def _registry_backed_verified(src: Source) -> bool:
    """S18 подтвердил источник по реестру БД (НПА / ПО / домен)."""
    if src.section == "normative" and src.status == "verified":
        return bool((src.evidence or {}).get("matched"))
    if src.section == "software" and src.status == "verified":
        return True
    if src.section == "internet" and src.status == "verified":
        return bool((src.evidence or {}).get("domain_allowlisted"))
    return False


def apply_source_verification_flags(sources: list[Source]) -> list[Source]:
    """Дополнительные пометки из verified.json: только повышение доверия, без понижения S18.

    Нельзя перезаписывать verified НПА/ПО из реестра БД из-за пустого списка citations в файле.
    """
    verified = load_file_verified()
    updated: list[Source] = []
    for src in sources:
        if _registry_backed_verified(src) or src.status in ("partially_verified", "not_found", "outdated"):
            updated.append(src)
            continue
        cite = (src.citation or "").strip().lower()
        if cite and verified.source_citations:
            if any(cite == known or known in cite or cite in known for known in verified.source_citations):
                if src.status == "unverified":
                    updated.append(src.model_copy(update={"status": "verified"}))
                    continue
        updated.append(src)
    return updated


def merge_registry_bundle_prof_standards(
    db_standards: list[Any],
    *,
    file_first: bool = True,
) -> list[Any]:
    """Объединить ProfStandard из БД с файлом (для build_registries)."""
    from karkas.domain.validators import ProfStandard

    verified = load_file_verified()
    raw = json.loads(VERIFIED_JSON.read_text(encoding="utf-8"))
    by_code: dict[str, ProfStandard] = {p.code: p for p in db_standards}
    for item in raw.get("prof_standards") or []:
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        if code not in by_code or file_first:
            by_code[code] = ProfStandard(
                code=code,
                title=str(item.get("title") or by_code.get(code, ProfStandard(code=code, title="")).title),
                status=str(item.get("status") or "active"),
            )
    # Порядок: сначала verified файл, затем остальные из БД
    ordered: list[ProfStandard] = []
    for code in sorted(verified.prof_standard_codes):
        if code in by_code:
            ordered.append(by_code.pop(code))
    ordered.extend(sorted(by_code.values(), key=lambda p: p.code))
    return ordered
