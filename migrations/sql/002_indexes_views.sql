-- =====================================================================
-- КАРКАС · миграция 002 · индексы, представления, функции проверки, триггеры
-- =====================================================================

-- ---------- Хранение ------------------------------------------------------
ALTER TABLE program_version ALTER COLUMN snapshot SET COMPRESSION lz4;  -- JSONB-снимки 0,2–2 МБ (Д2 §8)

-- ---------- Индексы под реальные запросы --------------------------------
CREATE INDEX program_org_status_idx ON program (org_id, status, updated_at DESC);  -- список «Мои программы»
CREATE INDEX program_owner_idx ON program (owner_id, updated_at DESC);
CREATE INDEX program_parent_idx ON program (parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX module_program_idx ON module (program_id, number);
CREATE INDEX topic_module_idx ON topic (module_id, number);
CREATE INDEX topic_program_idx ON topic (program_id);
CREATE INDEX lo_competency_idx ON learning_outcome (competency_id, ord);
CREATE INDEX topic_outcome_outcome_idx ON topic_outcome (outcome_id);  -- обратный обход для V-COV
CREATE INDEX ao_outcome_idx ON assessment_outcome (outcome_id);
CREATE INDEX ai_program_kind_idx ON assessment_item (program_id, kind);
CREATE INDEX ai_topic_idx ON assessment_item (topic_id) WHERE topic_id IS NOT NULL;
CREATE INDEX ai_stale_idx ON assessment_item (program_id) WHERE stale;  -- частичный: только к пересборке
CREATE INDEX ai_hash_idx ON assessment_item (program_id, content_hash);  -- дубли вопросов
CREATE INDEX cb_topic_idx ON content_block (topic_id) WHERE topic_id IS NOT NULL;
CREATE INDEX cb_stale_idx ON content_block (program_id) WHERE stale;
CREATE INDEX source_status_idx ON source (program_id, status);
CREATE INDEX vrun_program_idx ON validation_run (program_id, created_at DESC);
CREATE INDEX vissue_run_idx ON validation_issue (run_id, severity);
CREATE INDEX artifact_program_idx ON artifact (program_id, version DESC);
CREATE INDEX edit_program_idx ON edit_request (program_id, created_at DESC);
CREATE INDEX clar_open_idx ON clarification (program_id) WHERE answer IS NULL;
CREATE INDEX file_org_idx ON file_object (org_id, created_at DESC);
-- Очередь: выборка следующей задачи за O(log n) по частичному индексу
CREATE INDEX job_ready_idx ON job (priority, run_after) WHERE status IN ('queued','retry_wait');
CREATE INDEX job_program_idx ON job (program_id, created_at DESC);
CREATE INDEX job_stuck_idx ON job (locked_at) WHERE status = 'running';
-- RAG: HNSW по косинусному расстоянию + полнотекст для гибридного поиска
CREATE INDEX kb_chunk_hnsw ON kb_chunk USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX kb_chunk_tsv ON kb_chunk USING gin (tsv);
CREATE INDEX kb_chunk_org ON kb_chunk (org_id);
-- Реестры: нечёткий поиск по названию профстандарта и ТФ
CREATE INDEX ps_title_trgm ON prof_standard USING gin (title_trgm gin_trgm_ops);
CREATE INDEX lf_title_trgm ON labor_function USING gin (lower(title) gin_trgm_ops);
CREATE INDEX na_lookup_idx ON normative_act (issuer, number);
CREATE INDEX llm_cache_exp ON llm_cache (expires_at);

-- ---------- Представления: часы считаются, а не хранятся -----------------
CREATE VIEW v_topic_hours AS
SELECT t.program_id, t.module_id, t.id AS topic_id, t.ref,
       coalesce(sum(w.hours) FILTER (WHERE w.activity = 'lecture'), 0)::int AS lecture,
       coalesce(sum(w.hours) FILTER (WHERE w.activity = 'practice'), 0)::int AS practice,
       coalesce(sum(w.hours) FILTER (WHERE w.activity = 'lab'), 0)::int AS lab,
       coalesce(sum(w.hours) FILTER (WHERE w.activity = 'self_study'), 0)::int AS self_study,
       coalesce(sum(w.hours) FILTER (WHERE w.activity = 'current_control'), 0)::int AS control,
       coalesce(sum(w.hours) FILTER (WHERE w.mode = 'distance'), 0)::int AS distance,
       coalesce(sum(w.hours), 0)::int AS total
FROM topic t LEFT JOIN topic_workload w ON w.topic_id = t.id
GROUP BY t.program_id, t.module_id, t.id, t.ref;

CREATE VIEW v_module_hours AS
SELECT m.program_id, m.id AS module_id, m.ref, m.number,
       coalesce(sum(h.lecture),0)::int AS lecture, coalesce(sum(h.practice),0)::int AS practice,
       coalesce(sum(h.lab),0)::int AS lab, coalesce(sum(h.self_study),0)::int AS self_study,
       coalesce(sum(h.control),0)::int AS control, coalesce(sum(h.distance),0)::int AS distance,
       coalesce(sum(h.total),0)::int AS total
FROM module m LEFT JOIN v_topic_hours h ON h.module_id = m.id
GROUP BY m.program_id, m.id, m.ref, m.number;

CREATE VIEW v_program_hours AS
SELECT p.id AS program_id, p.total_hours AS requested, p.final_att_hours,
       coalesce(sum(mh.lecture),0)::int AS lecture, coalesce(sum(mh.practice),0)::int AS practice,
       coalesce(sum(mh.lab),0)::int AS lab, coalesce(sum(mh.self_study),0)::int AS self_study,
       coalesce(sum(mh.control),0)::int AS control,
       (coalesce(sum(mh.total),0) + p.final_att_hours)::int AS grand_total
FROM program p LEFT JOIN v_module_hours mh ON mh.program_id = p.id
GROUP BY p.id, p.total_hours, p.final_att_hours;

-- Покрытие: каждый результат обучения ≥ 1 тема и ≥ 2 оценочных средства
CREATE VIEW v_outcome_coverage AS
SELECT lo.program_id, lo.id AS outcome_id, lo.ref, lo.type,
       (SELECT count(*) FROM topic_outcome tl WHERE tl.outcome_id = lo.id) AS topics,
       (SELECT count(*) FROM assessment_outcome ao WHERE ao.outcome_id = lo.id) AS assessments
FROM learning_outcome lo;

-- ---------- Функция проверки часов (V-HRS) ------------------------------
-- Возвращает пустой набор, если всё сходится; иначе — список нарушений.
CREATE OR REPLACE FUNCTION check_program_hours(p_program uuid)
RETURNS TABLE (rule_code text, entity_ref text, message text)
LANGUAGE sql STABLE AS $$
SELECT 'V-HRS-01', NULL::text,
       format('Сумма часов %s ≠ запрошенному объёму %s', ph.grand_total, ph.requested)
FROM v_program_hours ph
WHERE ph.program_id = p_program AND ph.grand_total IS DISTINCT FROM ph.requested
UNION ALL
SELECT 'V-HRS-02', t.ref, format('У темы %s нет часов', t.ref)
FROM v_topic_hours t WHERE t.program_id = p_program AND t.total = 0
UNION ALL
SELECT 'V-HRS-03', m.ref, format('В модуле %s нет тем с часами', m.ref)
FROM v_module_hours m WHERE m.program_id = p_program AND m.total = 0
UNION ALL
SELECT 'V-HRS-04', NULL,
       format('Только самостоятельная работа (стажировка), но найдено ЛК/ПР/ЛБ: %s ч', ph.lecture + ph.practice + ph.lab)
FROM v_program_hours ph JOIN program p ON p.id = ph.program_id
WHERE ph.program_id = p_program AND (p.constraints->>'self_study_only')::boolean
  AND ph.lecture + ph.practice + ph.lab > 0
UNION ALL
SELECT 'V-HRS-05', NULL,
       format('Практика %s ч меньше минимума %s%% от объёма', ph.practice + ph.lab, p.constraints->>'min_practice_share_pct')
FROM v_program_hours ph JOIN program p ON p.id = ph.program_id
WHERE ph.program_id = p_program AND p.constraints ? 'min_practice_share_pct'
  AND (ph.practice + ph.lab) * 100 < (p.constraints->>'min_practice_share_pct')::numeric * ph.requested;
$$;

-- Human Gate на уровне БД: нельзя утвердить каркас с ошибками часов
CREATE OR REPLACE FUNCTION trg_program_gate() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'framework_approved' AND OLD.status IS DISTINCT FROM 'framework_approved' THEN
    IF EXISTS (SELECT 1 FROM check_program_hours(NEW.id)) THEN
      RAISE EXCEPTION 'HOURS_MISMATCH: каркас нельзя утвердить, часы не сходятся'
      USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.approved_by IS NULL THEN
      RAISE EXCEPTION 'APPROVER_REQUIRED' USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  -- генерация содержания возможна только после утверждения
  -- (проверяем именно ПЕРЕХОД в kit_generating: обновления, не меняющие статус,
  --  например сохранение снимка версии воркером, падать не должны)
  IF NEW.status = 'kit_generating' AND OLD.status IS DISTINCT FROM NEW.status
     AND OLD.status NOT IN ('framework_approved','kit_review','kit_updating') THEN
    RAISE EXCEPTION 'GATE_NOT_PASSED: генерация комплекта до утверждения каркаса запрещена'
    USING ERRCODE = 'check_violation';
  END IF;
  NEW.updated_at := now();
  NEW.lock_version := OLD.lock_version + 1;
  RETURN NEW;
END $$;

CREATE TRIGGER program_gate BEFORE UPDATE ON program FOR EACH ROW EXECUTE FUNCTION trg_program_gate();

-- Изменение часов/структуры после утверждения возвращает программу в framework_review
CREATE OR REPLACE FUNCTION trg_reopen_on_hours() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_prog uuid;
BEGIN
  SELECT t.program_id INTO v_prog FROM topic t WHERE t.id = coalesce(NEW.topic_id, OLD.topic_id);
  UPDATE program SET status = 'framework_review', approved_at = NULL, approved_by = NULL
  WHERE id = v_prog AND status IN ('framework_approved','kit_review');
  RETURN NULL;
END $$;

CREATE TRIGGER workload_reopen AFTER INSERT OR UPDATE OR DELETE ON topic_workload
FOR EACH ROW WHEN (current_setting('karkas.solver', true) IS DISTINCT FROM 'on')
EXECUTE FUNCTION trg_reopen_on_hours();

-- Снимки версий неизменяемы
CREATE OR REPLACE FUNCTION trg_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'program_version is append-only'; END $$;

CREATE TRIGGER program_version_ro BEFORE UPDATE OR DELETE ON program_version
FOR EACH ROW WHEN (current_setting('karkas.retention', true) IS DISTINCT FROM 'on')
EXECUTE FUNCTION trg_immutable();

-- ---------- Секции llm_call / audit_log ----------------------------------
CREATE TABLE llm_call_2026_10 PARTITION OF llm_call FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE llm_call_2026_11 PARTITION OF llm_call FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE llm_call_default PARTITION OF llm_call DEFAULT;
CREATE TABLE audit_log_2026_10 PARTITION OF audit_log FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');
CREATE TABLE audit_log_2026_11 PARTITION OF audit_log FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;
CREATE INDEX llm_call_program_idx ON llm_call (program_id, created_at);
CREATE INDEX llm_call_org_idx ON llm_call (org_id, created_at);
CREATE INDEX audit_program_idx ON audit_log (program_id, created_at);

-- Сводка затрат по программе (для экрана «Эффект» и защиты)
CREATE VIEW v_program_usage AS
SELECT program_id, count(*) AS calls,
       sum(prompt_tokens) AS prompt_tokens, sum(completion_tokens) AS completion_tokens,
       sum(cost_rub) AS cost_rub,
       round(100.0 * avg(cache_hit::int), 1) AS cache_hit_pct,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms
FROM llm_call GROUP BY program_id;
