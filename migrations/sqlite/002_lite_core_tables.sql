-- Lite-схема: недостающие таблицы для загрузки/сохранения каркаса.
-- Применяется после 001_lite.sql (см. migrations/lite.py).

CREATE TABLE IF NOT EXISTS source_usage (
    source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    topic_id TEXT NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, topic_id)
);

CREATE TABLE IF NOT EXISTS program_file (
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL REFERENCES file_object(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'reference',
    analysis TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (program_id, file_id)
);

-- PostgreSQL-версия хранит закреплённые ячейки в отдельной колонке.
-- В lite-схеме её не было, из-за чего load_kit/save_kit расходились.
ALTER TABLE topic ADD COLUMN locked TEXT NOT NULL DEFAULT '[]';
