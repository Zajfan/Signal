"""Scheduling and feed metadata behavior against real SQLite queries."""
import tempfile
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock
from ingestion import run_once, review_import, validate_sources
from local_server import connect
from search import search_jobs
import scraper


def source(identity='example', **changes):
    return dict(source_id=identity, ats='jobtech', label='Example', enabled=True,
                auto_publish=True, permission_basis='Fixture permission', **changes)


def job(**changes):
    return dict(id='example:1', title='AI engineer', company='Example',
                url='https://example.test/jobs/1', ai_explicit=True,
                salary_min=60, salary_currency='USD', salary_period='hourly', **changes)


class ExpansionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/'test.sqlite3'

    def test_query_independent_feed_id_preserves_existing_job_and_takedown(self):
        config = [dict(source(), ats='jobicy')]
        raw = dict(id=321, jobTitle='AI engineer', companyName='Acme', jobType=['Full-Time'],
                   jobDescription='Build machine learning systems', url='https://jobicy.com/jobs/321-ai-engineer')
        row = scraper.normalize('jobicy', 'Jobicy', 'machine learning', raw)
        legacy = dict(row, id='jobicy:example:321')
        self.assertEqual(run_once(self.db, config, lambda _: [legacy])['inserted'], 1)
        with connect(self.db) as db:
            identity = db.execute('SELECT id FROM imported_jobs').fetchone()[0]
            db.execute("UPDATE imported_jobs SET status='removed' WHERE id=?", (identity,))
        row = scraper.normalize('jobicy', 'Jobicy', 'machine learning',
                                dict(raw, url='https://jobicy.com/jobs/321-updated-ai-engineer'))
        result = run_once(self.db, config, lambda _: [row])
        self.assertEqual((result['inserted'], result['updated']), (0, 1))
        changed = scraper.normalize('jobicy', 'Jobicy', 'another search',
                                    dict(raw, url='https://jobicy.com/jobs/321-senior-ai-engineer'))
        result = run_once(self.db, config, lambda _: [changed])
        self.assertEqual((result['inserted'], result['updated']), (0, 1))
        with connect(self.db) as db:
            records = db.execute('SELECT id,status,source_job_id FROM imported_jobs').fetchall()
        self.assertEqual([tuple(r) for r in records], [(identity, 'removed', 'jobicy:public:321')])

    def test_source_cadence_survives_restart_and_failed_attempt(self):
        config = [source(refresh_interval_seconds=3600)]
        fetch = Mock(side_effect=OSError('offline'))
        self.assertEqual(run_once(self.db, config, fetch)['errors'], 1)
        skipped = run_once(self.db, config, fetch)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(skipped['sources'][0]['deferred'], 'refresh_interval')
        with connect(self.db) as db:
            db.execute("UPDATE ingest_run_metadata SET last_attempt_at=datetime('now','-2 hours')")
        fetch.side_effect = None; fetch.return_value = [job()]
        self.assertEqual(run_once(self.db, config, fetch)['inserted'], 1)

    def test_remotive_budget_is_shared_across_queries_and_restarts(self):
        configs = [source('r1') | {'ats':'remotive'}, source('r2') | {'ats':'remotive', 'query':'AI'}]
        fetch = Mock(return_value=[])
        result = run_once(self.db, configs, fetch)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result['sources'][1]['deferred'], 'provider_interval')
        run_once(self.db, configs, fetch)
        self.assertEqual(fetch.call_count, 1)
        with connect(self.db) as db:
            db.execute("UPDATE ingest_provider_schedule SET last_attempt_at=datetime('now','-7 hours')")
        run_once(self.db, configs, fetch)
        self.assertEqual(fetch.call_args.args[0]['source_id'], 'r2')

    def test_legacy_approval_survives_unchanged_metadata_upgrade(self):
        from ingestion import COLUMNS, canonical_url
        run_once(self.db, [source()], lambda _: [job() | {'salary_period':None}])
        with connect(self.db) as db:
            row = db.execute('SELECT * FROM imported_jobs').fetchone()
            old = {key:row[key] for key in COLUMNS}
            for key in ('apply_url','source_url'): old[key]=canonical_url(old[key])
            fingerprint=hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()
            db.execute('UPDATE ingest_job_metadata SET fingerprint=?',(fingerprint,))
        run_once(self.db,[source() | {'auto_publish':False}],lambda _: [job() | {'salary_period':None}])
        self.assertEqual(search_jobs(self.db,{})['total'], 1)

    def test_bad_intervals_fail_before_creating_database(self):
        for interval in (True, -1, 1.5, '100', 604801):
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                validate_sources([source(refresh_interval_seconds=interval)])
        self.assertFalse(self.db.exists())

    def test_expiry_and_salary_period_survive_and_expiry_hides_between_runs(self):
        tomorrow=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        run_once(self.db, [source() | {'ats':'himalayas'}], lambda _: [job(expires_at=tomorrow)])
        result = search_jobs(self.db, {})['jobs'][0]
        self.assertEqual(result['salary_period'], 'hourly')
        self.assertEqual(result['expires_at'], tomorrow)
        self.assertEqual(result['allow_syndication'], 0)
        with connect(self.db) as db:
            db.execute("UPDATE imported_job_details SET expires_at='2000-01-01T00:00:00Z'")
        self.assertEqual(search_jobs(self.db, {})['total'], 0)
        summary=run_once(self.db, [], lambda _: [])
        self.assertEqual(summary['expired'], 1)

    def test_expired_new_job_is_not_published_and_expired_pending_cannot_be_approved(self):
        run_once(self.db, [source()], lambda _: [job(expires_at='2000-01-01T00:00:00Z')])
        self.assertEqual(search_jobs(self.db, {})['total'], 0)
        run_once(self.db, [source() | {'auto_publish':False}], lambda _: [job()])
        with connect(self.db) as db:
            identity=db.execute('SELECT id FROM imported_jobs').fetchone()[0]
            db.execute("UPDATE imported_job_details SET expires_at='2000-01-01T00:00:00Z'")
        with self.assertRaises(ValueError): review_import(self.db, identity, 'approve')

    def test_malformed_expiry_fails_batch(self):
        result=run_once(self.db, [source()], lambda _: [job(expires_at='not-a-date')])
        self.assertEqual(result['errors'], 1)
        self.assertEqual(result['inserted'], 0)


if __name__=='__main__': unittest.main()
