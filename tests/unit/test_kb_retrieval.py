"""RAG: pgvector на Postgres, LIKE на SQLite."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from karkas.infra import kb_retrieval as kb


@pytest.mark.asyncio
async def test_sqlite_uses_like_not_embeddings(monkeypatch) -> None:
    monkeypatch.setattr(kb, "uses_sqlite", lambda: True)

    async def fail_embed(_texts):
        raise AssertionError("embed_texts must not run on SQLite")

    monkeypatch.setattr("karkas.infra.embeddings.embed_texts", fail_embed)

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            mappings=MagicMock(
                return_value=MagicMock(
                    all=MagicMock(return_value=[{"heading_path": "H1", "content": "Python для школьников"}])
                )
            )
        )
    )

    out = await kb.retrieve_kb_snippets(session, "org-1", "программирование Python", limit=3, max_tokens=500)
    assert out and "Python" in out[0]["content"]
    sql = str(session.execute.call_args[0][0])
    assert "ILIKE" in sql or "LIKE" in sql
    assert "vector" not in sql.lower()


@pytest.mark.asyncio
async def test_postgres_uses_pgvector_order(monkeypatch) -> None:
    monkeypatch.setattr(kb, "uses_sqlite", lambda: False)
    monkeypatch.setattr("karkas.settings.settings.fm_api_key", "test-key")
    monkeypatch.setattr("karkas.settings.settings.model_embed", "embed-model")

    async def fake_embed(texts):
        assert len(texts) == 1
        return [[0.0] * 1024]

    monkeypatch.setattr("karkas.infra.embeddings.embed_texts", fake_embed)

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            mappings=MagicMock(
                return_value=MagicMock(
                    all=MagicMock(
                        return_value=[
                            {"heading_path": "A", "content": "релевантный фрагмент базы знаний"},
                        ]
                    )
                )
            )
        )
    )

    out = await kb.retrieve_kb_snippets(session, "00000000-0000-0000-0000-0000000000a1", "запрос", limit=2)
    assert out[0]["content"].startswith("релевант")
    sql = str(session.execute.call_args[0][0])
    assert "<=>" in sql
    params = session.execute.call_args[0][1]
    assert "qvec" in params and params["qvec"].startswith("[")


@pytest.mark.asyncio
async def test_postgres_falls_back_to_keyword_when_embeddings_missing(monkeypatch) -> None:
    monkeypatch.setattr(kb, "uses_sqlite", lambda: False)
    monkeypatch.setattr("karkas.settings.settings.fm_api_key", "")
    monkeypatch.setattr("karkas.settings.settings.model_embed", "")

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            mappings=MagicMock(
                return_value=MagicMock(
                    all=MagicMock(return_value=[{"heading_path": "H", "content": "фрагмент по ключу"}])
                )
            )
        )
    )
    out = await kb.retrieve_kb_snippets(session, "00000000-0000-0000-0000-0000000000a1", "тест", limit=1)
    assert out and "фрагмент" in out[0]["content"]
    sql = str(session.execute.call_args[0][0])
    assert "ILIKE" in sql


@pytest.mark.asyncio
async def test_postgres_falls_back_on_transient_embed_error(monkeypatch) -> None:
    from karkas.agent.llm_gateway import TransientError

    monkeypatch.setattr(kb, "uses_sqlite", lambda: False)
    monkeypatch.setattr("karkas.settings.settings.fm_api_key", "key")
    monkeypatch.setattr("karkas.settings.settings.model_embed", "embed")

    async def fail_embed(_texts):
        raise TransientError("embed down")

    monkeypatch.setattr("karkas.infra.embeddings.embed_texts", fail_embed)

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            mappings=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[{"heading_path": "H", "content": "keyword hit"}]))
            )
        )
    )
    out = await kb.retrieve_kb_snippets(session, "00000000-0000-0000-0000-0000000000a1", "запрос", limit=1)
    assert out[0]["content"] == "keyword hit"
