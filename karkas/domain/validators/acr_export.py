"""V-ACR-01: структура выгружаемого .docx совпадает с эталоном АЦР."""

from __future__ import annotations

from typing import TYPE_CHECKING

from karkas.domain.acr_reference import expected_acr_headings
from karkas.domain.acr_docx_text import docx_plain_text, missing_acr_headings
from karkas.domain.docx_export import export_program_docx
from karkas.domain.validators.base import GroupResult, issue, resolve_stage

if TYPE_CHECKING:
    from karkas.domain.validators import ValidationContext


def validate(ctx: ValidationContext) -> GroupResult:
    """V-ACR-01: только на стадии полного комплекта (есть содержание)."""
    if resolve_stage(ctx) != "kit":
        return GroupResult(skipped=["V-ACR-01"], meta={"stage": resolve_stage(ctx)})
    return validate_acr_export(ctx)


def validate_acr_export(ctx: ValidationContext) -> GroupResult:
    kit = ctx.kit
    try:
        blob = export_program_docx(kit)
    except Exception as exc:  # noqa: BLE001 — отчёт методисту, не падение API
        return GroupResult(
            issues=[
                issue(
                    "V-ACR-01",
                    "error",
                    f"Не удалось собрать .docx для сверки с АЦР: {exc}",
                    entity_ref="acr_export",
                )
            ],
            meta={"kind": kit.program.kind, "form": kit.program.form},
        )
    try:
        text = docx_plain_text(blob)
    except Exception as exc:  # noqa: BLE001
        return GroupResult(
            issues=[
                issue(
                    "V-ACR-01",
                    "error",
                    f"не удалось разобрать .docx: {exc}",
                    entity_ref="acr_export",
                )
            ],
            meta={"kind": kit.program.kind, "form": kit.program.form},
        )
    missing = missing_acr_headings(text, kit.program.kind, kit.program.form)
    issues = []
    if missing:
        issues.append(
            issue(
                "V-ACR-01",
                "error",
                "В .docx нет разделов эталона АЦР: " + "; ".join(missing[:8])
                + ("…" if len(missing) > 8 else ""),
                entity_ref="acr_export",
                fix_hint={"missing_headings": missing},
            )
        )
    if kit.program.kind == "dop":
        ref_file = "acr_dop_intensive_ai_24h.txt"
    elif kit.program.form == "internship":
        ref_file = "acr_dpp_pk_staj_bsa_248h.txt"
    else:
        ref_file = "dpp_pk_template.yaml"
    return GroupResult(
        issues=issues,
        meta={
            "expected_sections": len(expected_acr_headings(kit.program.kind, kit.program.form)),
            "missing_count": len(missing),
            "reference": "data/templates/" + ref_file,
            "ok": len(missing) == 0,
        },
    )
