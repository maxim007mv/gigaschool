#!/usr/bin/env python3
"""Переиндексация kb_document → kb_chunk (эмбеддинги 1024, pgvector).

Использование:
  .venv/bin/python scripts/backfill_kb_embeddings.py
  .venv/bin/python scripts/backfill_kb_embeddings.py --org-id <uuid>
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from karkas.agent.pipeline import _index_kb_document
from karkas.infra.db import dispose_engine, get_session_factory
from karkas.settings import settings


async def main(org_id: str | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        query = "SELECT id::text FROM kb_document"
        params: dict[str, str] = {}
        if org_id:
            query += " WHERE org_id = CAST(:org AS uuid)"
            params["org"] = org_id
        rows = (await session.execute(text(query), params)).scalars().all()
        total = 0
        for doc_id in rows:
            n = await _index_kb_document(session, doc_id)
            total += n
            await session.commit()
            print(f"indexed {doc_id}: {n} chunks")
    await dispose_engine()
    print(f"done, chunks={total}, model={settings.model_embed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--org-id", default=None)
    args = parser.parse_args()
    asyncio.run(main(args.org_id))
