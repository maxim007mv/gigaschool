"""Нормативная основа программы из реестра."""

from __future__ import annotations

from karkas.domain.legal_basis import build_program_legal_basis


def test_dpp_pk_legal_basis_includes_266() -> None:
    acts = [
        {
            "issuer": "Российская Федерация",
            "number": "273-ФЗ",
            "signed_on": "2012-12-29",
            "title": "Об образовании",
        },
        {
            "issuer": "Минобрнауки России",
            "number": "266",
            "signed_on": "2025-03-24",
            "valid_from": "2025-09-01",
            "title": "Порядок ДПП",
        },
    ]
    basis = build_program_legal_basis("dpp_pk", acts)
    assert len(basis) == 2
    assert basis[0].status == "verified"
    assert "266" in basis[1].act
    assert basis[1].status == "verified"
