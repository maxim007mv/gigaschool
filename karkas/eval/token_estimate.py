"""Оценка числа токенов без вызова провайдера (бенчмарк и сравнение промптов)."""

from __future__ import annotations

import math
import re


def estimate_tokens(text: str) -> int:
    """Грубая оценка: max(символы/4, слова×1.3) — близко к BPE для рус+JSON."""
    if not text:
        return 0
    chars = len(text)
    words = len(re.findall(r"\S+", text))
    return max(1, int(math.ceil(max(chars / 4.0, words * 1.3))))


def estimate_messages_tokens(messages: list[dict[str, object]]) -> int:
    """Сумма токенов по полям content сообщений."""
    total = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
    return total
