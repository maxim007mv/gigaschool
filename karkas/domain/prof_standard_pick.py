"""Детерминированный подбор профстандарта и ТФ из реестра (fallback после S05)."""

from __future__ import annotations

import re
from typing import Any

# Минимальная доля совпадения лексем запроса с названием ПС/ТФ.
_MATCH_THRESHOLD = 0.08

_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower().replace("ё", "е")) if len(t) > 2}


def _score(query_tokens: set[str], target: str) -> float:
    if not query_tokens or not target:
        return 0.0
    target_tokens = _tokens(target)
    if not target_tokens:
        return 0.0
    exact = len(query_tokens & target_tokens) / len(query_tokens)
    fuzzy = 0.0
    for qt in query_tokens:
        for tt in target_tokens:
            if len(qt) >= 4 and (qt in tt or tt in qt):
                fuzzy += 1
                break
    fuzzy /= len(query_tokens)
    boosted = exact
    lowered = target.lower()
    if "python" in query_tokens and ("программ" in lowered or "код" in lowered):
        boosted = max(boosted, 0.2)
    if any(t in query_tokens for t in ("devops", "стажиров", "администр")) and "администратор" in lowered:
        boosted = max(boosted, 0.25)
    if any(t in query_tokens for t in ("pandas", "анализ", "данн", "банк")) and (
        "данн" in lowered or "программ" in lowered or "аналит" in lowered
    ):
        boosted = max(boosted, 0.18)
    return max(exact, fuzzy, boosted)


def _query_blob(profile: dict[str, Any], *, title: str = "", goal: str = "", brief: str = "") -> str:
    parts = [
        title,
        goal,
        brief,
        str(profile.get("audience") or ""),
        str(profile.get("entry_level") or ""),
        str(profile.get("notes") or ""),
        str(profile.get("schedule") or ""),
    ]
    return " ".join(parts)


def pick_prof_standard(
    profile: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    title: str = "",
    goal: str = "",
    brief: str = "",
) -> dict[str, Any] | None:
    """Вернуть результат в формате S05 или None, если порог не достигнут."""
    active = [c for c in candidates if str(c.get("status") or "active") == "active" and c.get("code")]
    if not active:
        return None
    query_tokens = _tokens(_query_blob(profile, title=title, goal=goal, brief=brief))
    if not query_tokens:
        return None

    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in active:
        code = str(candidate["code"])
        ps_title = str(candidate.get("title") or "")
        score = _score(query_tokens, ps_title)
        for lf in candidate.get("labor_functions") or []:
            if isinstance(lf, dict):
                score = max(score, _score(query_tokens, str(lf.get("title") or "")))
        if score > best_score:
            best_score = score
            best = candidate

    if best is None or best_score < _MATCH_THRESHOLD:
        return None

    code = str(best["code"])
    ps_title = str(best.get("title") or "")
    lf_list = [lf for lf in (best.get("labor_functions") or []) if isinstance(lf, dict) and lf.get("code")]
    best_lf: dict[str, Any] | None = None
    best_lf_score = 0.0
    for lf in lf_list:
        lf_score = _score(query_tokens, str(lf.get("title") or ""))
        if lf_score > best_lf_score:
            best_lf_score = lf_score
            best_lf = lf
    if best_lf is None and lf_list:
        best_lf = lf_list[0]
        best_lf_score = _score(query_tokens, str(best_lf.get("title") or ""))

    functions: list[dict[str, str]] = []
    if best_lf:
        functions.append(
            {
                "code": str(best_lf["code"]),
                "title": str(best_lf.get("title") or ""),
                "otf_code": str(best_lf.get("otf_code") or "") or None,
            }
        )

    gap_note = (
        f"Профстандарт {code} «{ps_title}» подобран автоматически по сходству с брифом "
        f"(частично проверено, score={best_score:.2f}) — уточните методистом."
    )
    return {
        "prof_standard": {"code": code, "title": ps_title},
        "labor_functions": functions,
        "confidence": min(0.85, 0.5 + best_score),
        "note": gap_note,
        "dropped_codes": [],
        "partially_verified": True,
        "gap": gap_note,
    }


def prof_standards_gap_section_text(gap: str) -> str:
    return (
        "Профстандарт и трудовые функции для данной программы не сопоставлены автоматически с достаточной "
        f"уверенностью. {gap} Программа опирается на заявленные компетенции и результаты обучения; "
        "при утверждении каркаса методист указывает актуальный профстандарт из реестра Минтруда."
    )
