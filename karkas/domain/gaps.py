"""Слияние списков gaps без дубликатов."""

from __future__ import annotations


def merge_gaps(*parts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        for raw in part:
            line = str(raw).strip()
            if not line or line in seen:
                continue
            seen.add(line)
            out.append(line)
    return out
