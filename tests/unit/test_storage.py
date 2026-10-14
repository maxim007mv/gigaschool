"""Тесты локального объектного хранилища и вспомогательных функций."""

from __future__ import annotations

from karkas.infra.storage import LocalStorage, content_sha256


def test_local_storage_roundtrip(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    key = storage.put("karkas-src", "org/file.txt", b"payload", content_type="text/plain")
    assert key == "org/file.txt"
    assert storage.get("karkas-src", key) == b"payload"
    assert storage.presign("karkas-src", key).startswith("file://")


def test_local_storage_sanitizes_traversal(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    storage.put("karkas-src", "../../escape.txt", b"x")
    stored = list((tmp_path / "karkas-src").rglob("escape.txt"))
    assert stored, "файл должен лежать внутри корня хранилища"
    assert tmp_path in stored[0].parents


def test_content_sha256_stable() -> None:
    assert content_sha256(b"abc") == content_sha256(b"abc")
    assert content_sha256(b"abc") != content_sha256(b"abd")
