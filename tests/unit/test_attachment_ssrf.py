"""Тесты защиты от SSRF при скачивании вложений по URL (ручная обработка редиректов)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from karkas.agent.pipeline import _fetch_attachment_url, _host_allowed, _url_host


def _factory(handler) -> object:
    transport = httpx.MockTransport(handler)

    def make() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, follow_redirects=False)

    return make


def test_url_host_parsing() -> None:
    assert _url_host("https://pypi.org/simple/") == "pypi.org"
    assert _url_host("http://user@Host.EXAMPLE:8080/x") == "host.example"
    # Обходы строкового парсинга: «@» в query/fragment не должен подменять хост.
    assert _url_host("http://169.254.169.254?x=@pypi.org") == "169.254.169.254"
    assert _url_host("http://169.254.169.254#@pypi.org") == "169.254.169.254"
    assert _host_allowed("pypi.org")
    assert not _host_allowed("127.0.0.1")


def test_query_at_sign_does_not_bypass_allowlist() -> None:
    """URL с «@» в query не должен считаться разрешённым хостом (SSRF)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("запрос на внутренний хост не должен уходить")

    with pytest.raises(ValueError, match="вне allowlist"):
        asyncio.run(
            _fetch_attachment_url("http://169.254.169.254?x=@pypi.org", name="x.txt", client_factory=_factory(handler))
        )


def test_fragment_at_sign_does_not_bypass_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("запрос на внутренний хост не должен уходить")

    with pytest.raises(ValueError, match="вне allowlist"):
        asyncio.run(
            _fetch_attachment_url("http://internal-svc:8080#@pypi.org", name="x.txt", client_factory=_factory(handler))
        )


def test_direct_disallowed_host_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("запрос не должен уйти на запрещённый хост")

    with pytest.raises(ValueError, match="вне allowlist"):
        asyncio.run(
            _fetch_attachment_url("http://127.0.0.1:9999/secret", name="x.txt", client_factory=_factory(handler))
        )


def test_redirect_to_disallowed_host_blocked() -> None:
    """Разрешённый хост не может увести запрос на внутренний сервис редиректом."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pypi.org":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:9999/secret"})
        raise AssertionError("внутренний хост не должен быть запрошен")

    with pytest.raises(ValueError, match="вне allowlist"):
        asyncio.run(_fetch_attachment_url("https://pypi.org/go", name="x.txt", client_factory=_factory(handler)))


def test_redirect_within_allowlist_allowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/go":
            return httpx.Response(302, headers={"location": "https://pypi.org/final"})
        if request.url.path == "/final":
            return httpx.Response(200, content=b"payload")
        raise AssertionError(f"неожиданный путь {request.url.path}")

    data = asyncio.run(_fetch_attachment_url("https://pypi.org/go", name="x.txt", client_factory=_factory(handler)))
    assert data == b"payload"


def test_too_many_redirects_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://pypi.org/loop"})

    with pytest.raises(ValueError, match="слишком много редиректов"):
        asyncio.run(_fetch_attachment_url("https://pypi.org/loop", name="x.txt", client_factory=_factory(handler)))
