"""Адаптация SQL под SQLite (режим KARKAS_LITE) и PostgreSQL."""

from __future__ import annotations

from karkas.settings import settings


def uses_sqlite() -> bool:
    return settings.database_url.startswith("sqlite")


def uuid_param(name: str) -> str:
    """Плейсхолдер UUID: в SQLite — текст, в PG — CAST."""
    if uses_sqlite():
        return f":{name}"
    return f"CAST(:{name} AS uuid)"


def json_param(name: str) -> str:
    if uses_sqlite():
        return f":{name}"
    return f"CAST(:{name} AS jsonb)"


def now_expr() -> str:
    return "datetime('now')" if uses_sqlite() else "now()"


def run_after_delay(seconds_param: str = ":delay") -> str:
    if uses_sqlite():
        return f"datetime('now', '+' || {seconds_param} || ' seconds')"
    return f"now() + make_interval(secs => {seconds_param})"


def run_after_hours(hours_param: str = ":ttl") -> str:
    if uses_sqlite():
        return f"datetime('now', '+' || {hours_param} || ' hours')"
    return f"now() + make_interval(hours => {hours_param})"


def interval_24h() -> str:
    if uses_sqlite():
        return "datetime('now', '-24 hours')"
    return "now() - interval '24 hours'"


def cache_hit_pct_expr() -> str:
    if uses_sqlite():
        return "round(100.0 * avg(cache_hit), 1)"
    return "round(100.0 * avg(cache_hit::int), 1)"
