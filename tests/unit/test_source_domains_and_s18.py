"""Белый список доменов и статусы S18 (без сети)."""

from __future__ import annotations

from karkas.agent.skills.S18_source_verification.run import verify_source
from karkas.domain.source_domains import url_on_allowlist


def test_allowlisted_domain() -> None:
    ok, host = url_on_allowlist("https://docs.python.org/3/tutorial/")
    assert ok is True
    assert host == "docs.python.org"


def test_unknown_domain_rejected() -> None:
    ok, _ = url_on_allowlist("https://evil.example/phish")
    assert ok is False


def test_internet_source_verified_on_allowlist() -> None:
    row = verify_source(
        {
            "section": "internet",
            "citation": "Документация Python",
            "url": "https://docs.python.org/3/",
        },
        None,
        __import__("datetime").date.today(),
    )
    assert row["status"] == "verified"
    assert row["evidence"].get("domain_allowlisted") is True


def test_invented_internet_not_found() -> None:
    row = verify_source(
        {
            "section": "internet",
            "citation": "Сомнительный ресурс",
            "url": "https://totally-unknown-site.invalid/page",
        },
        None,
        __import__("datetime").date.today(),
    )
    assert row["status"] == "not_found"


def test_isbn_partially_verified() -> None:
    row2 = verify_source(
        {"section": "main", "citation": "Book", "isbn": "9780306406157"},
        None,
        __import__("datetime").date.today(),
    )
    assert row2["status"] == "partially_verified"
