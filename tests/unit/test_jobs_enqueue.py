"""Очередь задач: модуль импортирует uuid (иначе enqueue → 500)."""

from __future__ import annotations

import uuid as uuid_mod

import karkas.infra.repos.jobs as jobs_repo


def test_jobs_repo_has_uuid() -> None:
    assert jobs_repo.uuid is uuid_mod
