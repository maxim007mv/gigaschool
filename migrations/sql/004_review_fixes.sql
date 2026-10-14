-- =====================================================================
-- КАРКАС · миграция 004 · аддитивные изменения по итогам ревью
-- =====================================================================
-- 1) Закреплённые ячейки тем («замок» в таблице часов, Д4 §5.9/§6.4):
--    раньше Topic.locked жил только в памяти и терялся при reload.
ALTER TABLE topic ADD COLUMN IF NOT EXISTS locked text[] NOT NULL DEFAULT '{}';

-- 2) Привязка артефакта к конкретной выгрузке (GET /exports/{id} должен
--    возвращать файлы ИМЕННО этой выгрузки, а не последние по программе).
ALTER TABLE artifact ADD COLUMN IF NOT EXISTS export_id uuid;
CREATE INDEX IF NOT EXISTS artifact_export_idx ON artifact (export_id) WHERE export_id IS NOT NULL;

-- 3) Уникальность Idempotency-Key автопрогонов (Д1 §14: повтор не создаёт дубль).
--    Ключ хранится в request jsonb; частичный уникальный индекс ловит гонку.
CREATE UNIQUE INDEX IF NOT EXISTS agent_run_idempotency_uniq
    ON agent_run ((request->>'idempotency_key'))
    WHERE request ? 'idempotency_key' AND coalesce(request->>'idempotency_key', '') <> '';
