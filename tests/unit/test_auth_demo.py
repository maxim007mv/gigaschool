"""B-02: демо-вход — Argon2id-хэш демо-пароля."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_EMAIL = "methodist@acr-demo.example"


def _demo_password() -> str:
    src = (ROOT / "web/src/pages/LoginPage.tsx").read_text(encoding="utf-8")
    match = re.search(r"""const\s+DEMO_PASSWORD\s*=\s*['"]([^'"]+)['"]""", src)
    assert match, "DEMO_PASSWORD не найдена в web/src/pages/LoginPage.tsx"
    return match.group(1)


def _demo_hash() -> str:
    sql = (ROOT / "migrations/sql/901_demo_password.sql").read_text(encoding="utf-8")
    assert DEMO_EMAIL in sql
    match = re.search(r"password_hash\s*=\s*'(\$argon2id\$[^']+)'", sql)
    assert match
    return match.group(1)


def test_demo_password_verifies() -> None:
    from karkas.api.routers.auth import _hash_verify

    assert _hash_verify(_demo_password(), _demo_hash()) is True
