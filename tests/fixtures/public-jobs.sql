INSERT INTO employers(user_id,email) VALUES('owner','owner@example.test');
INSERT INTO employer_jobs(id,employer_user_id,title,company_name,description,apply_url,location,country_code,work_mode,employment_type,salary_min,salary_max,salary_currency,status,expires_at,published_at,is_featured) VALUES
('sweden','owner','AI Engineer 100%','Example AB','Build AI systems with Python.','https://example.test/sweden','Stockholm','SE','remote','full-time',800000,900000,'SEK','published','2099-01-01','2026-01-02T00:00:00Z',0),
('usa','owner','AI Researcher','Example Inc','Train machine learning models.','https://example.test/usa','Boston','US','hybrid','contract',150000,200000,'USD','published','2099-01-01','2026-01-01T00:00:00Z',1),
('draft','owner','Private draft','Private Ltd','This must stay hidden.','https://example.test/draft','Paris','FR','remote','internship',1,2,'EUR','draft','2099-01-01','2026-01-03T00:00:00Z',0),
('expired','owner','Expired role','Old Ltd','This must stay hidden.','https://example.test/expired','Oslo','NO','remote','part-time',1,2,'NOK','published','2000-01-01','2026-01-03T00:00:00Z',0);
INSERT INTO ingest_sources(source_id,provider,label,permission_basis,enabled) VALUES
('permitted','lever','Original career board','Fixture permission',1),
('unlicensed','lever','No reuse permission','   ',1);
INSERT INTO imported_jobs(id,source_id,source_job_id,title,company_name,description,source_url,apply_url,location,country_code,work_mode,employment_type,salary_min,salary_currency,ai_signals,status,first_seen_at,last_seen_at) VALUES
('imported','permitted','1','AI Developer_under_score','Original GmbH','Use Claude Code and review generated code.','https://example.test/source','https://example.test/apply','Berlin','DE','on-site','full-time',80000,'EUR','["claude code"]','published','2026-01-03T00:00:00Z',strftime('%Y-%m-%dT%H:%M:%fZ','now')),
('stale','permitted','2','Stale AI job','Old Co','Hidden','https://example.test/stale','https://example.test/stale','Tokyo','JP','remote','part-time',1000,'JPY','[]','published','2026-01-03T00:00:00Z','2000-01-01'),
('pending','permitted','3','Pending AI job','New Co','Hidden','https://example.test/pending','https://example.test/pending','Dublin','IE','remote','internship',1000,'EUR','[]','needs_review','2026-01-03T00:00:00Z',strftime('%Y-%m-%dT%H:%M:%fZ','now')),
('unlicensed','unlicensed','4','Unlicensed AI job','Unknown','Hidden','https://example.test/unlicensed','https://example.test/unlicensed','London','GB','remote','freelance',1000,'GBP','[]','published','2026-01-03T00:00:00Z',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
