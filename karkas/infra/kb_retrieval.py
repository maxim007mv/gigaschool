"""RAG: выборка фрагментов kb_chunk под бюджет токенов (без лишних LLM-вызовов)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.eval.token_estimate import estimate_tokens


async def retrieve_kb_snippets(
    session: AsyncSession,
    org_id: str,
    query: str,
    *,
    limit: int = 5,
    max_tokens: int = 1200,
) -> list[dict[str, str]]:
    """Top-k фрагментов организации; при отсутствии pgvector — по длине текста запроса (LIKE)."""
    q = (query or "").strip()
    if not q or not org_id:
        return []
    words = [w for w in q.split() if len(w) > 3][:8]
    like = f"%{words[0]}%" if words else f"%{q[:40]}%"
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.heading_path, c.content
                    FROM kb_chunk c
                    WHERE c.org_id = CAST(:org AS uuid)
                      AND c.content ILIKE :like
                    ORDER BY c.ord
                    LIMIT :lim
                    """
                ),
                {"org": org_id, "like": like, "lim": int(limit)},
            )
        ).mappings().all()
    except Exception:
        try:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT c.heading_path, c.content
                        FROM kb_chunk c
                        WHERE c.org_id = :org
                          AND c.content LIKE :like
                        ORDER BY c.ord
                        LIMIT :lim
                        """
                    ),
                    {"org": org_id, "like": like, "lim": int(limit)},
                )
            ).mappings().all()
        except Exception:
            return []

    snippets: list[dict[str, str]] = []
    budget = max_tokens
    for row in rows:
        content = str(row["content"] or "").strip()
        if not content:
            continue
        heading = str(row["heading_path"] or "").strip()
        piece = content[:2000]
        cost = estimate_tokens(piece)
        if cost > budget:
            piece = piece[: max(200, budget * 4)]
            cost = estimate_tokens(piece)
        budget -= cost
        snippets.append({"heading": heading, "content": piece, "source": heading or "kb"})
        if budget <= 0:
            break
    return snippets


def format_kb_snippets(snippets: list[dict[str, str]]) -> str:
    if not snippets:
        return ""
    lines = []
    for item in snippets:
        src = item.get("source") or "kb"
        lines.append(f"[{src}] {item.get('content', '')}")
    return "\n".join(lines)
