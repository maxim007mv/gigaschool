-- КАРКАС · SQLite lite (демо без PostgreSQL). Триггеры Human Gate — в API/домене.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    sha256 BLOB NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS organization (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    requisites TEXT NOT NULL DEFAULT '{}',
    settings TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_user (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'methodist',
    password_hash TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (org_id, email)
);

CREATE TABLE IF NOT EXISTS program (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL REFERENCES app_user(id),
    title TEXT NOT NULL DEFAULT 'Новая программа',
    kind TEXT,
    form TEXT,
    total_hours INTEGER,
    final_att_hours INTEGER NOT NULL DEFAULT 0,
    final_att_form TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    profile TEXT NOT NULL DEFAULT '{}',
    constraints TEXT NOT NULL DEFAULT '{}',
    goal TEXT,
    current_version INTEGER NOT NULL DEFAULT 0,
    approved_by TEXT,
    approved_at TEXT,
    parent_id TEXT,
    lock_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS program_version (
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    reason TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    snapshot_hash BLOB NOT NULL,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (program_id, version)
);

CREATE TABLE IF NOT EXISTS clarification (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    slot TEXT NOT NULL,
    question TEXT NOT NULL,
    options TEXT NOT NULL DEFAULT '[]',
    answer TEXT,
    answered_by TEXT,
    is_default INTEGER NOT NULL DEFAULT 0,
    ord INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at TEXT,
    UNIQUE (program_id, ord)
);

CREATE TABLE IF NOT EXISTS competency (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    title TEXT NOT NULL,
    activity_kind TEXT,
    labor_function_id TEXT,
    ord INTEGER NOT NULL,
    UNIQUE (program_id, ref)
);

CREATE TABLE IF NOT EXISTS learning_outcome (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    competency_id TEXT NOT NULL REFERENCES competency(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    type TEXT NOT NULL,
    text TEXT NOT NULL,
    bloom_level INTEGER,
    ord INTEGER NOT NULL,
    UNIQUE (program_id, ref)
);

CREATE TABLE IF NOT EXISTS module (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1,
    att_form TEXT,
    UNIQUE (program_id, ref)
);

CREATE TABLE IF NOT EXISTS topic (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    module_id TEXT NOT NULL REFERENCES module(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    weight REAL NOT NULL DEFAULT 1,
    practicality REAL NOT NULL DEFAULT 0.5,
    complexity INTEGER NOT NULL DEFAULT 1,
    control_form TEXT,
    UNIQUE (program_id, ref)
);

CREATE TABLE IF NOT EXISTS topic_workload (
    topic_id TEXT NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    activity TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'in_person',
    hours INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (topic_id, activity, mode)
);

CREATE TABLE IF NOT EXISTS topic_outcome (
    topic_id TEXT NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    outcome_id TEXT NOT NULL REFERENCES learning_outcome(id) ON DELETE CASCADE,
    PRIMARY KEY (topic_id, outcome_id)
);

CREATE TABLE IF NOT EXISTS calendar_session (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    week_no INTEGER NOT NULL,
    day_no INTEGER NOT NULL,
    topic_id TEXT,
    activity TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'in_person',
    hours INTEGER NOT NULL,
    UNIQUE (program_id, seq)
);

CREATE TABLE IF NOT EXISTS assessment_item (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    topic_id TEXT,
    module_id TEXT,
    stem TEXT NOT NULL,
    qtype TEXT,
    options TEXT,
    answer_key TEXT,
    rubric TEXT,
    difficulty INTEGER,
    content_hash BLOB NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,
    UNIQUE (program_id, ref)
);

CREATE TABLE IF NOT EXISTS assessment_outcome (
    item_id TEXT NOT NULL REFERENCES assessment_item(id) ON DELETE CASCADE,
    outcome_id TEXT NOT NULL REFERENCES learning_outcome(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, outcome_id)
);

CREATE TABLE IF NOT EXISTS content_block (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    module_id TEXT,
    topic_id TEXT,
    body TEXT NOT NULL,
    stale INTEGER NOT NULL DEFAULT 0,
    generated_by TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (program_id, ref)
);

CREATE TABLE IF NOT EXISTS source (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    section TEXT NOT NULL,
    citation TEXT NOT NULL,
    url TEXT,
    isbn TEXT,
    normative_act_id TEXT,
    status TEXT NOT NULL DEFAULT 'unverified',
    evidence TEXT NOT NULL DEFAULT '{}',
    checked_at TEXT,
    UNIQUE (program_id, ref)
);

CREATE TABLE IF NOT EXISTS validation_run (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    scope TEXT NOT NULL,
    passed INTEGER NOT NULL,
    summary TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS validation_issue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES validation_run(id) ON DELETE CASCADE,
    rule_code TEXT NOT NULL,
    severity TEXT NOT NULL,
    entity_ref TEXT,
    message TEXT NOT NULL,
    fix_hint TEXT
);

CREATE TABLE IF NOT EXISTS job (
    id TEXT PRIMARY KEY,
    program_id TEXT REFERENCES program(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 5,
    payload TEXT NOT NULL DEFAULT '{}',
    progress TEXT NOT NULL DEFAULT '{}',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_after TEXT NOT NULL DEFAULT (datetime('now')),
    locked_by TEXT,
    locked_at TEXT,
    error TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_run (
    id TEXT PRIMARY KEY,
    api_key_id TEXT,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    request TEXT NOT NULL,
    result TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS llm_call (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    org_id TEXT NOT NULL,
    program_id TEXT,
    job_id TEXT,
    skill TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    cost_rub REAL NOT NULL DEFAULT 0,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_cache (
    key_hash BLOB PRIMARY KEY,
    model TEXT NOT NULL,
    response TEXT NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    org_id TEXT NOT NULL,
    actor_id TEXT,
    program_id TEXT,
    action TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS normative_act (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    issuer TEXT NOT NULL,
    number TEXT NOT NULL,
    signed_on TEXT NOT NULL,
    title TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    applies_to TEXT NOT NULL DEFAULT 'dpp_pk,dop',
    verified_by TEXT NOT NULL,
    verified_on TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prof_standard (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    reg_number TEXT,
    title TEXT NOT NULL,
    order_number TEXT,
    order_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS labor_function (
    id TEXT PRIMARY KEY,
    prof_standard_id TEXT NOT NULL REFERENCES prof_standard(id) ON DELETE CASCADE,
    otf_code TEXT NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    qual_level INTEGER,
    actions TEXT NOT NULL DEFAULT '[]',
    skills TEXT NOT NULL DEFAULT '[]',
    knowledge TEXT NOT NULL DEFAULT '[]',
    UNIQUE (prof_standard_id, code)
);

CREATE TABLE IF NOT EXISTS service_catalog (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    available_ru INTEGER,
    lifecycle TEXT NOT NULL DEFAULT 'current',
    latest_version TEXT,
    checked_on TEXT NOT NULL,
    evidence_url TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS file_object (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,
    uploaded_by TEXT,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 BLOB NOT NULL,
    s3_key TEXT NOT NULL,
    extracted_text TEXT,
    extract_meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS edit_request (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    author_id TEXT NOT NULL REFERENCES app_user(id),
    target_ref TEXT NOT NULL,
    instruction TEXT NOT NULL,
    affected_refs TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'planned',
    base_version INTEGER NOT NULL,
    result_version INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS artifact (
    id TEXT PRIMARY KEY,
    program_id TEXT NOT NULL REFERENCES program(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
