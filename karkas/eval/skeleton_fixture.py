"""Пункты чек-листа, неприменимые к skeleton-фикстурам data/eval/*.json."""

from __future__ import annotations

# Содержательные артефакты (слайды, тесты, журнал уточнений) в JSON-каркасах не хранятся.
SKELETON_NA_BY_CASE: dict[str, frozenset[str]] = {
    "tk1": frozenset({"TK1-6", "TK1-7", "TK1-8"}),
    "tk2": frozenset({"TK2-6"}),
    "tk3": frozenset({"TK3-2", "TK3-4", "TK3-6", "TK3-7", "TK3-8", "TK3-9"}),
    "tk4": frozenset({"TK4-1", "TK4-2", "TK4-3", "TK4-4", "TK4-6", "TK4-8", "TK4-9", "TK4-10"}),
    "tk5": frozenset({"TK5-7"}),
}


def apply_skeleton_na(results: list, case_key: str) -> list:
    """Пометить content-dependent пункты как N/A (passed) для skeleton fixture."""
    from karkas.eval.checklists import CheckResult

    na = SKELETON_NA_BY_CASE.get(case_key.lower().strip(), frozenset())
    if not na:
        return results
    out: list[CheckResult] = []
    for row in results:
        if row.item_id in na:
            out.append(
                CheckResult(
                    row.case_id,
                    row.item_id,
                    True,
                    f"не применимо (skeleton fixture): {row.detail}",
                )
            )
        else:
            out.append(row)
    return out
