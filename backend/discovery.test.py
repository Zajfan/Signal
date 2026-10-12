"""Offline discovery contracts: real directory formats, only transport is replaced."""
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import discovery

CSV = b'ats_vendor,company_name,board_slug,last_crawled\nashby,"Actual, Company",actual-company,2026-08-01\ngreenhouse,Example,example,2026-07-12\nlever,Example EU,example.eu,2026-08-01\n'
PROVENANCE = {
    'source_url': 'https://raw.githubusercontent.com/fyrosofttech/lastroundai-hiring-data/main/ats-directory/catalogue.csv',
    'fetched_at': '2026-10-12T10:00:00Z', 'license': 'CC-BY-4.0',
    'license_url': 'https://creativecommons.org/licenses/by/4.0/',
    'attribution': 'LastRound AI', 'attribution_url': 'https://lastroundai.com/blog/salary-transparency-study-2026',
}


def candidate(ats='greenhouse', board='example', region='us'):
    return dict(source_id=f'{ats}:{region}:{board}', ats=ats, board=board, region=region,
                label='Example', enabled=False, auto_publish=False, permission_basis='')


class DirectoryImportTest(unittest.TestCase):
    def test_real_csv_format_preserves_names_slugs_provenance_and_disabled_state(self):
        result = discovery.import_directory(CSV, PROVENANCE)
        self.assertEqual(result['directory']['sha256'], hashlib.sha256(CSV).hexdigest())
        self.assertEqual(result['directory']['source_url'], PROVENANCE['source_url'])
        self.assertEqual(result['directory']['attribution'], 'LastRound AI')
        self.assertEqual(result['counts'], {'ashby': 1, 'greenhouse': 1, 'lever': 1})
        rows = result['candidates']
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['label'], 'Actual, Company')
        self.assertEqual(rows[0]['board'], 'actual-company')
        self.assertEqual(rows[0]['directory_last_crawled'], '2026-08-01')
        self.assertEqual(rows[2]['board'], 'example.eu')
        for row in rows:
            self.assertIs(row['enabled'], False)
            self.assertIs(row['auto_publish'], False)
            self.assertEqual(row['permission_basis'], '')

    def test_duplicate_board_identity_is_deduplicated_without_guessing_new_boards(self):
        duplicate = CSV + b'greenhouse,Changed display name,example,2026-08-01\n'
        result = discovery.import_directory(duplicate, PROVENANCE)
        self.assertEqual(len(result['candidates']), 3)
        self.assertEqual(result['imported_rows'], 4)
        self.assertEqual(result['duplicate_rows'], 1)

    def test_invalid_rows_fail_the_import_without_silently_hiding_corrupt_data(self):
        for row in (b'unknown,Company,actual,2026-08-01\n', b'lever,,actual,2026-08-01\n',
                    b'lever,Company,../private,2026-08-01\n', b'lever,Company,actual,2026-02-30\n'):
            with self.subTest(row=row), self.assertRaises(ValueError):
                discovery.import_directory(CSV + row, PROVENANCE)
        with self.assertRaises(ValueError):
            discovery.import_directory(b'company,url\nExample,https://example.test\n', PROVENANCE)

    def test_missing_or_unlicensed_provenance_is_rejected(self):
        for key in ('source_url', 'fetched_at', 'license', 'attribution', 'attribution_url'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                discovery.import_directory(CSV, {k: v for k, v in PROVENANCE.items() if k != key})
        with self.assertRaises(ValueError):
            discovery.import_directory(CSV, PROVENANCE | {'license': 'unknown'})

    def test_import_cli_requires_explicit_files_and_preserves_attribution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'directory.csv').write_bytes(CSV)
            (root / 'LICENSE').write_text('Creative Commons Attribution 4.0 International (CC BY 4.0)\nCopyright LastRound AI')
            result = subprocess.run([sys.executable, str(Path(discovery.__file__)), 'import-directory',
                '--input', str(root / 'directory.csv'), '--output', str(root / 'candidates.json'),
                '--source-url', PROVENANCE['source_url'], '--fetched-at', PROVENANCE['fetched_at'],
                '--attribution', 'LastRound AI', '--attribution-url', PROVENANCE['attribution_url'],
                '--license-file', str(root / 'LICENSE')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            stored = json.loads((root / 'candidates.json').read_text())
            self.assertEqual(stored['directory']['license_sha256'], hashlib.sha256((root / 'LICENSE').read_bytes()).hexdigest())
            self.assertEqual(len(stored['candidates']), 3)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['LICENSE', 'candidates.json', 'directory.csv'])


class BoardURLTest(unittest.TestCase):
    def test_known_public_board_and_job_urls_extract_actual_board_identity(self):
        examples = (
            ('https://boards.greenhouse.io/example/jobs/123', 'greenhouse', 'example', 'us'),
            ('https://job-boards.greenhouse.io/example?gh_jid=123', 'greenhouse', 'example', 'us'),
            ('https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true', 'greenhouse', 'example', 'us'),
            ('https://jobs.lever.co/example/123-abc', 'lever', 'example', 'us'),
            ('https://jobs.eu.lever.co/example.eu/123-abc', 'lever', 'example.eu', 'eu'),
            ('https://api.eu.lever.co/v0/postings/example?mode=json', 'lever', 'example', 'eu'),
            ('https://jobs.ashbyhq.com/ActualCompany/job-123', 'ashby', 'ActualCompany', 'us'),
            ('https://api.ashbyhq.com/posting-api/job-board/example', 'ashby', 'example', 'us'),
            ('https://careers.smartrecruiters.com/Example', 'smartrecruiters', 'Example', 'us'),
            ('https://jobs.smartrecruiters.com/Example/123-job', 'smartrecruiters', 'Example', 'us'),
            ('https://api.smartrecruiters.com/v1/companies/Example/postings', 'smartrecruiters', 'Example', 'us'),
            ('https://example-team.recruitee.com/o/job', 'recruitee', 'example-team', 'us'),
            ('https://example-team.recruitee.com/api/offers', 'recruitee', 'example-team', 'us'),
        )
        for url, ats, board, region in examples:
            with self.subTest(url=url):
                self.assertEqual(discovery.parse_board_url(url), {'ats': ats, 'board': board, 'region': region})

    def test_unrelated_private_credentialed_and_malformed_urls_are_rejected(self):
        invalid = (
            'http://jobs.lever.co/example', 'https://localhost/example', 'https://127.0.0.1/example',
            'https://jobs.lever.co.evil.test/example', 'https://jobs.lever.co@evil.test/example',
            'https://user:password@jobs.lever.co/example', 'https://jobs.lever.co:8443/example',
            'https://api.lever.co/private/example', 'https://api.ashbyhq.com/api/nonpublic/example',
            'https://app.greenhouse.io/example', 'https://app.ashbyhq.com/example',
            'https://boards.greenhouse.io/../private', 'https://boards.greenhouse.io/%2e%2e',
            'https://jobs.lever.co/example%2Fprivate', 'https://jobs.lever.co/example%00',
            'https://example.recruitee.com/api/private', 'https://careers.smartrecruiters.com/',
            'https://jobs.lever.co/example?token=secret', 'https://jobs.lever.co/example\\private', None,
        )
        for url in invalid:
            with self.subTest(url=url):
                self.assertIsNone(discovery.parse_board_url(url))

    def test_validation_endpoints_ignore_user_supplied_endpoint_and_credentials(self):
        valid = candidate('lever', 'example.eu', 'eu')
        self.assertEqual(discovery.endpoint_for(valid), 'https://api.eu.lever.co/v0/postings/example.eu?mode=json')
        for change in ({'endpoint': 'http://127.0.0.1/private'}, {'token_env': 'SECRET'}, {'board': '../private'}, {'ats': 'custom'}, {'region': 'private'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                discovery.endpoint_for(valid | change)


class BoardValidationTest(unittest.TestCase):
    def test_counts_public_jobs_and_ai_signals_without_retaining_text(self):
        fixtures = {
            'greenhouse': {'jobs': [{'title': 'AI engineer', 'content': 'Private job description marker'}, {'title': 'Painter', 'content': 'Maintain emails'}]},
            'lever': [{'text': 'Engineer', 'descriptionPlain': 'Build machine learning models'}],
            'ashby': {'jobs': [{'title': 'AI engineer', 'isListed': True}, {'title': 'AI private job', 'isListed': False}]},
            'smartrecruiters': {'content': [{'name': 'LLM engineer'}], 'totalFound': 120},
            'recruitee': {'offers': [{'title': 'Engineer', 'description': '<p>Use AI-assisted workflows</p>'}]},
        }
        wants = {'greenhouse': (2, 1, True), 'lever': (1, 1, True), 'ashby': (1, 1, True), 'smartrecruiters': (1, 1, False), 'recruitee': (1, 1, True)}
        for provider, fixture in fixtures.items():
            with self.subTest(provider=provider):
                report = discovery.validate_candidates([candidate(provider)], limit=1, workers=1,
                    pace_seconds=.5, fetcher=lambda url: fixture)
                row = report['results'][0]
                self.assertEqual((row['job_count'], row['ai_job_count'], row['complete']), wants[provider])
                self.assertEqual(row['state'], 'reachable')
                self.assertNotIn('Private job description marker', json.dumps(report))
                self.assertNotIn('description', row)

    def test_empty_boards_and_source_failures_are_isolated(self):
        inputs = [candidate(board='empty'), candidate(board='blocked'), candidate(board='malformed')]
        def fetch(url):
            if '/empty/' in url: return {'jobs': []}
            if '/blocked/' in url: raise HTTPError(url, 429, 'Too many requests', {}, None)
            return {'jobs': 'not an array'}
        report = discovery.validate_candidates(inputs, limit=3, workers=1, pace_seconds=.5, fetcher=fetch)
        self.assertEqual([r['state'] for r in report['results']], ['empty', 'error', 'error'])
        self.assertEqual(report['summary']['validated'], 3)
        self.assertEqual(report['summary']['error'], 2)
        self.assertEqual(report['results'][1]['http_status'], 429)

    def test_bounded_validation_caps_workers_limit_and_paces_each_provider(self):
        for change in ({'limit': 0}, {'limit': 1001}, {'workers': 5}, {'workers': 0}, {'pace_seconds': .1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                discovery.validate_candidates([candidate()], **({'limit': 1, 'workers': 1, 'pace_seconds': .5} | change))
        lock = threading.Lock()
        active = maximum = 0
        def fetch(url):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(active, maximum)
            time.sleep(.01)
            with lock: active -= 1
            return {'jobs': []}
        report = discovery.validate_candidates([candidate('ashby', f'board-{i}') for i in range(5)],
            limit=2, workers=2, pace_seconds=.5, fetcher=fetch)
        self.assertEqual(report['summary']['validated'], 2)
        self.assertLessEqual(maximum, 2)
        self.assertEqual(len(report['results']), 2)
        observed = []
        fake_now = [0.0]
        pacer = discovery.ProviderPacer(.5, clock=lambda: fake_now[0], sleeper=lambda delay: fake_now.__setitem__(0, fake_now[0] + delay))
        for provider in ('lever', 'lever', 'ashby', 'lever'):
            pacer.wait(provider)
            observed.append(fake_now[0])
        self.assertEqual(observed, [0.0, .5, .5, 1.0])

    def test_enabled_candidates_are_still_only_validated_never_activated(self):
        original = candidate() | {'enabled': True, 'auto_publish': True, 'permission_basis': 'External review'}
        report = discovery.validate_candidates([original], limit=1, workers=1, pace_seconds=.5, fetcher=lambda url: {'jobs': []})
        self.assertEqual(report['summary']['validated'], 1)
        self.assertEqual(original['enabled'], True)
        self.assertEqual(report['results'][0]['source_id'], 'greenhouse:us:example')
        self.assertNotIn('permission_basis', report['results'][0])

    def test_malformed_candidate_is_reported_without_fetching_unknown_endpoints(self):
        def fetch(url): raise AssertionError('Unknown endpoint must not be fetched')
        report = discovery.validate_candidates([candidate() | {'board': '../private'}], limit=1, workers=1, pace_seconds=.5, fetcher=fetch)
        self.assertEqual(report['results'][0]['state'], 'error')

    def test_network_fetch_rejects_private_dns_and_unrelated_hosts(self):
        with patch('discovery.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                discovery.fetch_public_json('https://api.lever.co/v0/postings/example?mode=json')
        for url in ('https://example.test/jobs', 'https://user:pass@api.lever.co/v0/postings/example', 'https://api.lever.co/private'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                discovery.fetch_public_json(url)

    def test_unlisted_ashby_jobs_do_not_make_an_empty_board_reachable(self):
        report = discovery.validate_candidates([candidate('ashby')], limit=1, workers=1,
            pace_seconds=.5, fetcher=lambda url: {'jobs': [{'title': 'AI hidden role', 'isListed': False}]})
        self.assertEqual(report['results'][0]['state'], 'empty')
        self.assertEqual(report['results'][0]['job_count'], 0)
        self.assertEqual(report['results'][0]['ai_job_count'], 0)

    def test_response_with_missing_job_titles_is_an_error_not_inventory(self):
        report = discovery.validate_candidates([candidate()], limit=1, workers=1,
            pace_seconds=.5, fetcher=lambda url: {'jobs': [{}]})
        self.assertEqual(report['results'][0]['state'], 'error')
        self.assertEqual(report['results'][0]['job_count'], 0)

    def test_parser_does_not_interpret_private_recruitee_routes_as_board_urls(self):
        for path in ('/api/private', '/api/candidates', '/admin', '/login'):
            with self.subTest(path=path):
                self.assertIsNone(discovery.parse_board_url('https://example.recruitee.com' + path))

    def test_network_fetch_rejects_nonpublic_multicast_dns_addresses(self):
        with patch('discovery.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('224.0.0.1', 443))]):
            with self.assertRaises(ValueError):
                discovery.fetch_public_json('https://api.lever.co/v0/postings/example?mode=json')

    def test_cli_validation_requires_an_explicit_positive_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'candidates.json'
            source.write_text(json.dumps({'candidates': [candidate()]}))
            result = subprocess.run([sys.executable, str(Path(discovery.__file__)), 'validate', '--input', str(source), '--output', str(root / 'report.json')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / 'report.json').exists())


if __name__ == '__main__':
    unittest.main()
