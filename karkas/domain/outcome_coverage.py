"""Детерминированное покрытие РО темами (V-COV-01, S07)."""

from __future__ import annotations

import re
from typing import Any

_LO_MODULE_RE = re.compile(r"^LO(\d+)", re.IGNORECASE)


def _topic_score(module: dict[str, Any], topic: dict[str, Any], lo_ref: str) -> float:
    score = float(topic.get("practicality") or 0.5)
    if topic.get("has_lab"):
        score += 0.25
    mod_num = module.get("number")
    match = _LO_MODULE_RE.match(lo_ref.strip())
    if match and mod_num is not None and int(match.group(1)) == int(mod_num):
        score += 1.0
    return score


def link_uncovered_outcomes(
    modules: list[dict[str, Any]],
    known: set[str],
    gaps: list[str],
) -> None:
    """Привязать каждый нераскрытый РО к наиболее практичной теме (детерминированно)."""
    if not known or not modules:
        return
    covered: set[str] = set()
    for module in modules:
        for topic in module.get("topics") or []:
            covered.update(topic.get("outcome_refs") or [])
    missing = sorted(known - covered)
    if not missing:
        return
    has_topics = any(module.get("topics") for module in modules)
    if not has_topics:
        gaps.append("Нет тем для привязки нераскрытых РО (V-COV-01)")
        return
    for lo_ref in missing:
        best_score = -1.0
        best_topic: dict[str, Any] | None = None
        for module in modules:
            for topic in module.get("topics") or []:
                score = _topic_score(module, topic, lo_ref)
                if score > best_score:
                    best_score = score
                    best_topic = topic
        if best_topic is None:
            continue
        refs = list(best_topic.get("outcome_refs") or [])
        if lo_ref not in refs:
            refs.append(lo_ref)
            best_topic["outcome_refs"] = refs
            gaps.append(
                f"{lo_ref}: детерминированно привязан к практической теме {best_topic.get('ref', '?')} (V-COV-01)"
            )
