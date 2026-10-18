"""karkas.infra.exporters — сериализаторы выгрузок: GIFT, Moodle XML, CSV, .docx, .pptx, KitV1 JSON.

``ARTIFACT_KINDS`` — соответствие видов артефактов (POST /exports) функциям выгрузки.
"""

from __future__ import annotations

from typing import Callable

from karkas.infra.exporters.csv_tests import export_tests_csv
from karkas.infra.exporters.docx_program import export_docx_program
from karkas.infra.exporters.docx_report import export_docx_report
from karkas.infra.exporters.gift import export_gift
from karkas.infra.exporters.kit_json import export_kit_json, kit_json_schema
from karkas.infra.exporters.moodle_xml import export_moodle_xml
from karkas.infra.exporters.pptx_slides import export_pptx_slides

ExportFunction = Callable[..., str | bytes]

ARTIFACT_KINDS: dict[str, ExportFunction] = {
    "docx": export_docx_program,
    "pptx": export_pptx_slides,
    "gift": export_gift,
    "moodle_xml": export_moodle_xml,
    "csv": export_tests_csv,
    "json": export_kit_json,
    "report": export_docx_report,
}

__all__ = [
    "ARTIFACT_KINDS",
    "ExportFunction",
    "export_docx_program",
    "export_docx_report",
    "export_gift",
    "export_kit_json",
    "export_moodle_xml",
    "export_pptx_slides",
    "export_tests_csv",
    "kit_json_schema",
]
