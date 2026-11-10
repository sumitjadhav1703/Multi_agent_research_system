-- usage_ledger is read by identity_id (usage_snapshot); it had no index.
CREATE INDEX IF NOT EXISTS ix_usage_ledger_identity
    ON usage_ledger (identity_id);

-- Exact duplicates of the unique indexes uq_job_events_sequence / uq_sources_job_url.
DROP INDEX IF EXISTS ix_job_events_run_seq;

DROP INDEX IF EXISTS ix_sources_job_url;
