"""S20 · Экспорт комплекта: docx, pptx, GIFT, Moodle XML, CSV, JSON, отчёт (Д4 §5.12)."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from karkas.agent.skills._base import SkillContext, SkillSpec, kit_from_inputs
from karkas.domain.kit import KitV1, Report
from karkas.infra import exporters
from karkas.infra.exporters import (
    export_docx_program,
    export_docx_report,
    export_gift,
    export_kit_json,
    export_moodle_xml,
    export_pptx_slides,
    export_tests_csv,
)

DIR = "S20_export"
METADATA = SkillSpec(code="S20", name="Экспорт", dir=DIR, depends_on=("S19",))

FORMATS: tuple[str, ...] = ("docx", "pptx", "gift", "moodle_xml", "csv", "json", "report")


def default_kinds() -> dict[str, Callable[..., Any]]:
    """Артефакт → экспортёр: ARTIFACT_KINDS из infra, иначе замороженные имена export_*."""
    registry = getattr(exporters, "ARTIFACT_KINDS", None)
    if isinstance(registry, dict) and registry:
        return dict(registry)
    return {
        "docx": export_docx_program,
        "pptx": export_pptx_slides,
        "gift": export_gift,
        "moodle_xml": export_moodle_xml,
        "csv": export_tests_csv,
        "json": export_kit_json,
        "report": export_docx_report,
    }


def call_exporter(
    func: Callable[..., Any],
    kit: KitV1,
    *,
    module_refs: list[str] | None,
    report: Report | None,
) -> Any:
    """Вызвать экспортёр с теми параметрами, которые он объявляет (ArtifactKinds-совместимо)."""
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return func(kit)
    extra: dict[str, Any] = {}
    if "module_refs" in parameters:
        extra["module_refs"] = module_refs
    if "report" in parameters:
        extra["report"] = report
    return func(kit, **extra)


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Сформировать артефакты выгрузки в память (файлы не пишутся)."""
    kit = kit_from_inputs(inputs, ctx, "S20")
    kinds = default_kinds()
    requested = inputs.get("formats")
    if requested is None:
        formats = [name for name in FORMATS if name in kinds]
    elif isinstance(requested, (list, tuple)):
        formats = [str(name) for name in requested]
    else:
        raise ValueError("S20: formats должен быть списком")
    unknown = [name for name in formats if name not in FORMATS]
    if unknown:
        raise ValueError(f"S20: неизвестные форматы: {', '.join(unknown)}")
    report_source = inputs.get("report")
    if report_source is None:
        s19 = inputs.get("S19") if isinstance(inputs.get("S19"), dict) else {}
        report_source = s19.get("report")
    report = Report.model_validate(report_source) if isinstance(report_source, dict) else report_source
    module_refs_raw = inputs.get("module_refs")
    module_refs = [str(ref) for ref in module_refs_raw] if isinstance(module_refs_raw, list) else None

    artifacts: dict[str, Any] = {}
    for name in formats:
        exporter = kinds.get(name)
        if exporter is None:
            raise ValueError(f"S20: экспортёр для формата {name!r} недоступен")
        artifacts[name] = call_exporter(exporter, kit, module_refs=module_refs, report=report)
        if artifacts[name] is None:
            raise ValueError(f"S20: экспортёр {name!r} вернул пустой результат")
    return artifacts
