"""Минимальный разбор GIFT для round-trip тестов (не полный парсер Moodle)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CATEGORY_RE = re.compile(r"^\$CATEGORY:\s*(.+)$")
_QUESTION_RE = re.compile(r"^::(?P<ref>[^ \]]+)(?:\s*\[[^\]]*\])?::(?P<stem>.+)$")


@dataclass
class ParsedGiftQuestion:
    ref: str
    stem: str
    correct_count: int = 0
    distractor_count: int = 0
    category: str | None = None


@dataclass
class ParsedGift:
    categories: list[str] = field(default_factory=list)
    questions: list[ParsedGiftQuestion] = field(default_factory=list)


def parse_gift(text: str) -> ParsedGift:
    """Разобрать экспорт GIFT: категории и заголовки вопросов с числом = и ~."""
    result = ParsedGift()
    current_category: str | None = None
    current: ParsedGiftQuestion | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            result.questions.append(current)
            current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        cat = _CATEGORY_RE.match(line)
        if cat:
            flush()
            current_category = cat.group(1).strip()
            result.categories.append(current_category)
            continue
        if line.startswith("::"):
            flush()
            match = _QUESTION_RE.match(line)
            if match:
                current = ParsedGiftQuestion(
                    ref=match.group("ref"),
                    stem=match.group("stem").strip(),
                    category=current_category,
                )
            continue
        if current is None:
            continue
        if line.startswith("="):
            current.correct_count += 1
        elif line.startswith("~"):
            current.distractor_count += 1
        elif line.startswith("{") and ("TRUE" in line or "FALSE" in line):
            current.correct_count += 1
    flush()
    return result
