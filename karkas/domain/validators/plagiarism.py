"""karkas.domain.validators.plagiarism — заимствования из референсов (Д4 §5.8).

Реализовано правило V-PLG-01: доля общих n-грамм (settings.plagiarism_ngram,
по умолчанию 5) между абзацем текста комплекта и референсами сравнивается с
settings.plagiarism_max_overlap (по умолчанию 15 %). Превышение — error
с указанием совпавшего фрагмента. Нет reference_texts — правило пропускается.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from karkas.domain.validators.base import (
    GroupResult,
    issue,
    iter_text_units,
    paragraphs,
    shingles,
    word_tokens,
)
from karkas.settings import settings

if TYPE_CHECKING:  # pragma: no cover - только для аннотаций
    from karkas.domain.validators import ValidationContext

_FRAGMENT_WORDS = 24


def _reference_shingles(reference_texts: list[str], size: int) -> set[tuple[str, ...]]:
    known: set[tuple[str, ...]] = set()
    for text in reference_texts:
        known |= shingles(word_tokens(text), size)
    return known


def _first_shared_fragment(tokens: list[str], size: int, known: set[tuple[str, ...]]) -> str:
    for start in range(len(tokens) - size + 1):
        gram = tuple(tokens[start : start + size])
        if gram in known:
            return " ".join(tokens[start : start + _FRAGMENT_WORDS])
    return " ".join(tokens[:size])


def validate(ctx: "ValidationContext") -> GroupResult:
    """Проверка дословного копирования референсов."""
    references = [t for t in ctx.reference_texts if t and t.strip()]
    if not references:
        return GroupResult(
            skipped=["V-PLG-01"],
            meta={
                "max_overlap": 0.0,
                "ngram": settings.plagiarism_ngram,
                "threshold": settings.plagiarism_max_overlap,
            },
        )

    size = settings.plagiarism_ngram
    threshold = settings.plagiarism_max_overlap
    known = _reference_shingles(references, size)

    issues = []
    max_overlap = 0.0
    for ref, text in iter_text_units(ctx.kit):
        for paragraph in paragraphs(text):
            tokens = word_tokens(paragraph)
            if len(tokens) < size:
                continue
            gram_set = shingles(tokens, size)
            overlap = len(gram_set & known) / len(gram_set)
            max_overlap = max(max_overlap, overlap)
            if overlap > threshold:
                fragment = _first_shared_fragment(tokens, size, known)
                issues.append(
                    issue(
                        "V-PLG-01",
                        "error",
                        f"Фрагмент «{fragment}» совпадает с референсом на {overlap:.0%} "
                        f"(порог {threshold:.0%}) — перефразируйте своими словами",
                        entity_ref=ref,
                    )
                )
    meta = {
        "max_overlap": round(max_overlap, 4),
        "ngram": size,
        "threshold": threshold,
    }
    return GroupResult(issues=issues, meta=meta)
