"""Локальный verified.json: анти-галлюцинации кодов и источников."""

from __future__ import annotations

from karkas.domain.kit import Competency, LaborFunctionRef, ProfStandardRef, Source
from karkas.domain.verified_registry import (
    NEEDS_REVIEW,
    annotate_registries_dict,
    apply_source_verification_flags,
    load_file_verified,
    verification_assumptions_for_competencies,
)


def test_file_registry_contains_demo_codes() -> None:
    reg = load_file_verified()
    assert reg.prof_ok("06.015")
    assert reg.lf_ok("06.015", "C/14.6")


def test_unverified_prof_standard_flagged() -> None:
    comp = Competency(
        ref="C1",
        title="Тест",
        prof_standard=ProfStandardRef(code="99.999", title="Выдуманный"),
        labor_functions=[],
        outcomes=[],
    )
    notes = verification_assumptions_for_competencies([comp])
    assert any(NEEDS_REVIEW in note for note in notes)


def test_annotate_registries_marks_file_verified() -> None:
    raw = annotate_registries_dict(
        {
            "prof_standards": [{"code": "06.015", "title": "ИС", "status": "active"}],
            "labor_functions": [],
        }
    )
    assert raw["prof_standards"][0]["file_verified"] is True


def test_source_not_in_file_becomes_unverified() -> None:
    sources = apply_source_verification_flags(
        [Source(ref="SRC-01", section="internet", citation="Несуществующая книга 2026", status="verified")]
    )
    assert sources[0].status == "unverified"
