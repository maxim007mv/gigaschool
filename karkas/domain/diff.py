"""karkas.domain.diff — сравнение снимков KitV1 для экрана «Версии» (Д4 §6.2).

Возвращает изменённые/добавленные/удалённые элементы по стабильным ref.
"""

from __future__ import annotations

from typing import Any


def _collect(snapshot: dict[str, Any]) -> dict[str, str]:
    """Плоская карта ref → канонический JSON элемента (для сравнения)."""
    import json

    index: dict[str, str] = {}
    framework = snapshot.get("framework") or {}
    # Глобальные поля каркаса тоже сравниваются (правка цели/ИА должна быть видна
    # на экране версий, а не давать «изменений нет»).
    index["framework:goal"] = json.dumps(framework.get("goal") or "", ensure_ascii=False, sort_keys=True)
    index["framework:tasks"] = json.dumps(framework.get("tasks") or [], ensure_ascii=False, sort_keys=True)
    index["framework:final_attestation"] = json.dumps(
        framework.get("final_attestation") or {}, ensure_ascii=False, sort_keys=True
    )
    for comp in framework.get("competencies", []):
        index[f"competency:{comp['ref']}"] = json.dumps(comp, ensure_ascii=False, sort_keys=True)
    for module in framework.get("modules", []):
        index[f"module:{module['ref']}"] = json.dumps(module, ensure_ascii=False, sort_keys=True)
        for topic in module.get("topics", []):
            index[f"topic:{topic['ref']}"] = json.dumps(topic, ensure_ascii=False, sort_keys=True)
    content = snapshot.get("content") or {}
    for group in ("assessments", "sources", "module_programs", "lecture_plans", "slides", "sections"):
        for item in content.get(group, []):
            index[f"{group}:{item['ref']}"] = json.dumps(item, ensure_ascii=False, sort_keys=True)
    return index


def diff_snapshots(left: dict[str, Any], right: dict[str, Any]) -> dict[str, list[str]]:
    """Сравнение двух снимков KitV1.

    Возвращает {"changed": [...], "added": [...], "removed": [...]} — списки ref
    в порядке появления (changed — только реально отличающиеся элементы).
    """
    l_index = _collect(left)
    r_index = _collect(right)
    changed = sorted(key for key in l_index.keys() & r_index.keys() if l_index[key] != r_index[key])
    added = sorted(r_index.keys() - l_index.keys())
    removed = sorted(l_index.keys() - r_index.keys())
    strip = lambda keys: [k.split(":", 1)[1] if ":" in k else k for k in keys]  # noqa: E731
    return {"changed": strip(changed), "added": strip(added), "removed": strip(removed)}
