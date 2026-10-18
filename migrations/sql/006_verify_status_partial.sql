-- КАРКАС · 006_verify_status_partial · значение partially_verified для S18
BEGIN;
ALTER TYPE verify_status ADD VALUE IF NOT EXISTS 'partially_verified';
COMMIT;
