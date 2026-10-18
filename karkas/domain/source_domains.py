"""Белый список доменов для internet-источников (без сетевых вызовов в тестах)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

DOMAINS_JSON = Path(__file__).resolve().parents[2] / "data" / "registries" / "source_domains.json"


@lru_cache(maxsize=1)
def allowed_domains() -> frozenset[str]:
    if not DOMAINS_JSON.is_file():
        return frozenset()
    try:
        raw = json.loads(DOMAINS_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return frozenset()
    hosts: set[str] = set()
    for item in raw.get("domains") or []:
        host = str(item).strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
        if host.startswith("www."):
            host = host[4:]
        if host:
            hosts.add(host)
    return frozenset(hosts)


def parse_url_host(url: str | None) -> str | None:
    if not url or not str(url).strip():
        return None
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def url_on_allowlist(url: str | None) -> tuple[bool, str | None]:
    """(разрешён, host) — только синтаксис URL и белый список."""
    host = parse_url_host(url)
    if host is None:
        return False, None
    allowed = allowed_domains()
    if not allowed:
        return False, host
    if host in allowed:
        return True, host
    for domain in allowed:
        if host == domain or host.endswith(f".{domain}"):
            return True, host
    return False, host
