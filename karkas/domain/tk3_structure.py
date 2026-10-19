"""Детерминированные правки структуры ТК-3 (72 ч, Python-аналитика) после S07."""

from __future__ import annotations

import re
from typing import Any


def _is_tk3_profile(brief: str, total_hours: int) -> bool:
    blob = brief.casefold()
    return total_hours == 72 and ("python" in blob or "pandas" in blob or "банк" in blob)


def apply_tk3_structure(
    modules: list[dict[str, Any]],
    gaps: list[str],
    *,
    brief: str,
    total_hours: int,
) -> list[dict[str, Any]]:
    """Отдельная тема статистики; не совмещать pandas и визуализацию в одном названии."""
    if not _is_tk3_profile(brief, total_hours):
        return modules
    topics = [t for m in modules for t in m.get("topics") or []]
    titles = " ".join(str(t.get("title") or "") for t in topics).casefold()
    has_stats = bool(re.search(r"статистик", titles))
    for topic in topics:
        title = str(topic.get("title") or "")
        lower = title.casefold()
        if "pandas" in lower and re.search(r"визуал", lower):
            topic["title"] = "Анализ данных в pandas"
            gaps.append(f"{topic.get('ref', '?')}: pandas и визуализация разделены (ТК-3)")
            if not any(re.search(r"визуал", str(t.get("title") or ""), re.I) for t in topics if t is not topic):
                last_mod = modules[-1]
                order = len(last_mod.get("topics") or []) + 1
                last_mod.setdefault("topics", []).append(
                    {
                        "ref": f"T{last_mod.get('number', len(modules))}.{order}",
                        "title": "Визуализация данных",
                        "summary": "Построение графиков для банковской аналитики",
                        "outcome_refs": list(topic.get("outcome_refs") or [])[:1],
                        "complexity": int(topic.get("complexity") or 2),
                        "practicality": 0.75,
                        "weight": 1.0,
                        "has_lab": True,
                    }
                )
                gaps.append("добавлена отдельная тема визуализации (ТК-3)")
    if not has_stats and not re.search(r"статистик", titles):
        host = modules[-1] if modules else None
        if host is not None:
            order = len(host.get("topics") or []) + 1
            host.setdefault("topics", []).append(
                {
                    "ref": f"T{host.get('number', len(modules))}.{order}",
                    "title": "Основы статистики для анализа данных",
                    "summary": "Описательная статистика и проверка гипотез на банковских выборках",
                    "outcome_refs": [ref for t in topics for ref in (t.get("outcome_refs") or [])][:1],
                    "complexity": 3,
                    "practicality": 0.7,
                    "weight": 1.0,
                    "has_lab": False,
                }
            )
            gaps.append("добавлена отдельная тема статистики (ТК-3)")
    return modules


def tk3_min_calendar_weeks(brief: str, total_hours: int, weeks: int) -> int:
    """72 ч / 4 недели в брифе → минимум 3 недели в календаре."""
    if not _is_tk3_profile(brief, total_hours):
        return weeks
    if re.search(r"4\s*недел", brief, re.I):
        return max(weeks, 3)
    return max(weeks, 3)
