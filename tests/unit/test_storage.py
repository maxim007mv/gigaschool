"""Тесты локального объектного хранилища и вспомогательных функций."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from karkas.infra.storage import LocalStorage, content_sha256, verify_local_presign


def test_local_storage_roundtrip(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    key = storage.put("karkas-src", "org/file.txt", b"payload", content_type="text/plain")
    assert key == "org/file.txt"
    assert storage.get("karkas-src", key) == b"payload"
    url = storage.presign("karkas-src", key)
    assert url.startswith("http://")
    assert "/api/v1/local-storage/karkas-src/org/file.txt" in url
    query = parse_qs(urlparse(url).query)
    assert verify_local_presign("karkas-src", key, int(query["exp"][0]), query["sig"][0])


def test_local_storage_sanitizes_traversal(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    storage.put("karkas-src", "../../escape.txt", b"x")
    stored = list((tmp_path / "karkas-src").rglob("escape.txt"))
    assert stored, "файл должен лежать внутри корня хранилища"
    assert tmp_path.resolve() in stored[0].resolve().parents


def test_content_sha256_stable() -> None:
    assert content_sha256(b"abc") == content_sha256(b"abc")
    assert content_sha256(b"abc") != content_sha256(b"abd")
