"""Маркеры подтверждения источников в DOCX."""

from __future__ import annotations

from karkas.domain.kit import Content, KitV1, Source
from karkas.infra.exporters.docx_program import PARTIAL_VERIFY_MARK, UNVERIFIED_MARK, _source_payload
from tests.conftest import build_minimal_kit


def test_verified_normative_no_unverified_mark() -> None:
    kit = build_minimal_kit()
    kit.content = Content(
        sources=[
            Source(
                ref="SRC-1",
                section="normative",
                citation="Приказ Минобрнауки России № 266",
                status="verified",
            )
        ]
    )
    payload = _source_payload(kit.content.sources[0], 1)
    assert UNVERIFIED_MARK not in payload["citation"]


def test_invented_book_gets_unverified_mark() -> None:
    src = Source(ref="SRC-2", section="main", citation="Несуществующая книга", status="unverified")
    payload = _source_payload(src, 1)
    assert UNVERIFIED_MARK in payload["citation"]


def test_isbn_partial_mark() -> None:
    src = Source(ref="SRC-3", section="main", citation="Учебник", status="partially_verified")
    payload = _source_payload(src, 1)
    assert PARTIAL_VERIFY_MARK in payload["citation"]
    assert UNVERIFIED_MARK not in payload["citation"]
