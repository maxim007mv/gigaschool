"""kit_fixup: reference ТК-1 проходит ключевые проверки."""

from __future__ import annotations

import karkas.infra.exporters.bootstrap  # noqa: F401
from karkas.domain.kit_fixup import apply_kit_fixup
from karkas.domain.validators import ValidationContext, run_validation
from karkas.eval.checklists import run_checklist
from karkas.eval.official_cases import OFFICIAL_CASES
from karkas.eval.reference_kits import build_tk1_kit


def test_tk1_reference_checklist_after_fixup() -> None:
    kit = apply_kit_fixup(build_tk1_kit(), brief=OFFICIAL_CASES["tk1"].request_text)
    results = run_checklist(kit, "tk1")
    failed = {r.item_id for r in results if not r.passed}
    # Минимальная фикстура не содержит 10 тестовых вопросов; слайды занятий 1–2
    # fixup достраивает из темы и её РО. Остальные пункты должны проходить.
    assert failed == {"TK1-6"}


def test_tk1_self_check_errors_reduced() -> None:
    before = run_validation(ValidationContext(kit=build_tk1_kit(), stage="kit"))
    kit = apply_kit_fixup(build_tk1_kit(), brief=OFFICIAL_CASES["tk1"].request_text)
    after = run_validation(ValidationContext(kit=kit, stage="kit"))
    before_err = sum(1 for i in before.issues if i.severity == "error")
    after_err = sum(1 for i in after.issues if i.severity == "error")
    assert after_err < before_err
    assert after.summary.get("template", {}).get("ok") is True
