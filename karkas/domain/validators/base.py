"""karkas.domain.validators.base — общие примитивы правил самопроверки (Д4 §5.8).

Здесь нет самих правил: только создание issue, результат группы правил,
определение стадии комплекта (каркас/комплект) и текстовые утилиты
(нормализация, кириллица, n-граммы, косинус, обход текстов KitV1).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from karkas.domain.kit import IssueSeverity, ReportIssue

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.kit import KitV1
    from karkas.domain.validators import ValidationContext

Stage = Literal["framework", "kit"]

CYRILLIC_MIN_SHARE = 0.6  # V-LNG-01: доля кириллицы в русском тексте
_TOLERATED_LETTERS = 5  # тексты короче не проверяются (заголовки-аббревиатуры)

_WORD_RE = re.compile(r"[А-Яа-яЁёA-Za-z]+")
_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+")
_SPACES_RE = re.compile(r"\s+")


@dataclass
class GroupResult:
    """Результат группы правил (например, всех правил часов)."""

    issues: list[ReportIssue] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Группа без блокирующих ошибок (warning/info не блокируют)."""
        return not any(i.severity == "error" for i in self.issues)


def issue(
    rule_code: str,
    severity: IssueSeverity,
    message: str,
    *,
    entity_ref: str | None = None,
    fix_hint: dict[str, Any] | None = None,
) -> ReportIssue:
    """Собрать ReportIssue единым образом (все сообщения — по-русски)."""
    return ReportIssue(
        rule_code=rule_code,
        severity=severity,
        entity_ref=entity_ref,
        message=message,
        fix_hint=fix_hint,
    )


def resolve_stage(ctx: ValidationContext) -> Stage:
    """Стадия проверки: «framework» (S10, без содержания) или «kit» (S19).

    Значение `ctx.stage`:
    - "framework"/"kit" — задано явно;
    - "auto" (по умолчанию) — если в комплекте есть хоть один элемент
      содержания (оценочные средства, источники, блоки), это «kit»; иначе
      проверяется только каркас, а правила содержания пропускаются.
    """
    explicit = getattr(ctx, "stage", "auto")
    if explicit in ("framework", "kit"):
        return explicit
    content = ctx.kit.content
    has_content = bool(
        content.assessments
        or content.sources
        or content.module_programs
        or content.lecture_plans
        or content.slides
        or content.sections
    )
    return "kit" if has_content else "framework"


# ---------------------------------------------------------------------------
# Текстовые утилиты
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Регистронезависимая нормализация для сравнения дублей (V-DUP-01)."""
    return _SPACES_RE.sub(" ", text).strip().lower()


def stem_hash(text: str) -> str:
    """sha256 нормализованного текста вопроса — быстрый детектор дублей."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def cyrillic_share(text: str) -> float:
    """Доля кириллицы среди букв текста; 1.0, если букв нет (V-LNG-01)."""
    letters = _WORD_RE.findall(text)
    total = sum(len(word) for word in letters)
    if total == 0:
        return 1.0
    cyr = sum(len(_CYR_RE.findall(word)) for word in letters)
    return cyr / total


def cyrillic_letters(text: str) -> int:
    """Сколько кириллических букв в тексте (для V-LNG-01)."""
    return len(_CYR_RE.findall(text))


def is_substantial_text(text: str, min_letters: int = _TOLERATED_LETTERS) -> bool:
    """Достаточно ли в тексте букв, чтобы судить о языке."""
    return sum(len(w) for w in _WORD_RE.findall(text)) >= min_letters


def word_tokens(text: str) -> list[str]:
    """Слова и числа в нижнем регистре — вход n-грамм (V-PLG-01)."""
    return _TOKEN_RE.findall(text.lower())


def shingles(tokens: Sequence[str], size: int) -> set[tuple[str, ...]]:
    """Множество n-грамм (скользящее окно) для сравнения заимствований."""
    if size <= 0 or len(tokens) < size:
        return set()
    return {tuple(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Косинусная близость двух векторов; 0.0 при пустых или нулевых векторах."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def paragraphs(text: str) -> list[str]:
    """Разбить текст на абзацы (для V-PLG-01: сравнение идёт по абзацам)."""
    return [p.strip() for p in re.split(r"\n+", text) if p.strip()]


def _body_strings(value: Any, depth: int = 0) -> Iterator[str]:
    """Рекурсивно собрать строки из тела ContentBlock (с ограничением глубины)."""
    if depth > 4:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ("layout", "layout_kind"):
                continue
            yield from _body_strings(item, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _body_strings(item, depth + 1)


def iter_text_units(kit: KitV1) -> Iterator[tuple[str | None, str]]:
    """Все текстовые единицы комплекта: (ref элемента, текст).

    Используется V-LNG-01 (язык) и V-PLG-01 (заимствования).
    """
    yield None, kit.program.title
    if kit.program.document:
        yield None, kit.program.document
    for basis in kit.program.legal_basis:
        yield basis.ref, basis.act
    if kit.framework.goal:
        yield None, kit.framework.goal
    for task in kit.framework.tasks:
        yield None, task
    for competency in kit.framework.competencies:
        yield competency.ref, competency.title
        for outcome in competency.outcomes:
            yield outcome.ref, outcome.text
    for module in kit.framework.modules:
        yield module.ref, module.title
        for topic in module.topics:
            yield topic.ref, topic.title
            if topic.summary:
                yield topic.ref, topic.summary
    for assessment in kit.content.assessments:
        yield assessment.ref, assessment.stem
        for option in assessment.options:
            yield assessment.ref, option.text
        for criterion in assessment.rubric:
            yield assessment.ref, criterion.criterion
        if assessment.answer_key and assessment.answer_key.explanation:
            yield assessment.ref, assessment.answer_key.explanation
    for source in kit.content.sources:
        yield source.ref, source.citation
    _layout_ids = frozenset({"title_and_content", "title", "title_only", "content"})
    for group in (
        kit.content.module_programs,
        kit.content.lecture_plans,
        kit.content.slides,
        kit.content.sections,
    ):
        for block in group:
            for text in _body_strings(block.body):
                if text.strip().lower() in _layout_ids:
                    continue
                yield block.ref, text
