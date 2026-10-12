import io
import json
import tempfile
import unittest
from pathlib import Path
from wsgiref.util import setup_testing_defaults

from local_server import connect, initialize
try:
    from public_server import create_app
except ImportError:
    create_app = None

ROOT = Path(__file__).resolve().parent.parent


class PublicRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(create_app, 'The public WSGI runtime must exist')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'public.sqlite3'
        initialize(self.path)
        with connect(self.path) as db:
            db.executescript((ROOT / 'tests/fixtures/public-jobs.sql').read_text())
        self.app = create_app(self.path)

    def request(self, path, method='GET', headers=None):
        environ = {}
        setup_testing_defaults(environ)
        route, _, query = path.partition('?')
        environ.update(PATH_INFO=route, QUERY_STRING=query, REQUEST_METHOD=method,
                       **{'wsgi.input': io.BytesIO(b'{}'), 'CONTENT_LENGTH': '2'})
        environ.update(headers or {})
        response = {}
        def start(status, headers):
            response.update(status=int(status.split()[0]), headers=dict(headers))
        result = self.app(environ, start)
        try:
            response['body'] = b''.join(result)
        finally:
            if hasattr(result, 'close'): result.close()
        if response['body'] and response['headers'].get('Content-Type', '').startswith('application/json'):
            response['data'] = json.loads(response['body'])
        return response

    def test_search_pagination_and_provenance(self):
        response = self.request('/api/v1/jobs?limit=1')
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['data']['total'], 3)
        self.assertEqual(response['data']['jobs'][0]['id'], 'usa')
        second = self.request('/api/v1/jobs?limit=1&offset=1')['data']
        self.assertEqual(second['jobs'][0]['id'], 'imported')
        self.assertEqual(second['jobs'][0]['ai_signals'], ['claude code'])
        self.assertEqual(second['jobs'][0]['source_label'], 'Original career board')

    def test_filters_are_literal_and_currency_aware(self):
        for query, expected in [
            ('country=se&currency=sek&salary_min=700000&work_mode=remote&employment_type=full-time', ['sweden']),
            ('currency=USD&salary_min=700000', []), ('employment_type=contract', ['usa']),
            ('q=Python', ['sweden']), ('q=%25', ['sweden']), ('q=_', ['imported']),
            ('ids=sweden,draft,pending,stale,unlicensed', ['sweden']),
        ]:
            with self.subTest(query=query):
                response = self.request('/api/v1/jobs?' + query)
                self.assertEqual(response['status'], 200)
                self.assertEqual([job['id'] for job in response['data']['jobs']], expected)
        for query in ['offset=no', 'limit=1.5', 'country=Sweden', 'work_mode=anywhere', 'salary_min=10']:
            self.assertEqual(self.request('/api/v1/jobs?' + query)['status'], 400)

    def test_details_facets_and_document_routes_hide_unpublished_records(self):
        for identity in ['draft', 'expired', 'pending', 'stale', 'unlicensed', 'missing']:
            self.assertEqual(self.request('/api/v1/jobs/' + identity)['status'], 404, identity)
            self.assertEqual(self.request('/jobs/' + identity)['status'], 404, identity)
        job = self.request('/api/v1/jobs/imported')['data']['job']
        self.assertEqual(job['source_url'], 'https://example.test/source')
        self.assertNotIn('employer_user_id', job)
        self.assertEqual(self.request('/jobs/imported')['status'], 200)
        self.assertEqual(self.request('/api/v1/jobs/facets')['data'], {
            'countries': ['DE', 'SE', 'US'], 'currencies': ['EUR', 'SEK', 'USD'],
            'employment_types': ['contract', 'full-time'],
        })

    def test_private_routes_ignore_spoofed_development_and_dispatch_identity(self):
        headers = {'HTTP_X_LOCAL_ADMIN': 'true', 'HTTP_X_LOCAL_USER_ID': 'owner',
                   'HTTP_OAI_AUTHENTICATED_USER_ID': 'owner', 'HTTP_OAI_AUTHENTICATED_USER_EMAIL': 'owner@example.test'}
        for route in ['/api/v1/employer/profile', '/api/v1/employer/jobs', '/api/v1/admin/jobs',
                      '/api/v1/admin/sources', '/api/v1/local/payments/123/complete',
                      '/api/v1/payments/stripe/webhook', '/employer', '/admin', '/sources']:
            for method in ['GET', 'POST', 'PATCH', 'DELETE']:
                self.assertIn(self.request(route, method, headers)['status'], (404, 405), (route, method))
        for method in ['POST', 'PATCH', 'DELETE']:
            response = self.request('/api/v1/jobs', method, headers)
            self.assertEqual(response['status'], 405)
            self.assertEqual(response['headers']['Allow'], 'GET, HEAD')
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM employer_jobs').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM payments').fetchone()[0], 0)

    def test_public_shell_assets_and_head_exclude_local_controls_and_repository_files(self):
        response = self.request('/')
        self.assertEqual(response['status'], 200)
        self.assertNotIn(b'Development identity', response['body'])
        self.assertNotIn(b'href="/employer', response['body'])
        self.assertIn(b'/web/app.js', response['body'])
        head = self.request('/', 'HEAD')
        self.assertEqual(head['body'], b'')
        self.assertEqual(head['headers']['Content-Length'], str(len(response['body'])))
        for route in ['/web/styles.css', '/web/app.js', '/web/shared.js', '/web/candidate.js', '/web/brand.png']:
            self.assertEqual(self.request(route)['status'], 200, route)
        for route in ['/signal.sqlite3', '/.git/config', '/sources.local.json', '/README.md',
                      '/scraper.py', '/web/../backend/local_server.py', '/web/app.html',
                      '/web/employer.js', '/web/sources.js', '/unknown']:
            self.assertEqual(self.request(route)['status'], 404, route)

    def test_unavailable_database_returns_503_without_creating_a_file(self):
        missing = Path(self.temp.name) / 'missing.sqlite3'
        self.app = create_app(missing)
        for route in ['/api/v1/health', '/api/v1/jobs', '/api/v1/jobs/facets', '/api/v1/jobs/imported', '/jobs/imported']:
            with self.assertLogs('public_server', level='ERROR'):
                response = self.request(route)
            self.assertEqual(response['status'], 503, route)
            self.assertNotIn(str(missing).encode(), response['body'])
        self.assertFalse(missing.exists())
        self.assertEqual(self.request('/')['status'], 200)

    def test_database_readiness_and_public_capabilities(self):
        response = self.request('/api/v1/health')
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['data']['runtime'], 'public')
        self.assertFalse(response['data']['capabilities']['employer_posting'])

    def test_public_database_connection_cannot_write(self):
        import sqlite3
        with connect(self.path, read_only=True) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("UPDATE employer_jobs SET status='published' WHERE id='draft'")


if __name__ == '__main__': unittest.main()
