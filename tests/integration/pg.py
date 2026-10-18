"""PostgreSQL helpers for integration tests (CI uses PGUSER=postgres)."""

from __future__ import annotations

import os


def pg_user() -> str:
    return os.environ.get("PGUSER") or os.environ.get("USER", "postgres")
