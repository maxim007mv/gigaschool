"""Регистрация адаптеров infra в доменных портах."""

from __future__ import annotations

from karkas.domain.docx_export import register_program_docx_exporter
from karkas.infra.exporters.docx_program import export_docx_program

register_program_docx_exporter(export_docx_program)
