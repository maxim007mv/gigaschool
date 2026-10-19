-- Lite-схема: колонки реестра НПА, которые есть в PostgreSQL, но отсутствовали в SQLite.
-- Применяется после 001_lite.sql / 002_lite_core_tables.sql (см. migrations/lite.py).
--
-- Без official_url запрос karkas/infra/repos/registry.py:normative_acts падал в lite-режиме
-- (OperationalError: no such column: official_url), из-за чего задача framework уходила в failed.

ALTER TABLE normative_act ADD COLUMN official_url TEXT;
