"""Public, read-only WSGI application. Run behind Gunicorn and a TLS proxy.

No local identity, employer, moderation, payment or ingestion routes are mounted.
The local development server remains a separate application.
"""
import json
import logging
import os
import re
import sqlite3
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

from local_server import connect
from search import facets, public_job, search_jobs

ROOT = Path(__file__).resolve().parent.parent
ASSETS = {
    '/web/app.js': 'text/javascript; charset=utf-8',
    '/web/shared.js': 'text/javascript; charset=utf-8',
    '/web/candidate.js': 'text/javascript; charset=utf-8',
    '/web/saved-search.js': 'text/javascript; charset=utf-8',
    '/web/styles.css': 'text/css; charset=utf-8',
    '/web/brand.png': 'image/png',
}
CAPABILITIES = {'employer_posting': False, 'moderation': False, 'payments': False}
SECURITY_HEADERS = [
    ('X-Content-Type-Options', 'nosniff'),
    ('Referrer-Policy', 'strict-origin-when-cross-origin'),
    ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
]


def create_app(db_path=None):
    configured = db_path or os.environ.get('SIGNAL_DB_PATH')
    if not configured:
        raise ValueError('Set SIGNAL_DB_PATH to an initialized Signal database')
    return PublicApplication(Path(configured).resolve())


class PublicApplication:
    def __init__(self, db_path):
        self.db_path = db_path

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '/')
        method = environ.get('REQUEST_METHOD', 'GET')
        headers = []
        try:
            if method not in ('GET', 'HEAD'):
                status, content, mime = self.json(405, {'error': 'Method not allowed'})
                headers.append(('Allow', 'GET, HEAD'))
            else:
                status, content, mime = self.route(path, environ.get('QUERY_STRING', ''))
        except ValueError as exc:
            status, content, mime = self.json(400, {'error': str(exc)})
        except (sqlite3.Error, OSError):
            logging.getLogger(__name__).exception('Public request could not access its data or assets')
            status, content, mime = self.json(503, {'error': 'Signal is temporarily unavailable. Please try again.'})
            headers.append(('Retry-After', '30'))
        start_response(f'{status} {HTTPStatus(status).phrase}', [
            ('Content-Type', mime), ('Content-Length', str(len(content))),
            ('Cache-Control', 'no-store'), *SECURITY_HEADERS, *headers,
        ])
        return [b'' if method == 'HEAD' else content]

    @staticmethod
    def json(status, payload):
        return status, json.dumps(payload, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8'

    @staticmethod
    def shell(status=200):
        return status, (ROOT / 'web/public.html').read_bytes(), 'text/html; charset=utf-8'

    def route(self, path, query):
        if path == '/api/v1/health':
            # Check the tables needed for browsing, not only whether a DB file exists.
            with connect(self.db_path, read_only=True) as db:
                db.execute('SELECT id FROM employer_jobs LIMIT 1').fetchone()
                db.execute('SELECT j.id FROM imported_jobs j JOIN ingest_sources s USING(source_id) LIMIT 1').fetchone()
            return self.json(200, {'ok': True, 'runtime': 'public', 'capabilities': CAPABILITIES})
        if path == '/api/v1/jobs':
            return self.json(200, search_jobs(self.db_path, parse_qs(query, max_num_fields=30)))
        if path == '/api/v1/jobs/facets':
            return self.json(200, facets(self.db_path))
        match = re.fullmatch(r'/api/v1/jobs/([^/]+)', path)
        if match:
            job = public_job(self.db_path, match[1])
            return self.json(200, {'job': job}) if job else self.json(404, {'error': 'This job is no longer available'})
        if path == '/':
            return self.shell()
        match = re.fullmatch(r'/jobs/([^/]+)', path)
        if match:
            return self.shell(200 if public_job(self.db_path, match[1]) else 404)
        if path in ASSETS:
            return 200, (ROOT / path.lstrip('/')).read_bytes(), ASSETS[path]
        return self.json(404, {'error': 'Not found'})
