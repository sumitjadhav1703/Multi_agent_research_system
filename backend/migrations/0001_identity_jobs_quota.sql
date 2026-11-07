CREATE TABLE IF NOT EXISTS guest_identities (
    id VARCHAR(64) PRIMARY KEY,
    created_at VARCHAR(40) NOT NULL,
    expires_at VARCHAR(40),
    turnstile_verified INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS demo_entitlements (
    identity_id VARCHAR(64) PRIMARY KEY,
    status VARCHAR(16) NOT NULL,
    job_id VARCHAR(36),
    consumed_at VARCHAR(40),
    refunded_at VARCHAR(40),
    refund_reason VARCHAR(120),
    FOREIGN KEY (identity_id) REFERENCES guest_identities (id)
);

CREATE TABLE IF NOT EXISTS quota_guard (
    id INTEGER PRIMARY KEY,
    daily_window VARCHAR(10) NOT NULL,
    daily_count INTEGER NOT NULL
);

INSERT INTO quota_guard (id, daily_window, daily_count)
SELECT 1, '', 0
WHERE NOT EXISTS (SELECT 1 FROM quota_guard WHERE id = 1);

CREATE TABLE IF NOT EXISTS research_jobs (
    id VARCHAR(36) PRIMARY KEY,
    owner_id VARCHAR(64) NOT NULL,
    topic VARCHAR(500) NOT NULL,
    status VARCHAR(32) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    thread_id VARCHAR(36) NOT NULL,
    lease_owner VARCHAR(80),
    lease_expires_at VARCHAR(40),
    heartbeat_at VARCHAR(40),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at VARCHAR(40),
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    provider_work_started INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(80),
    error_detail VARCHAR(300),
    approval_status VARCHAR(40),
    stop_reason VARCHAR(80),
    resume_action VARCHAR(16),
    resume_comments VARCHAR(2000),
    config_version VARCHAR(40) NOT NULL,
    budget_json TEXT NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL,
    started_at VARCHAR(40),
    finished_at VARCHAR(40),
    FOREIGN KEY (owner_id) REFERENCES guest_identities (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_research_jobs_owner_idempotency
    ON research_jobs (owner_id, idempotency_key);

CREATE INDEX IF NOT EXISTS ix_research_jobs_owner_created
    ON research_jobs (owner_id, created_at);

CREATE INDEX IF NOT EXISTS ix_research_jobs_status_lease
    ON research_jobs (status, lease_expires_at);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id VARCHAR(36) PRIMARY KEY,
    identity_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    job_id VARCHAR(36) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    FOREIGN KEY (identity_id) REFERENCES guest_identities (id),
    FOREIGN KEY (job_id) REFERENCES research_jobs (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_idempotency_identity_key
    ON idempotency_keys (identity_id, idempotency_key);

CREATE TABLE IF NOT EXISTS job_events (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    sequence_id INTEGER NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    payload TEXT NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    FOREIGN KEY (job_id) REFERENCES research_jobs (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_job_events_sequence
    ON job_events (job_id, sequence_id);

CREATE INDEX IF NOT EXISTS ix_job_events_run_seq
    ON job_events (job_id, sequence_id);

CREATE TABLE IF NOT EXISTS research_sources (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    source_key VARCHAR(80) NOT NULL,
    canonical_url VARCHAR(1000) NOT NULL,
    url VARCHAR(1000) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    title VARCHAR(300) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    extraction_method VARCHAR(40) NOT NULL,
    retrieved_at VARCHAR(40),
    excerpt TEXT,
    FOREIGN KEY (job_id) REFERENCES research_jobs (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sources_job_key
    ON research_sources (job_id, source_key);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sources_job_url
    ON research_sources (job_id, canonical_url);

CREATE INDEX IF NOT EXISTS ix_sources_job_url
    ON research_sources (job_id, canonical_url);

CREATE TABLE IF NOT EXISTS evidence_passages (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    evidence_key VARCHAR(80) NOT NULL,
    source_key VARCHAR(80) NOT NULL,
    subquestion_id VARCHAR(80),
    quote TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES research_jobs (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_passages_job_key
    ON evidence_passages (job_id, evidence_key);

CREATE TABLE IF NOT EXISTS research_claims (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    claim_key VARCHAR(80) NOT NULL,
    claim_text TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    verification_reason TEXT,
    evidence_ids_json TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES research_jobs (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_claims_job_key
    ON research_claims (job_id, claim_key);

CREATE TABLE IF NOT EXISTS research_reports (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    version INTEGER NOT NULL,
    markdown TEXT NOT NULL,
    approval_state VARCHAR(40) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    FOREIGN KEY (job_id) REFERENCES research_jobs (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_reports_job_version
    ON research_reports (job_id, version);

CREATE TABLE IF NOT EXISTS usage_ledger (
    id VARCHAR(36) PRIMARY KEY,
    job_id VARCHAR(36) NOT NULL,
    identity_id VARCHAR(64) NOT NULL,
    provider VARCHAR(80),
    model VARCHAR(160),
    llm_calls INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    estimated_cost_usd VARCHAR(32),
    search_calls INTEGER,
    created_at VARCHAR(40) NOT NULL,
    FOREIGN KEY (job_id) REFERENCES research_jobs (id)
);

CREATE INDEX IF NOT EXISTS ix_usage_ledger_job
    ON usage_ledger (job_id);
