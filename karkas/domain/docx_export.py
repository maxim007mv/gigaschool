"""Порт экспорта программы в .docx — реализация регистрируется из infra при старте."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from karkas.domain.kit import KitV1

_exporter: Callable[["KitV1"], bytes] | None = None


def register_program_docx_exporter(fn: Callable[["KitV1"], bytes]) -> None:
    global _exporter
    _exporter = fn


def export_program_docx(kit: "KitV1") -> bytes:
    if _exporter is None:
        raise RuntimeError(
            "Экспорт .docx не инициализирован: импортируйте karkas.infra.exporters.bootstrap при старте API/воркера"
        )
    return _exporter(kit)
