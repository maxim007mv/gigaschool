"""Порядок миграций: 9xx только с --demo."""

from __future__ import annotations

from pathlib import Path

from migrations.runner import migration_files

REAL_SQL = Path(__file__).resolve().parent.parent.parent / "migrations" / "sql"


def test_real_prod_chain_has_no_demo() -> None:
    names = [p.name for p in migration_files(REAL_SQL, include_demo=False)]
    assert not any(n.startswith("9") for n in names)
    assert "006_verify_status_partial.sql" in names


def test_real_demo_chain_includes_password_not_usage() -> None:
    names = [p.name for p in migration_files(REAL_SQL, include_demo=True)]
    assert "901_demo_password.sql" in names
    assert "902_demo_usage.sql" not in names
    assert names.index("006_verify_status_partial.sql") < names.index("900_demo_sample248.sql")
