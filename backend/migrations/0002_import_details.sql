-- Additive/idempotent metadata for aggregate feeds. Apply alongside 0001.
CREATE TABLE IF NOT EXISTS imported_job_details (
  job_id TEXT PRIMARY KEY REFERENCES imported_jobs(id),
  expires_at TEXT,
  salary_period TEXT,
  allow_syndication INTEGER NOT NULL DEFAULT 0 CHECK (allow_syndication IN (0,1))
);
CREATE TABLE IF NOT EXISTS ingest_provider_schedule (
  provider TEXT PRIMARY KEY,
  last_attempt_at TEXT NOT NULL
);
