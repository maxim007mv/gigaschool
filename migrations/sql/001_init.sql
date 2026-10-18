-- =====================================================================
-- КАРКАС · миграция 001_init · PostgreSQL 16 + pgvector 0.7+
-- Единственный источник истины по часам — topic_workload (листовой уровень).
-- Итоги модулей и программы НЕ хранятся, а вычисляются (v_module_hours, v_program_hours).
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector: эмбеддинги RAG
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- нечёткий поиск по реестрам

-- ---------- Перечисления -------------------------------------------------
CREATE TYPE program_kind AS ENUM ('dpp_pk', 'dop');  -- ДПП повышения квалификации / доп. общеразвивающая
CREATE TYPE program_form AS ENUM ('full_time', 'part_time', 'distance', 'internship');
CREATE TYPE program_status AS ENUM ('draft','clarifying','framework_generating','framework_review',
                                    'framework_approved','kit_generating','kit_review','kit_updating',
                                    'archived','failed');
CREATE TYPE outcome_type AS ENUM ('knowledge','skill','experience');  -- Знания / Умения / Навыки (практический опыт)
CREATE TYPE activity_type AS ENUM ('lecture','practice','lab','self_study','current_control');
CREATE TYPE delivery_mode AS ENUM ('in_person','distance');
CREATE TYPE assessment_kind AS ENUM ('test_question','seminar_task','interview_question',
                                     'final_project','exam_task','portfolio_item');
CREATE TYPE verify_status AS ENUM ('verified','unverified','not_found','outdated');
CREATE TYPE job_status AS ENUM ('queued','running','retry_wait','succeeded','failed','cancelled');
CREATE TYPE issue_severity AS ENUM ('error','warning','info');
CREATE TYPE user_role AS ENUM ('methodist','expert','head','admin','service');
CREATE TYPE artifact_kind AS ENUM ('program_docx','slides_pptx','tests_gift','tests_moodle_xml',
                                   'tests_csv','kit_json','report_docx','source_file');

-- ---------- Организации и пользователи ----------------------------------
CREATE TABLE organization (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    requisites jsonb NOT NULL DEFAULT '{}'::jsonb,  -- шапка титульного листа (ОГРН, адрес) — заполняет админ
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,    -- лимиты, модели по умолчанию
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_user (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    email text NOT NULL CHECK (email ~* '^[^@\s]+@[^@\s]+$'),
    display_name text NOT NULL,
    role user_role NOT NULL DEFAULT 'methodist',
    password_hash text,  -- NULL при входе через SSO
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, email)
);

CREATE TABLE api_key (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    name text NOT NULL,
    key_hash bytea NOT NULL UNIQUE,  -- sha256(ключ); сам ключ не хранится
    scopes text[] NOT NULL DEFAULT '{agent:run}',
    rate_per_min int NOT NULL DEFAULT 30 CHECK (rate_per_min > 0),
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- ---------- Файлы и база знаний (RAG) -----------------------------------
CREATE TABLE file_object (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    uploaded_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
    filename text NOT NULL,
    mime_type text NOT NULL CHECK (mime_type IN (
        'application/pdf','text/plain','text/markdown',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
    size_bytes bigint NOT NULL CHECK (size_bytes BETWEEN 1 AND 52428800),  -- ≤ 50 МБ
    sha256 bytea NOT NULL,
    s3_key text NOT NULL,
    extracted_text text,  -- результат ingest; TOAST сжимает
    extract_meta jsonb NOT NULL DEFAULT '{}'::jsonb,  -- страницы, таблицы, заголовки
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, sha256)  -- дедупликация повторных загрузок
);

CREATE TABLE kb_document (  -- база знаний организации (локальные акты, шаблоны)
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    file_id uuid NOT NULL REFERENCES file_object(id) ON DELETE CASCADE,
    title text NOT NULL,
    doc_role text NOT NULL CHECK (doc_role IN ('template','sample_program','local_act','prof_standard','fgos','other')),
    applies_to program_kind[],  -- NULL = ко всем видам программ
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE kb_chunk (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id uuid NOT NULL,
    file_id uuid NOT NULL REFERENCES file_object(id) ON DELETE CASCADE,
    ord int NOT NULL,
    heading_path text,  -- «2. Содержание › 2.1 Учебный план»
    content text NOT NULL,
    tokens int NOT NULL,
    embedding vector(1024) NOT NULL,  -- Qwen3-Embedding-0.6B (Допущение: размерность 1024)
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', content)) STORED,
    UNIQUE (file_id, ord)
);

-- ---------- Справочники-реестры (защита от выдуманных источников) -------
CREATE TABLE normative_act (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind text NOT NULL CHECK (kind IN ('federal_law','order','letter','gost','other')),
    issuer text NOT NULL,     -- «Минобрнауки России»
    number text NOT NULL,     -- «499», «273-ФЗ»
    signed_on date NOT NULL,
    title text NOT NULL,
    valid_from date,
    valid_to date,            -- NULL = действует
    replaced_by uuid REFERENCES normative_act(id),
    official_url text,
    applies_to program_kind[] NOT NULL DEFAULT '{dpp_pk,dop}',
    verified_by text NOT NULL,  -- кто и по какому источнику сверил запись
    verified_on date NOT NULL,
    UNIQUE (issuer, number, signed_on)
);

CREATE TABLE prof_standard (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE CHECK (code ~ '^\d{2}\.\d{3}$'),  -- «06.015»
    reg_number text,
    title text NOT NULL,
    order_number text,  -- «586н»
    order_date date,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','replaced','cancelled')),
    source text NOT NULL,  -- 'mintrud_xlsx:2026-10-01'
    imported_at timestamptz NOT NULL DEFAULT now(),
    title_trgm text GENERATED ALWAYS AS (lower(title)) STORED
);

CREATE TABLE labor_function (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    prof_standard_id uuid NOT NULL REFERENCES prof_standard(id) ON DELETE CASCADE,
    otf_code text NOT NULL,   -- обобщённая ТФ: «C»
    code text NOT NULL,       -- ТФ: «C/14.6»
    title text NOT NULL,
    qual_level smallint CHECK (qual_level BETWEEN 1 AND 9),
    actions text[] NOT NULL DEFAULT '{}',    -- трудовые действия
    skills text[] NOT NULL DEFAULT '{}',     -- необходимые умения
    knowledge text[] NOT NULL DEFAULT '{}',  -- необходимые знания
    UNIQUE (prof_standard_id, code)
);

CREATE TABLE service_catalog (  -- сервисы/инструменты: доступность в РФ, актуальность
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    category text NOT NULL,  -- 'ai_service','library','tool','platform'
    available_ru boolean,    -- NULL = не установлено → предупреждение
    lifecycle text NOT NULL DEFAULT 'current' CHECK (lifecycle IN ('current','deprecated','eol','unknown')),
    latest_version text,
    checked_on date NOT NULL,
    evidence_url text,
    note text
);

-- ---------- Программа и её версии ---------------------------------------
CREATE TABLE program (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    owner_id uuid NOT NULL REFERENCES app_user(id),
    title text NOT NULL DEFAULT 'Новая программа',
    kind program_kind,       -- NULL до выбора шаблона
    form program_form,
    total_hours smallint CHECK (total_hours BETWEEN 1 AND 2000),
    final_att_hours smallint NOT NULL DEFAULT 0 CHECK (final_att_hours >= 0),
    final_att_form text,
    status program_status NOT NULL DEFAULT 'draft',
    profile jsonb NOT NULL DEFAULT '{}'::jsonb,      -- JSON-профиль брифа (S01): аудитория, уровень, срок …
    constraints jsonb NOT NULL DEFAULT '{}'::jsonb,  -- доля практики, только СРС, ч/день, кратность …
    goal text,
    current_version int NOT NULL DEFAULT 0,
    approved_by uuid REFERENCES app_user(id),
    approved_at timestamptz,
    parent_id uuid REFERENCES program(id) ON DELETE SET NULL,  -- источник адаптации/актуализации
    lock_version int NOT NULL DEFAULT 0,  -- оптимистическая блокировка (If-Match)
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (final_att_hours < coalesce(total_hours, 32767)),
    CHECK (status NOT IN ('framework_approved','kit_generating','kit_review','kit_updating')
           OR (approved_at IS NOT NULL AND kind IS NOT NULL AND total_hours IS NOT NULL))
);

CREATE TABLE program_version (  -- неизменяемые снимки (Human Gate, генерация, каждая правка)
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    version int NOT NULL,
    reason text NOT NULL,        -- 'framework_generated','framework_approved','edit:…'
    snapshot jsonb NOT NULL,     -- KitV1 целиком
    snapshot_hash bytea NOT NULL,
    created_by uuid REFERENCES app_user(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (program_id, version)
);

CREATE TABLE program_file (  -- референсы, приложенные к запросу
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    file_id uuid NOT NULL REFERENCES file_object(id) ON DELETE RESTRICT,
    role text NOT NULL CHECK (role IN ('template','sample_program','prof_standard','reference','old_program')),
    analysis jsonb NOT NULL DEFAULT '{}'::jsonb,  -- найденная структура, ошибки образца (S04)
    PRIMARY KEY (program_id, file_id)
);

CREATE TABLE clarification (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    slot text NOT NULL CHECK (slot IN ('kind','total_hours','audience','entry_level','form',
                                       'final_attestation','schedule','other')),
    question text NOT NULL,
    options jsonb NOT NULL DEFAULT '[]'::jsonb,  -- варианты-кнопки
    answer text,
    answered_by uuid REFERENCES app_user(id),
    is_default boolean NOT NULL DEFAULT false,  -- «на ваше усмотрение» → принято значение по умолчанию
    ord smallint NOT NULL CHECK (ord BETWEEN 1 AND 5),  -- не более 5 вопросов
    created_at timestamptz NOT NULL DEFAULT now(),
    answered_at timestamptz,
    UNIQUE (program_id, ord)
);

-- ---------- Каркас: компетенции, модули, темы, часы ---------------------
CREATE TABLE competency (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref text NOT NULL CHECK (ref ~ '^C\d{1,2}$'),  -- C1, C2 …
    title text NOT NULL,
    activity_kind text,  -- «вид деятельности» шаблона ДПП
    labor_function_id uuid REFERENCES labor_function(id),  -- обязателен для dpp_pk (проверяет V-PST)
    ord smallint NOT NULL,
    UNIQUE (program_id, ref)
);

CREATE TABLE learning_outcome (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    competency_id uuid NOT NULL REFERENCES competency(id) ON DELETE CASCADE,
    ref text NOT NULL CHECK (ref ~ '^LO\d{1,2}\.\d{1,2}$'),  -- LO1.2
    type outcome_type NOT NULL,
    text text NOT NULL,
    bloom_level smallint CHECK (bloom_level BETWEEN 1 AND 6),
    ord smallint NOT NULL,
    UNIQUE (program_id, ref)
);

CREATE TABLE module (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref text NOT NULL CHECK (ref ~ '^M\d{1,2}$'),
    number smallint NOT NULL CHECK (number > 0),
    title text NOT NULL,
    weight numeric(6,3) NOT NULL DEFAULT 1 CHECK (weight > 0),  -- вес для солвера часов
    att_form text,  -- форма промежуточной аттестации
    UNIQUE (program_id, ref),
    UNIQUE (program_id, number) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE topic (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    module_id uuid NOT NULL REFERENCES module(id) ON DELETE CASCADE,
    ref text NOT NULL CHECK (ref ~ '^T\d{1,2}\.\d{1,2}$'),  -- T2.3
    number smallint NOT NULL CHECK (number > 0),
    title text NOT NULL,
    summary text,
    weight numeric(6,3) NOT NULL DEFAULT 1 CHECK (weight > 0),
    practicality numeric(3,2) NOT NULL DEFAULT 0.5 CHECK (practicality BETWEEN 0 AND 1),
    complexity smallint NOT NULL DEFAULT 1 CHECK (complexity BETWEEN 1 AND 5),  -- для V-SEQ (порядок тем)
    control_form text,
    UNIQUE (program_id, ref),
    UNIQUE (module_id, number) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE topic_workload (  -- ЕДИНСТВЕННОЕ место хранения часов
    topic_id uuid NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    activity activity_type NOT NULL,
    mode delivery_mode NOT NULL DEFAULT 'in_person',
    hours smallint NOT NULL CHECK (hours >= 0 AND hours <= 500),
    PRIMARY KEY (topic_id, activity, mode)
);

CREATE TABLE topic_outcome (  -- «результат обучения раскрыт в теме»
    topic_id uuid NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    outcome_id uuid NOT NULL REFERENCES learning_outcome(id) ON DELETE CASCADE,
    PRIMARY KEY (topic_id, outcome_id)
);

CREATE TABLE calendar_session (  -- календарный учебный график
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    seq smallint NOT NULL CHECK (seq > 0),
    week_no smallint NOT NULL CHECK (week_no > 0),
    day_no smallint NOT NULL CHECK (day_no > 0),  -- относительный день; даты — по комплектованию групп
    topic_id uuid REFERENCES topic(id) ON DELETE CASCADE,  -- NULL = итоговая аттестация
    activity text NOT NULL,
    mode delivery_mode NOT NULL DEFAULT 'in_person',
    hours smallint NOT NULL CHECK (hours BETWEEN 1 AND 12),
    UNIQUE (program_id, seq)
);

-- ---------- Содержание комплекта ----------------------------------------
CREATE TABLE assessment_item (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref text NOT NULL,  -- Q-001, ST-T2.3-1, IQ-M1-03, FA-1
    kind assessment_kind NOT NULL,
    topic_id uuid REFERENCES topic(id) ON DELETE SET NULL,
    module_id uuid REFERENCES module(id) ON DELETE SET NULL,
    stem text NOT NULL,  -- формулировка вопроса/задания
    qtype text CHECK (qtype IN ('single','multiple','truefalse','short','matching','order','open')),
    options jsonb,      -- [{id:'a',text:'…'}]
    answer_key jsonb,   -- {'correct':['b'],'explanation':'…'}
    rubric jsonb,       -- критерии оценки: [{criterion,max_points,levels[]}]
    difficulty smallint CHECK (difficulty BETWEEN 1 AND 5),
    content_hash bytea NOT NULL,  -- поиск дублей между темами
    stale boolean NOT NULL DEFAULT false,  -- помечен к пересборке графом зависимостей
    UNIQUE (program_id, ref),
    CHECK (kind <> 'test_question' OR (qtype IS NOT NULL AND answer_key IS NOT NULL)),
    CHECK (kind NOT IN ('seminar_task','final_project','exam_task','portfolio_item') OR rubric IS NOT NULL)
);

CREATE TABLE assessment_outcome (  -- «оценочное средство проверяет результат»
    item_id uuid NOT NULL REFERENCES assessment_item(id) ON DELETE CASCADE,
    outcome_id uuid NOT NULL REFERENCES learning_outcome(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, outcome_id)
);

CREATE TABLE content_block (  -- рабочие программы модулей, планы лекций, слайды
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref text NOT NULL,  -- MP-M2, LP-T2.3, SL-T2.3, SEC-1.6
    kind text NOT NULL CHECK (kind IN ('module_program','lecture_plan','slides','template_section','annotation')),
    module_id uuid REFERENCES module(id) ON DELETE CASCADE,
    topic_id uuid REFERENCES topic(id) ON DELETE CASCADE,
    body jsonb NOT NULL,  -- структурированный контент (для .docx/.pptx)
    stale boolean NOT NULL DEFAULT false,
    generated_by text,    -- 'S12@qwen3.6-35b'
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (program_id, ref)
);

CREATE TABLE source (  -- литература, НПА, интернет-ресурсы программы
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref text NOT NULL,  -- SRC-01
    section text NOT NULL CHECK (section IN ('normative','main','additional','internet','software')),
    citation text NOT NULL,  -- библиографическое описание (ГОСТ Р 7.0.100)
    url text,
    isbn text,
    normative_act_id uuid REFERENCES normative_act(id),
    status verify_status NOT NULL DEFAULT 'unverified',
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,  -- как проверено: реестр/HTTP 200/ISBN
    checked_at timestamptz,
    UNIQUE (program_id, ref)
);

CREATE TABLE source_usage (
    source_id uuid NOT NULL REFERENCES source(id) ON DELETE CASCADE,
    topic_id uuid NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, topic_id)
);

-- ---------- Проверка, правки, артефакты ---------------------------------
CREATE TABLE validation_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    version int NOT NULL,
    scope text NOT NULL CHECK (scope IN ('framework','kit','sample')),
    passed boolean NOT NULL,
    summary jsonb NOT NULL,  -- {hours:{ok:true}, coverage:{…}, sources:{…}}
    duration_ms int NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE validation_issue (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES validation_run(id) ON DELETE CASCADE,
    rule_code text NOT NULL,   -- V-HRS-03
    severity issue_severity NOT NULL,
    entity_ref text,           -- T2.3 / LO1.2 / SRC-04
    message text NOT NULL,     -- по-русски, без жаргона
    fix_hint jsonb             -- машинно-применимое исправление
);

CREATE TABLE edit_request (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    author_id uuid NOT NULL REFERENCES app_user(id),
    target_ref text NOT NULL,
    instruction text NOT NULL CHECK (length(instruction) BETWEEN 3 AND 2000),
    affected_refs text[] NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','running','applied','rejected','failed')),
    base_version int NOT NULL,
    result_version int,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE artifact (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    version int NOT NULL,
    kind artifact_kind NOT NULL,
    s3_key text NOT NULL,
    size_bytes bigint NOT NULL,
    sha256 bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (program_id, version, kind, s3_key)
);

-- ---------- Очередь задач и запуски агента ------------------------------
CREATE TABLE job (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    program_id uuid REFERENCES program(id) ON DELETE CASCADE,
    kind text NOT NULL,  -- 'intake','framework','kit','edit','export','actualize','adapt'
    status job_status NOT NULL DEFAULT 'queued',
    priority smallint NOT NULL DEFAULT 5,  -- 1 = выше (каркас, демо)
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    progress jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {step:'S07', done:3, total:9}
    attempts smallint NOT NULL DEFAULT 0,
    max_attempts smallint NOT NULL DEFAULT 3,
    run_after timestamptz NOT NULL DEFAULT now(),
    locked_by text,
    locked_at timestamptz,
    error jsonb,
    idempotency_key text,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (idempotency_key)
);

CREATE TABLE agent_run (  -- запуски через единый эндпоинт /api/v1/agent/run
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_id uuid REFERENCES api_key(id),
    program_id uuid NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    mode text NOT NULL CHECK (mode IN ('framework','full')),
    status text NOT NULL CHECK (status IN ('running','needs_input','completed','failed')),
    request jsonb NOT NULL,
    result jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

-- ---------- Учёт токенов и аудит (секционированы по месяцам) ------------
CREATE TABLE llm_call (
    id bigint GENERATED ALWAYS AS IDENTITY,
    created_at timestamptz NOT NULL DEFAULT now(),
    org_id uuid NOT NULL,
    program_id uuid,
    job_id uuid,
    skill text NOT NULL,  -- 'S06'
    model text NOT NULL,
    prompt_tokens int NOT NULL CHECK (prompt_tokens >= 0),
    completion_tokens int NOT NULL CHECK (completion_tokens >= 0),
    latency_ms int NOT NULL,
    cost_rub numeric(12,4) NOT NULL DEFAULT 0,  -- по тарифной таблице организации
    cache_hit boolean NOT NULL DEFAULT false,
    ok boolean NOT NULL,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE llm_cache (
    key_hash bytea PRIMARY KEY,  -- sha256(model|prompt_version|messages|params)
    model text NOT NULL,
    response jsonb NOT NULL,
    hits int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY,
    created_at timestamptz NOT NULL DEFAULT now(),
    org_id uuid NOT NULL,
    actor_id uuid,
    program_id uuid,
    action text NOT NULL,  -- 'framework.approve','edit.apply','export.create'
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
