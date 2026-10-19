-- Lite-схема: уникальность file_object(org_id, sha256).
-- В PostgreSQL дедупликация файлов опирается на это ограничение, в SQLite его
-- не было, поэтому INSERT ... ON CONFLICT (org_id, sha256) падал с
-- "ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint".

CREATE UNIQUE INDEX IF NOT EXISTS uq_file_object_org_sha256
    ON file_object (org_id, sha256);
