PRAGMA foreign_keys = ON;

CREATE TABLE employers (
  user_id TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  company_name TEXT,
  website_url TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE employer_jobs (
  id TEXT PRIMARY KEY,
  employer_user_id TEXT NOT NULL REFERENCES employers(user_id),
  title TEXT NOT NULL,
  company_name TEXT NOT NULL,
  description TEXT NOT NULL,
  apply_url TEXT NOT NULL,
  location TEXT NOT NULL,
  country_code TEXT,
  work_mode TEXT NOT NULL DEFAULT 'on-site' CHECK (work_mode IN ('remote', 'hybrid', 'on-site')),
  employment_type TEXT NOT NULL DEFAULT 'full-time',
  salary_min INTEGER,
  salary_max INTEGER,
  salary_currency TEXT,
  package_code TEXT,
  is_featured INTEGER NOT NULL DEFAULT 0 CHECK (is_featured IN (0, 1)),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'awaiting_payment', 'pending_review', 'published', 'rejected', 'expired', 'withdrawn')),
  published_at TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE payments (
  id TEXT PRIMARY KEY,
  employer_job_id TEXT NOT NULL REFERENCES employer_jobs(id),
  employer_user_id TEXT NOT NULL REFERENCES employers(user_id),
  provider TEXT NOT NULL CHECK (provider IN ('stripe')),
  provider_session_id TEXT UNIQUE,
  checkout_url TEXT,
  checkout_expires_at TEXT,
  provider_payment_id TEXT,
  idempotency_key TEXT NOT NULL UNIQUE,
  package_code TEXT NOT NULL,
  amount_minor INTEGER CHECK (amount_minor IS NULL OR amount_minor > 0),
  currency TEXT,
  status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'checkout_open', 'paid', 'failed', 'refunded')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE payment_webhook_events (
  provider_event_id TEXT PRIMARY KEY,
  received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE ingest_sources (
  source_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  label TEXT NOT NULL,
  country_code TEXT,
  permission_basis TEXT NOT NULL,
  terms_url TEXT,
  enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
  last_success_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE imported_jobs (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES ingest_sources(source_id),
  source_job_id TEXT NOT NULL,
  title TEXT NOT NULL,
  company_name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL,
  apply_url TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '',
  country_code TEXT,
  work_mode TEXT NOT NULL DEFAULT 'on-site',
  employment_type TEXT NOT NULL DEFAULT 'full-time',
  salary_min INTEGER,
  salary_max INTEGER,
  salary_currency TEXT,
  ai_signals TEXT NOT NULL DEFAULT '[]',
  source_updated_at TEXT,
  first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  status TEXT NOT NULL DEFAULT 'published' CHECK (status IN ('published', 'expired', 'removed', 'needs_review')),
  UNIQUE (source_id, source_job_id)
);

CREATE TABLE moderation_events (
  id TEXT PRIMARY KEY,
  employer_job_id TEXT NOT NULL REFERENCES employer_jobs(id),
  moderator_user_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('approve', 'reject', 'withdraw', 'expire')),
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX employer_jobs_owner_created ON employer_jobs(employer_user_id, created_at DESC);
CREATE INDEX employer_jobs_publication ON employer_jobs(status, published_at DESC);
CREATE INDEX imported_jobs_freshness ON imported_jobs(status, last_seen_at DESC);
CREATE INDEX imported_jobs_country_mode ON imported_jobs(country_code, work_mode);
CREATE INDEX payments_owner_created ON payments(employer_user_id, created_at DESC);
