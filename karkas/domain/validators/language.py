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
    strip_code_spans,
)

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

_SCHOOL_AUDIENCE_RE = re.compile(r"школьн|подрост|\bкласс(?:а|у|ы|е|ов|ам|ах|ом|ами)?\b", re.IGNORECASE)
_MAX_TEXT_SHOWN = 60
_MIN_CYRILLIC_LETTERS = 3
_LAYOUT_IDS = frozenset({"title_and_content", "title", "title_only", "content"})
_CODE_SNIPPET_RE = re.compile(
    r"\b(if|elif|else)\s*:\s*$|"
    r"\bfor\s+\w+\s+in\s+.*:\s*$|"
    r"\bwhile\s+.*:\s*$|"
    r"\bdef\s+\w+\s*\(|"
    r"\bclass\s+\w+.*:\s*$|"
    r"^\s*(?:import\s+[\w.]+|from\s+[\w.]+\s+import\b)|"
    r"^\s*return\b|"
    r"[=<>!]=|[+\-*/%]=",
    re.IGNORECASE,
)

_SINGLE_TOKEN_CODE_RE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_.]*\s*\(.*\)|[A-Za-z0-9_]+)$")
_EXPRESSION_CODE_RE = re.compile(r"[=<>{};\[\]]")

_COMMAND_SNIPPET_RE = re.compile(
    r"^\s*(?:[$#>]|\w+@\w+[:~].*[$#])\s*\S+|"  # prompt markers like "$ git commit", "# apt update"
    r"^\s*(?:git\s+(?:clone|commit|checkout|pull|push|add|status|branch|merge|init|rebase|log)|docker\s+|docker-compose\s+|podman\s+|kubectl\s+|helm\s+|minikube\s+)|"
    r"^\s*(?:pip|pip3|npm|npx|yarn|pnpm|uv|poetry|cargo)\s+(?:install|run|build|add|remove|update|init|check)|"
    r"^\s*(?:apt|apt-get|yum|dnf|apk|pacman|brew)\s+(?:install|update|upgrade)|"
    r"^\s*(?:terraform|terragrunt|ansible|ansible-playbook)\s+|"
    r"^\s*(?:systemctl|journalctl|service)\s+|"
    r"^\s*(?:curl|wget|ssh|scp|rsync)\s+|"
    r"^\s*(?:chmod|chown)\s+[0-9a-zA-Z+-]+|"
    r"^\s*(?:cd\s+\S+|export\s+\w+=|source\s+\S+)|"
    r"^\s*(?:python3?|bash|sh)\s+(?:-[a-zA-Z0-9_-]+|\S+\.(?:py|sh|bash)|[./]\S+)",
    re.IGNORECASE,
)


def _looks_like_code_snippet(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("```") or stripped.startswith("`"):
        return True
    # Отдельные идентификаторы/вызовы (print(), my_var, 1stValue) и выражения
    # (fruits = {...}, x > 5 and x < 10) — код, а не текст программы.
    if cyrillic_letters(stripped) == 0 and "\n" not in stripped and _SINGLE_TOKEN_CODE_RE.match(stripped):
        return True
    if cyrillic_letters(stripped) == 0 and _EXPRESSION_CODE_RE.search(stripped):
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return False
    code_lines = 0
    for line in lines:
        if (
            _COMMAND_SNIPPET_RE.search(line)
            or _CODE_SNIPPET_RE.search(line)
            or bool(":" in line and re.search(r"\b(for|while|def|class)\b", line, re.I))
            or line.startswith(("/", "./", "../", "http://", "https://"))
        ):
            code_lines += 1
    if code_lines > 0 and code_lines >= len(lines) / 2:
        return True
    if len(stripped) <= 200:
        if _COMMAND_SNIPPET_RE.search(stripped) or _CODE_SNIPPET_RE.search(stripped):
            return True
        if ":" in stripped and re.search(r"\b(for|while|def|class)\b", stripped, re.I):
            return True
    return False


def _language_issues(ctx: ValidationContext) -> list:
    issues = []
    for ref, text in iter_text_units(ctx.kit):
        text = strip_code_spans(text)
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
