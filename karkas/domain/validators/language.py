"""karkas.domain.validators.language — язык материалов (Д4 §5.8, V-LNG-01).

Два правила уровня warning:
- доля кириллицы в текстах комплекта не ниже 60 % — тексты считаются
  нерусскими, если доля ниже порога и кириллических букв меньше трёх
  (названия технологий латиницей, например «Основы Python», допустимы);
- для аудитории «школьники/класс/подростки» глоссарий профиля не пуст
  (термины поясняются при первом упоминании, ТК1-5, ТК1-8).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from karkas.domain.validators.base import (
    CYRILLIC_MIN_SHARE,
    GroupResult,
    cyrillic_letters,
    cyrillic_share,
    is_substantial_text,
    issue,
    iter_text_units,
)

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

_SCHOOL_AUDIENCE_RE = re.compile(r"школьн|подрост|\bкласс(?:а|у|ы|е|ов|ам|ах|ом|ами)?\b", re.IGNORECASE)
_MAX_TEXT_SHOWN = 60
_MIN_CYRILLIC_LETTERS = 3
_LAYOUT_IDS = frozenset({"title_and_content", "title", "title_only", "content"})
_CODE_SNIPPET_RE = re.compile(
    r"\b(if|elif|else)\b|"
    r"\bfor\s+\w+\s+in\s+|"
    r"\bwhile\s+\w+|"
    r"\bdef\s+\w+\s*\(|"
    r"[=<>!]=|[+\-*/%]=|\w+\s*\([^)]*\)",
    re.IGNORECASE,
)


def _looks_like_code_snippet(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 200:
        return False
    if _CODE_SNIPPET_RE.search(stripped):
        return True
    return bool(":" in stripped and re.search(r"\b(for|while|def|class)\b", stripped, re.I))


def _language_issues(ctx: ValidationContext) -> list:
    issues = []
    for ref, text in iter_text_units(ctx.kit):
        if not is_substantial_text(text):
            continue
        if _looks_like_code_snippet(text):
            continue
        if text.strip().lower() in _LAYOUT_IDS:
            continue
        share = cyrillic_share(text)
        if share < CYRILLIC_MIN_SHARE and cyrillic_letters(text) < _MIN_CYRILLIC_LETTERS:
            shown = text.strip().replace("\n", " ")
            if len(shown) > _MAX_TEXT_SHOWN:
                shown = shown[: _MAX_TEXT_SHOWN - 1] + "…"
            issues.append(
                issue(
                    "V-LNG-01",
                    "warning",
                    f"Текст «{shown}» не на русском языке (кириллицы {share:.0%} < "
                    f"{CYRILLIC_MIN_SHARE:.0%}) — материалы программы должны быть на русском",
                    entity_ref=ref,
                )
            )
    return issues


def _glossary_issues(ctx: ValidationContext) -> list:
    audience = ctx.kit.profile.audience or ""
    if not _SCHOOL_AUDIENCE_RE.search(audience):
        return []
    if ctx.kit.profile.glossary:
        return []
    return [
        issue(
            "V-LNG-01",
            "warning",
            "Аудитория — школьники: добавьте глоссарий терминов, чтобы сложные слова пояснялись при первом упоминании",
            entity_ref=None,
        )
    ]


def validate(ctx: ValidationContext) -> GroupResult:
    """Все проверки группы «Язык»."""
    issues = _language_issues(ctx)
    issues += _glossary_issues(ctx)
    checked = sum(1 for _, text in iter_text_units(ctx.kit) if is_substantial_text(text))
    meta = {"checked": checked, "min_cyrillic_share": CYRILLIC_MIN_SHARE}
    return GroupResult(issues=issues, meta=meta)
