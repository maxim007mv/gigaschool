-- Lite-схема: минимальная таблица RAG, чтобы keyword-поиск не падал.
-- Векторный поиск (pgvector) в lite не используется.

CREATE TABLE IF NOT EXISTS kb_chunk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    file_id TEXT,
    ord INTEGER NOT NULL,
    heading_path TEXT,
    content TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    embedding TEXT
);
