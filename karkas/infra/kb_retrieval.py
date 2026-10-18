"""RAG: выборка фрагментов kb_chunk под бюджет токенов."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from karkas.eval.token_estimate import estimate_tokens
from karkas.infra.sql_dialect import uses_sqlite

logger = logging.getLogger(__name__)


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


def _pack_snippets(
    rows: list[Any],
    *,
    limit: int,
    max_tokens: int,
) -> list[dict[str, str]]:
    snippets: list[dict[str, str]] = []
    budget = max_tokens
    for row in rows[:limit]:
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


def _like_pattern(query: str) -> str:
    q = (query or "").strip()
    words = [w for w in q.split() if len(w) > 3][:8]
    return f"%{words[0]}%" if words else f"%{q[:40]}%"


async def _retrieve_like(
    session: AsyncSession,
    org_id: str,
    query: str,
    *,
    limit: int,
) -> list[Any]:
    """SQLite: LIKE по первому значимому слову запроса (без pgvector)."""
    like = _like_pattern(query)
    rows = (
        (
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
        )
        .mappings()
        .all()
    )
    return list(rows)


async def _retrieve_keyword_pg(
    session: AsyncSession,
    org_id: str,
    query: str,
    *,
    limit: int,
) -> list[Any]:
    """PostgreSQL без эмбеддинга: ILIKE по ключевому слову (деградация RAG)."""
    like = _like_pattern(query)
    rows = (
        (
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
        )
        .mappings()
        .all()
    )
    return list(rows)


async def _org_has_kb_chunks(session: AsyncSession, org_id: str) -> bool:
    row = (
        await session.execute(
            text(
                """
                SELECT 1 FROM kb_chunk
                WHERE org_id = CAST(:org AS uuid)
                LIMIT 1
                """
            ),
            {"org": org_id},
        )
    ).first()
    return row is not None


async def _retrieve_pgvector(
    session: AsyncSession,
    org_id: str,
    query: str,
    *,
    limit: int,
) -> list[Any]:
    """PostgreSQL + pgvector: cosine top-k по эмбеддингу запроса (Giga-Embeddings)."""
    if not await _org_has_kb_chunks(session, org_id):
        return []
    from karkas.agent.llm_gateway import TransientError
    from karkas.infra.embeddings import embed_texts

    try:
        vectors = await embed_texts([query.strip()])
    except TransientError as exc:
        logger.warning("kb_retrieval: embed failed (%s), skip vector search", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("kb_retrieval: embed error (%s), skip vector search", exc)
        return []
    if not vectors:
        return []
    qvec = _vector_literal(vectors[0])
    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT c.heading_path, c.content
                FROM kb_chunk c
                WHERE c.org_id = CAST(:org AS uuid)
                ORDER BY c.embedding <=> CAST(:qvec AS vector)
                LIMIT :lim
                """
                ),
                {"org": org_id, "qvec": qvec, "lim": int(limit)},
            )
        )
        .mappings()
        .all()
    )
    return list(rows)


async def retrieve_kb_snippets(
    session: AsyncSession,
    org_id: str,
    query: str,
    *,
    limit: int = 5,
    max_tokens: int = 1200,
) -> list[dict[str, str]]:
    """Top-k фрагментов: pgvector при доступных эмбеддингах; иначе keyword ILIKE/LIKE."""
    q = (query or "").strip()
    if not q or not org_id:
        return []

    rows: list[Any] = []
    if uses_sqlite():
        rows = await _retrieve_like(session, org_id, q, limit=limit)
    else:
        from karkas.agent.llm_gateway import TransientError
        from karkas.settings import settings

        if settings.fm_api_key and settings.model_embed:
            try:
                rows = await _retrieve_pgvector(session, org_id, q, limit=limit)
            except TransientError as exc:
                logger.warning("kb_retrieval: эмбеддинги недоступны (%s), keyword fallback", exc)
            except Exception as exc:  # noqa: BLE001 — RAG не должен валить конвейер
                logger.warning("kb_retrieval: ошибка pgvector (%s), keyword fallback", exc)
        else:
            logger.warning(
                "kb_retrieval: FM_API_KEY / MODEL_EMBED не настроены — keyword fallback (org=%s)",
                org_id,
            )
        if not rows:
            rows = await _retrieve_keyword_pg(session, org_id, q, limit=limit)

    return _pack_snippets(rows, limit=limit, max_tokens=max_tokens)


def format_kb_snippets(snippets: list[dict[str, str]]) -> str:
    if not snippets:
        return ""
    lines = []
    for item in snippets:
        src = item.get("source") or "kb"
        lines.append(f"[{src}] {item.get('content', '')}")
    return "\n".join(lines)
