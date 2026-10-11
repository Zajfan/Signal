"""Offline connector and SQLite ingestion contracts. Run: python3 backend/ingestion.test.py."""
import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))
import scraper
from local_server import connect
try:
    import ingestion
except ImportError:
    ingestion = None


def source(source_id='example', **changes):
    return dict(source_id=source_id, ats='lever', board='example', label='Example careers',
                permission_basis='Fixture permission', terms_url='https://example.test/terms',
                enabled=True, auto_publish=False, **changes)


def job(identity='lever:example:1', **changes):
    value = dict(id=identity, title='AI platform engineer', company='Example Ltd',
                 description='Build machine learning systems and reliable AI infrastructure.',
                 url='https://example.test/apply?job=1', source_url='https://example.test/jobs/1',
                 location='Stockholm', country_code='SE', currency='SEK', salary_min=0,
                 salary_max=100000, work_mode='Remote', type='Full-time', ai_explicit=True,
                 tags=['AI infrastructure'], posted_at='2026-10-11')
    return value | changes


class ConnectorTest(unittest.TestCase):
    def test_generic_review_and_quality_are_not_ai_signals(self):
        row = scraper.normalize('greenhouse', 'Example', 'example', {
            'id': 1, 'title': 'Software engineer', 'content': 'Own code review and improve code quality.',
            'absolute_url': 'https://example.test/jobs/1'})
        self.assertFalse(row['ai_explicit'])

    def test_lever_eu_date_apply_url_currency_and_full_description(self):
        raw = {'id': '1', 'text': 'AI engineer', 'categories': {'location': 'Stockholm'},
               'country': 'SE', 'createdAt': 1704067200000, 'hostedUrl': 'https://jobs.eu.lever.co/example/1',
               'applyUrl': 'https://jobs.eu.lever.co/example/1/apply', 'descriptionPlain': 'AI ' + 'x' * 6000,
               'salaryRange': {'min': 0, 'max': 100000, 'currency': 'SEK'}}
        def fetch(url, headers=None):
            self.assertEqual(url, 'https://api.eu.lever.co/v0/postings/example?mode=json')
            return [raw]
        with patch.object(scraper, 'fetch_json', fetch):
            row = scraper.source_jobs({'ats': 'lever', 'board': 'example', 'region': 'eu'})[0]
        self.assertEqual(row['posted_at'], '2024-01-01')
        self.assertEqual(row['url'], raw['applyUrl'])
        self.assertEqual(row['source_url'], raw['hostedUrl'])
        self.assertEqual(row['country_code'], 'SE')
        self.assertEqual(row['currency'], 'SEK')
        self.assertEqual(len(row['description']), 6003)
        self.assertEqual(row['salary_min'], 0)

    def test_smartrecruiters_paginates_and_fetches_fixed_host_details(self):
        def fetch(url, headers=None):
            prefix = 'https://api.smartrecruiters.com/v1/companies/acme%2Fteam/postings'
            if '?' in url:
                if 'offset=0' in url:
                    return {'totalFound': 2, 'content': [{'id': '1', 'ref': 'https://bad.test/secret'}]}
                self.assertIn('offset=1', url)
                return {'totalFound': 2, 'content': [{'id': '2'}]}
            self.assertIn(url, [prefix + '/1', prefix + '/2'])
            identity = url.rsplit('/', 1)[1]
            return {'id': identity, 'name': 'AI platform engineer', 'company': {'name': 'Acme'},
                    'location': {'country': 'gb', 'city': 'London', 'remote': True},
                    'jobAd': {'sections': {'jobDescription': {'text': '<p>Build AI infrastructure</p>'},
                                          'qualifications': {'text': 'Machine learning experience'}}},
                    'applyUrl': 'https://jobs.smartrecruiters.com/acme/' + identity,
                    'typeOfEmployment': {'label': 'Part-time'}, 'releasedDate': '2026-10-01T00:00:00Z'}
        with patch.object(scraper, 'fetch_json', fetch):
            rows = scraper.source_jobs({'ats': 'smartrecruiters', 'board': 'acme/team', 'limit': 1})
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['company'], 'Acme')
        self.assertEqual(rows[0]['country_code'], 'GB')
        self.assertEqual(rows[0]['work_mode'], 'Remote')
        self.assertEqual(rows[0]['type'], 'Part-time')
        self.assertIn('Machine learning experience', rows[0]['description'])
        self.assertTrue(rows[0]['ai_explicit'])
        self.assertNotEqual(rows[0]['source_url'], rows[0]['url'])

    def test_recruitee_token_and_multiple_locations(self):
        def fetch(url, headers=None):
            self.assertEqual(url, 'https://acme.recruitee.com/api/offers')
            self.assertEqual(headers, {'X-Careers-Sites-Token': 'fixture-secret'})
            return {'offers': [{'id': 12, 'title': 'Machine learning engineer', 'description': '<p>Build models</p>',
                'requirements': '<p>AI infrastructure experience</p>', 'careers_url': 'https://acme.recruitee.com/o/ml',
                'careers_apply_url': 'https://acme.recruitee.com/o/ml/c/new',
                'locations': [{'country_code': 'nl', 'city': 'Amsterdam'}, {'country_code': 'de', 'city': 'Berlin'}],
                'remote': True, 'employment_type': 'fulltime', 'published_at': '2026-10-01T10:00:00Z'}]}
        with patch.dict(os.environ, {'ACME_CAREERS_TOKEN': 'fixture-secret'}), patch.object(scraper, 'fetch_json', fetch):
            row = scraper.source_jobs({'ats': 'recruitee', 'board': 'acme', 'company': 'Acme', 'token_env': 'ACME_CAREERS_TOKEN'})[0]
        self.assertIn('Amsterdam', row['location'])
        self.assertIn('Berlin', row['location'])
        self.assertEqual(row['country_code'], 'NL')
        self.assertEqual(row['work_mode'], 'Remote')
        self.assertEqual(row['url'], 'https://acme.recruitee.com/o/ml/c/new')
        self.assertEqual(row['source_url'], 'https://acme.recruitee.com/o/ml')
        self.assertIn('AI infrastructure experience', row['description'])

    def test_recruitee_rejects_host_escape_and_missing_configured_token(self):
        for board in ('acme.evil', '../acme', 'acme/recruitee', '-acme', 'acme:443'):
            with self.subTest(board=board), patch.object(scraper, 'fetch_json', side_effect=AssertionError('network')):
                with self.assertRaises(ValueError):
                    scraper.source_jobs({'ats': 'recruitee', 'board': board})
        with patch.dict(os.environ, {}, clear=True), patch.object(scraper, 'fetch_json', side_effect=AssertionError('network')):
            with self.assertRaises(ValueError):
                scraper.source_jobs({'ats': 'recruitee', 'board': 'acme', 'token_env': 'MISSING_TOKEN'})

    def test_jobtech_cross_query_ids_are_provider_stable_and_country_is_preserved(self):
        raw = {'id': '123', 'headline': 'AI engineer', 'employer': {'name': 'Example'},
               'webpage_url': 'https://example.test/jobs/123', 'description': {'text': 'Build machine learning systems'},
               'workplace_address': {'country_code': 'SE', 'city': 'Stockholm'}}
        first = scraper.normalize('jobtech', 'JobTech', 'query-one', raw)
        second = scraper.normalize('jobtech', 'JobTech', 'query-two', raw)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(first['country_code'], 'SE')

    def test_ashby_country_currency_and_application_link(self):
        raw = {'id': 'a', 'title': 'AI engineer', 'location': 'London', 'jobUrl': 'https://jobs.ashbyhq.com/acme/a',
               'applyUrl': 'https://jobs.ashbyhq.com/acme/a/application', 'descriptionPlain': 'Build machine learning',
               'address': {'postalAddress': {'addressCountry': 'GB'}},
               'compensation': {'currencyCode': 'GBP', 'minValue': 0, 'maxValue': 100000}}
        row = scraper.normalize('ashby', 'Acme', 'acme', raw)
        self.assertEqual(row['country_code'], 'GB')
        self.assertEqual(row['currency'], 'GBP')
        self.assertEqual(row['url'], raw['applyUrl'])


class IngestionTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ingestion, 'The ingestion API must exist')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'signal.sqlite3'

    def run_rows(self, rows, sources=None):
        return ingestion.run_once(self.db, sources or [source()], fetcher=lambda _: copy.deepcopy(rows))

    def rows(self):
        with connect(self.db) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM imported_jobs')]

    def test_default_review_and_reruns_refresh_same_stable_record(self):
        first = self.run_rows([job(), job()])
        self.assertEqual(first['inserted'], 1)
        record = self.rows()[0]
        self.assertEqual(record['status'], 'needs_review')
        self.assertEqual(record['country_code'], 'SE')
        self.assertEqual(record['salary_currency'], 'SEK')
        second = self.run_rows([job()])
        self.assertEqual(second['inserted'], 0)
        self.assertEqual(self.rows()[0]['id'], record['id'])
        self.assertEqual(self.rows()[0]['source_job_id'], 'lever:example:1')
        self.assertEqual(self.rows()[0]['source_url'], 'https://example.test/jobs/1')
        queued = ingestion.list_imports(self.db)[0]
        self.assertEqual(queued['source_label'], 'Example careers')
        self.assertEqual(queued['permission_basis'], 'Fixture permission')
        registered = ingestion.list_sources(self.db)[0]
        self.assertEqual(registered['review_count'], 1)
        self.assertIsNotNone(registered['last_success_at'])

    def test_disabled_sources_register_without_fetching(self):
        config = source() | {'enabled': False, 'permission_basis': ''}
        summary = ingestion.run_once(self.db, [config], fetcher=lambda _: self.fail('Disabled source fetched'))
        self.assertEqual(summary['fetched'], 0)
        self.assertEqual(ingestion.list_sources(self.db)[0]['enabled'], 0)

    def test_failures_are_isolated_and_malformed_batch_is_not_partial_success(self):
        configs = [source('bad'), source('good')]
        def fetch(config):
            if config['source_id'] == 'bad':
                return [job(), {'id': 'broken'}]
            return [job('lever:example:2', url='https://example.test/apply?job=2')]
        summary = ingestion.run_once(self.db, configs, fetcher=fetch)
        self.assertEqual(summary['inserted'], 1)
        registered = {item['source_id']: item for item in ingestion.list_sources(self.db)}
        self.assertTrue(registered['bad']['last_error'])
        self.assertIsNone(registered['bad']['last_success_at'])
        self.assertTrue(registered['good']['last_success_at'])
        self.assertEqual(self.rows()[0]['source_id'], 'good')

    def test_cross_query_and_canonical_url_dedupe_preserves_identity_parameters(self):
        self.run_rows([job(url='https://example.test/apply?job=1&utm_source=board')])
        self.run_rows([job('other:record', url='https://example.test/apply?utm_campaign=ai&job=1')], [source('query-two')])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['source_id'], 'example')
        self.run_rows([job('lever:example:2', url='https://example.test/apply?job=2')])
        self.assertEqual(len(self.rows()), 2)

    def test_same_provider_id_cross_queries_dedupes_even_with_different_url(self):
        self.run_rows([job()])
        self.run_rows([job(url='https://example.test/different-application')], [source('query-two')])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['source_id'], 'example')

    def test_rejected_identity_cannot_be_republished_by_autopublish_or_url_alias(self):
        self.run_rows([job()])
        identity = self.rows()[0]['id']
        ingestion.review_import(self.db, identity, 'reject')
        self.run_rows([job(description='Changed AI infrastructure description')], [source() | {'auto_publish': True}])
        self.run_rows([job('alias:1')], [source('new-source') | {'auto_publish': True}])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['status'], 'removed')
        self.assertEqual(ingestion.list_imports(self.db), [])

    def test_approved_same_content_stays_published_but_changed_content_returns_to_review(self):
        self.run_rows([job()])
        identity = self.rows()[0]['id']
        ingestion.review_import(self.db, identity, 'approve')
        self.run_rows([job(posted_at='2026-10-12', url='https://example.test/apply?utm_source=new&job=1')])
        self.assertEqual(self.rows()[0]['status'], 'published')
        self.run_rows([job(description='Build a new machine learning product and AI infrastructure.')])
        self.assertEqual(self.rows()[0]['status'], 'needs_review')
        self.assertEqual(ingestion.list_sources(self.db)[0]['review_count'], 1)

    def test_non_ai_refresh_withdraws_existing_listing_and_recovery_needs_review(self):
        from search import public_job
        self.run_rows([job()])
        identity = self.rows()[0]['id']
        ingestion.review_import(self.db, identity, 'approve')
        ordinary = job(ai_explicit=False, title='Accountant', description='Manage accounts')
        self.run_rows([ordinary], [source() | {'auto_publish': True}])
        self.assertEqual(self.rows()[0]['status'], 'expired')
        self.assertEqual(self.rows()[0]['description'], 'Manage accounts')
        self.assertIsNone(public_job(self.db, identity))
        self.run_rows([job()])
        self.assertEqual(self.rows()[0]['status'], 'needs_review')
        ingestion.review_import(self.db, identity, 'reject')
        self.run_rows([ordinary])
        self.assertEqual(self.rows()[0]['status'], 'removed')

    def test_explicit_autopublish_and_non_ai_filter(self):
        self.run_rows([job(), job('ordinary', ai_explicit=False, title='Engineer', description='Build ordinary software',
                                 url='https://example.test/ordinary')], [source() | {'auto_publish': True}])
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]['status'], 'published')

    def test_stale_expiry_uses_age_without_immediate_expiry_on_failed_fetch(self):
        self.run_rows([job(), job('lever:example:2', url='https://example.test/apply?job=2')], [source() | {'auto_publish': True}])
        stale = (datetime.now(timezone.utc) - timedelta(days=36)).isoformat()
        with connect(self.db) as db:
            db.execute("UPDATE imported_jobs SET last_seen_at=? WHERE source_job_id='lever:example:1'", (stale,))
        summary = ingestion.run_once(self.db, [source()], fetcher=lambda _: (_ for _ in ()).throw(OSError('offline')))
        self.assertEqual(summary['expired'], 1)
        self.assertEqual({row['source_job_id']: row['status'] for row in self.rows()},
                         {'lever:example:1': 'expired', 'lever:example:2': 'published'})

    def test_review_requires_enabled_permission_freshness_valid_url_and_pending_state(self):
        self.run_rows([job()])
        identity = self.rows()[0]['id']
        with self.assertRaises(LookupError):
            ingestion.review_import(self.db, 'missing', 'approve')
        with self.assertRaises(ValueError):
            ingestion.review_import(self.db, identity, 'publish')
        for mutation in ("UPDATE ingest_sources SET enabled=0", "UPDATE ingest_sources SET permission_basis=''",
                         "UPDATE imported_jobs SET apply_url='https://'",
                         "UPDATE imported_jobs SET last_seen_at='2020-01-01T00:00:00Z'"):
            with self.subTest(mutation=mutation), connect(self.db) as db:
                db.execute('SAVEPOINT fixture')
                db.execute(mutation)
                db.commit()
                with self.assertRaises(ValueError):
                    ingestion.review_import(self.db, identity, 'approve')
            # Reset through actual state restoration; rerun does not undo a broken permission gate.
            with connect(self.db) as db:
                db.execute("UPDATE ingest_sources SET enabled=1,permission_basis='Fixture permission'")
                db.execute("UPDATE imported_jobs SET apply_url='https://example.test/apply?job=1',last_seen_at=?",
                           (datetime.now(timezone.utc).isoformat(),))
        approved = ingestion.review_import(self.db, identity, 'approve')
        self.assertEqual(approved['status'], 'published')
        with self.assertRaises(ValueError):
            ingestion.review_import(self.db, identity, 'reject')
        with connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM import_review_events').fetchone()[0], 1)

    def test_invalid_config_is_rejected_before_network_or_registration(self):
        valid = source()
        cases = [None, {}, [1], [valid, valid], [valid | {'enabled': 'false'}],
                 [valid | {'enabled': True, 'permission_basis': ' '}], [valid | {'board': ''}],
                 [valid | {'ats': 'arbitrary'}], [valid | {'auto_publish': 1}],
                 [valid | {'terms_url': 'https://'}], [valid | {'endpoint': 'https://bad.test'}],
                 [valid | {'source_id': ' '}], [valid | {'limit': 0}]]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ingestion.run_once(self.db, value, fetcher=lambda _: self.fail('Invalid config fetched'))
        self.assertFalse(self.db.exists())

    def test_cli_config_validation_and_minimum_interval(self):
        config = Path(self.temp.name) / 'sources.json'
        config.write_text(json.dumps([source() | {'enabled': False, 'permission_basis': ''}]))
        result = subprocess.run([sys.executable, str(ROOT / 'backend/ingestion.py'), '--config', str(config), '--db', str(self.db)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['fetched'], 0)
        result = subprocess.run([sys.executable, str(ROOT / 'backend/ingestion.py'), '--config', str(config), '--db', str(self.db), '--interval', '59'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
