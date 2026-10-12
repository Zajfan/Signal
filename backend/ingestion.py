#!/usr/bin/env python3
"""Reviewed source registry and serialized local ingestion scheduler."""
import argparse
import hashlib
import json
import re
import signal
import sys
import threading
import uuid
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper import source_jobs
from local_server import initialize, connect, now
from marketplace import absolute_url

PROVIDERS = {'greenhouse', 'lever', 'ashby', 'jobtech', 'usajobs', 'smartrecruiters', 'recruitee', 'himalayas', 'remotive', 'jobicy', 'remoteok', 'arbeitnow'}
TRACKING = {'gclid', 'fbclid', 'msclkid', 'source', 'referrer'}
COLUMNS = ('title', 'company_name', 'description', 'source_url', 'apply_url', 'location', 'country_code', 'work_mode', 'employment_type', 'salary_min', 'salary_max', 'salary_currency', 'ai_signals')


def validate_sources(sources):
    if not isinstance(sources, list): raise ValueError('Source configuration must be an array')
    result, seen = [], set()
    for entry in sources:
        if not isinstance(entry, dict): raise ValueError('Every source must be an object')
        s = dict(entry)
        for key in ('source_id', 'ats'):
            if not isinstance(s.get(key), str) or not s[key].strip(): raise ValueError(f'Source needs {key}')
            s[key] = s[key].strip()
        if s['source_id'] in seen: raise ValueError('Duplicate source_id')
        seen.add(s['source_id'])
        if s['ats'] not in PROVIDERS: raise ValueError('Unsupported source provider')
        if type(s.get('enabled', False)) is not bool or type(s.get('auto_publish', False)) is not bool:
            raise ValueError('enabled and auto_publish must be booleans')
        s.setdefault('enabled', False); s.setdefault('auto_publish', False)
        permission = s.get('permission_basis', '')
        if not isinstance(permission, str) or (s['enabled'] and not permission.strip()):
            raise ValueError('Enabled sources need a reviewed permission_basis')
        s['permission_basis'] = permission.strip()
        if s['ats'] not in ('jobtech', 'usajobs', 'himalayas', 'remotive', 'jobicy', 'remoteok', 'arbeitnow') and (not isinstance(s.get('board'), str) or not s['board'].strip()):
            raise ValueError('ATS sources need a board')
        if s.get('terms_url'): absolute_url(s['terms_url'], https_only=True)
        if 'endpoint' in s: raise ValueError('Custom source endpoints are not allowed in the registry')
        for key in ('limit', 'max_pages'):
            if key in s and (type(s[key]) is not int or not 1 <= s[key] <= 500): raise ValueError(f'Invalid {key}')
        if s.get('region', 'us') not in ('us', 'eu'): raise ValueError('Lever region must be us or eu')
        if s.get('token_env') and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', s['token_env']): raise ValueError('Invalid token_env')
        cadence = s.setdefault('refresh_interval_seconds', 86400 if s['ats']=='himalayas' else 0)
        if type(cadence) is not int or not 0 <= cadence <= 604800: raise ValueError('Invalid refresh_interval_seconds')
        s['label'] = str(s.get('label') or s.get('company') or s['source_id'])
        result.append(s)
    return result


def load_sources(config_path):
    return validate_sources(json.loads(Path(config_path).read_text()))


def initialize_ingestion(db_path):
    initialize(Path(db_path))
    with connect(db_path) as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS ingest_job_metadata (
          job_id TEXT PRIMARY KEY REFERENCES imported_jobs(id), canonical_url TEXT NOT NULL, fingerprint TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ingest_job_url ON ingest_job_metadata(canonical_url);
        CREATE INDEX IF NOT EXISTS imported_provider_identity ON imported_jobs(source_job_id);
        CREATE TABLE IF NOT EXISTS ingest_run_metadata (
          source_id TEXT PRIMARY KEY REFERENCES ingest_sources(source_id), fetched_count INTEGER NOT NULL DEFAULT 0,
          inserted_count INTEGER NOT NULL DEFAULT 0, updated_count INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT);
        CREATE TABLE IF NOT EXISTS import_review_events (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES imported_jobs(id), action TEXT NOT NULL,
          moderator_user_id TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')


def canonical_url(value):
    absolute_url(value)
    parts = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in TRACKING]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(sorted(query)), parts.fragment))


def normalize_record(row, config):
    if not isinstance(row, dict): raise ValueError('Source returned a non-object record')
    identity = row.get('id')
    title, company = row.get('title'), row.get('company') or row.get('company_name')
    if not all(isinstance(v, str) and v.strip() for v in (identity, title, company)):
        raise ValueError('Source record needs id, title and company')
    url = absolute_url(row.get('apply_url') or row.get('url'))
    original = absolute_url(row.get('source_url') or url)
    country = row.get('country_code') or row.get('country') or config.get('country_code')
    country = country.upper() if isinstance(country, str) and re.fullmatch('[A-Za-z]{2}', country) else None
    mode = str(row.get('work_mode') or 'on-site').lower()
    if mode not in ('remote', 'hybrid', 'on-site'): mode = 'on-site'
    signals = row.get('ai_signals') or row.get('tags') or []
    if not isinstance(signals, list) or not all(isinstance(s, str) for s in signals): raise ValueError('AI signals must be a list of strings')
    salary_min, salary_max = row.get('salary_min'), row.get('salary_max')
    for amount in (salary_min, salary_max):
        if amount is not None and (type(amount) is not int or amount < 0 or amount > 9007199254740991): raise ValueError('Invalid source salary')
    if salary_min is not None and salary_max is not None and salary_min > salary_max: raise ValueError('Invalid source salary range')
    currency = row.get('salary_currency') or row.get('currency')
    currency = currency.upper() if isinstance(currency, str) and re.fullmatch('[A-Za-z]{3}', currency) else None
    data = dict(title=title.strip(), company_name=company.strip(), description=str(row.get('description') or ''),
                source_url=original, apply_url=url, location=str(row.get('location') or ''), country_code=country,
                work_mode=mode, employment_type=str(row.get('employment_type') or row.get('type') or 'full-time').lower(),
                salary_min=salary_min, salary_max=salary_max, salary_currency=currency, ai_signals=json.dumps(signals))
    for value in data.values():
        if isinstance(value, str): value.encode('utf-8')
    expires = row.get('expires_at') or None
    if expires is not None:
        if not isinstance(expires, str): raise ValueError('Invalid source expiry')
        try:
            parsed = datetime.fromisoformat(expires.replace('Z', '+00:00'))
            if parsed.tzinfo is None: raise ValueError('Expiry needs a timezone')
        except ValueError as exc: raise ValueError('Invalid source expiry') from exc
    period = row.get('salary_period') or None
    if period not in (None, 'hourly', 'daily', 'weekly', 'biweekly', 'fortnightly', 'monthly', 'yearly', 'annually', 'annual'):
        raise ValueError('Invalid salary period')
    details = dict(expires_at=expires, salary_period=period, allow_syndication=0)
    normalized = dict(data, **{k:v for k,v in details.items() if k != 'allow_syndication' and v is not None}, apply_url=canonical_url(url), source_url=canonical_url(original))
    fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    return identity, data, fingerprint, row.get('posted_at') or row.get('source_updated_at'), row.get('ai_explicit') is True and (expires is None or parsed > datetime.now(timezone.utc)), details



def claim_fetch(db_path, source):
    """Persist the request budget before network I/O, including failed attempts."""
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT (julianday('now')-julianday(last_attempt_at))*86400 age FROM ingest_run_metadata WHERE source_id=?", (source['source_id'],)).fetchone()
        if row and row['age'] is not None and row['age'] < source['refresh_interval_seconds']:
            return 'refresh_interval'
        # Remotive recommends no more than four API requests per day, across all searches.
        minimum = 21600 if source['ats']=='remotive' else 0
        provider = db.execute("SELECT (julianday('now')-julianday(last_attempt_at))*86400 age FROM ingest_provider_schedule WHERE provider=?", (source['ats'],)).fetchone()
        if minimum and provider and provider['age'] < minimum:
            return 'provider_interval'
        db.execute('INSERT INTO ingest_run_metadata(source_id,last_attempt_at) VALUES(?,?) ON CONFLICT(source_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at', (source['source_id'],now()))
        db.execute('INSERT INTO ingest_provider_schedule(provider,last_attempt_at) VALUES(?,?) ON CONFLICT(provider) DO UPDATE SET last_attempt_at=excluded.last_attempt_at', (source['ats'],now()))
    return None


def run_once(db_path, sources, fetcher=source_jobs):
    sources = validate_sources(sources)
    initialize_ingestion(db_path)
    # Give the least recently attempted Remotive query the next shared budget slot.
    with connect(db_path) as db:
        attempts = {r['source_id']:r['last_attempt_at'] or '' for r in db.execute('SELECT source_id,last_attempt_at FROM ingest_run_metadata')}
    remotive = iter(sorted((s for s in sources if s['ats']=='remotive'), key=lambda s: attempts.get(s['source_id'],'')))
    sources = [next(remotive) if s['ats']=='remotive' else s for s in sources]
    summary = dict(sources=[], fetched=0, inserted=0, updated=0, skipped=0, expired=0, errors=0)
    for s in sources:
        sid = s['source_id']
        with connect(db_path) as db:
            db.execute('''INSERT INTO ingest_sources(source_id,provider,label,country_code,permission_basis,terms_url,enabled)
              VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET provider=excluded.provider,label=excluded.label,
              country_code=excluded.country_code,permission_basis=excluded.permission_basis,terms_url=excluded.terms_url,
              enabled=excluded.enabled,updated_at=CURRENT_TIMESTAMP''',
              (sid,s['ats'],s['label'],s.get('country_code'),s['permission_basis'],s.get('terms_url'),int(s['enabled'])))
        result = dict(source_id=sid, fetched=0, inserted=0, updated=0, skipped=0)
        deferred = claim_fetch(db_path, s) if s['enabled'] else None
        if deferred: result['deferred'] = deferred
        if s['enabled'] and not deferred:
            try:
                rows = fetcher(s)
                if not isinstance(rows, list): raise ValueError('Source must return an array')
                # Validate the complete batch before writes: malformed partial fetches are not successes.
                records = [normalize_record(row, s) for row in rows]
                result['fetched'] = len(records)
                with connect(db_path) as db:
                    db.execute('BEGIN IMMEDIATE')
                    for identity, data, fingerprint, posted, is_ai, details in records:
                        canonical = canonical_url(data['apply_url'])
                        legacy_identity = identity
                        public_prefix = s['ats'] + ':public:'
                        if s['ats'] in ('jobicy', 'remoteok') and identity.startswith(public_prefix):
                            legacy_identity = s['ats'] + ':' + (s.get('board') or sid) + ':' + identity[len(public_prefix):]
                        old = db.execute('''SELECT j.*,m.fingerprint FROM imported_jobs j LEFT JOIN ingest_job_metadata m ON m.job_id=j.id
                            WHERE j.source_job_id=? OR m.canonical_url=? OR (j.source_id=? AND j.source_job_id=?)
                            ORDER BY j.first_seen_at LIMIT 1''', (identity, canonical, sid, legacy_identity)).fetchone()
                        if old and old['source_id'] != sid:
                            # A second source may not transfer ownership or undo a takedown.
                            result['skipped'] += 1; continue
                        if not old and not is_ai:
                            result['skipped'] += 1; continue
                        state = ('published' if s['auto_publish'] else 'needs_review') if is_ai else 'expired'
                        if old:
                            if old['status'] == 'removed': state = 'removed'
                            elif is_ai and old['status'] == 'published' and old['fingerprint'] == fingerprint: state = 'published'
                            job_id = old['id']
                            # Adopt the current provider identity after a same-source URL match,
                            # so later URL changes still find this row and preserve takedowns.
                            db.execute('UPDATE imported_jobs SET '+','.join(f'{key}=?' for key in COLUMNS)+',source_job_id=?,status=?,source_updated_at=?,last_seen_at=? WHERE id=?',
                                       (*[data[k] for k in COLUMNS],identity,state,posted,now(),job_id))
                            result['updated'] += 1
                        else:
                            job_id = str(uuid.uuid4())
                            db.execute('INSERT INTO imported_jobs(id,source_id,source_job_id,'+','.join(COLUMNS)+',status,source_updated_at,last_seen_at) VALUES('+','.join('?' for _ in range(len(COLUMNS)+6))+')',
                                       (job_id,sid,identity,*[data[k] for k in COLUMNS],state,posted,now()))
                            result['inserted'] += 1
                        db.execute('INSERT INTO imported_job_details(job_id,expires_at,salary_period,allow_syndication) VALUES(?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET expires_at=excluded.expires_at,salary_period=excluded.salary_period,allow_syndication=excluded.allow_syndication', (job_id,details['expires_at'],details['salary_period'],details['allow_syndication']))
                        db.execute('INSERT INTO ingest_job_metadata(job_id,canonical_url,fingerprint) VALUES(?,?,?) ON CONFLICT(job_id) DO UPDATE SET canonical_url=excluded.canonical_url,fingerprint=excluded.fingerprint', (job_id,canonical,fingerprint))
                    db.execute('UPDATE ingest_sources SET last_success_at=?,last_error=NULL WHERE source_id=?',(now(),sid))
            except Exception as exc:
                # Provider errors do not stop other sources or reset freshness.
                result.update(inserted=0,updated=0,skipped=0,error=f'{type(exc).__name__}: {exc}'[:500])
                summary['errors'] += 1
                with connect(db_path) as db: db.execute('UPDATE ingest_sources SET last_error=? WHERE source_id=?',(result['error'],sid))
            with connect(db_path) as db:
                db.execute('''INSERT INTO ingest_run_metadata(source_id,fetched_count,inserted_count,updated_count,last_attempt_at) VALUES(?,?,?,?,?)
                  ON CONFLICT(source_id) DO UPDATE SET fetched_count=excluded.fetched_count,inserted_count=excluded.inserted_count,
                  updated_count=excluded.updated_count''',
                  (sid,result['fetched'],result['inserted'],result['updated'],now()))
        summary['sources'].append(result)
        for key in ('fetched','inserted','updated','skipped'): summary[key] += result[key]
    with connect(db_path) as db:
        summary['expired'] = db.execute("UPDATE imported_jobs SET status='expired' WHERE status='published' AND (datetime(last_seen_at)<datetime('now','-35 days') OR id IN (SELECT job_id FROM imported_job_details WHERE datetime(expires_at)<=datetime('now')))").rowcount
        db.execute("UPDATE employer_jobs SET status='expired' WHERE status='published' AND expires_at IS NOT NULL AND datetime(expires_at)<=datetime('now')")
    return summary


def list_sources(db_path):
    initialize_ingestion(db_path)
    with connect(db_path) as db:
        return [dict(r) for r in db.execute('''SELECT s.*,m.last_attempt_at,m.fetched_count,m.inserted_count,m.updated_count,
          (SELECT COUNT(*) FROM imported_jobs j WHERE j.source_id=s.source_id AND j.status='published') published_count,
          (SELECT COUNT(*) FROM imported_jobs j WHERE j.source_id=s.source_id AND j.status='needs_review') review_count,
          (SELECT COUNT(*) FROM imported_jobs j WHERE j.source_id=s.source_id AND j.status='expired') expired_count
          FROM ingest_sources s LEFT JOIN ingest_run_metadata m USING(source_id) ORDER BY s.label''')]


def list_imports(db_path):
    initialize_ingestion(db_path)
    with connect(db_path) as db:
        return [dict(r) for r in db.execute('''SELECT j.*,s.label source_label,s.permission_basis,s.terms_url,s.enabled
          FROM imported_jobs j JOIN ingest_sources s USING(source_id) WHERE j.status='needs_review' ORDER BY j.first_seen_at DESC LIMIT 500''')]


def review_import(db_path, job_id, action):
    if action not in ('approve','reject'): raise ValueError('Action must be approve or reject')
    initialize_ingestion(db_path)
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT j.*,s.enabled,s.permission_basis,(datetime(j.last_seen_at)>=datetime('now','-35 days') AND (d.expires_at IS NULL OR datetime(d.expires_at)>datetime('now'))) fresh
             FROM imported_jobs j JOIN ingest_sources s USING(source_id) LEFT JOIN imported_job_details d ON d.job_id=j.id WHERE j.id=?''',(job_id,)).fetchone()
        if not row: raise LookupError('Imported job not found')
        if row['status'] != 'needs_review': raise ValueError('Only pending imports can be reviewed')
        if action == 'approve':
            if not row['enabled'] or not row['permission_basis'].strip() or not row['fresh']: raise ValueError('Enabled, permitted source and fresh record are required')
            absolute_url(row['apply_url']); absolute_url(row['source_url'])
        db.execute('UPDATE imported_jobs SET status=? WHERE id=?',('published' if action=='approve' else 'removed',job_id))
        db.execute('INSERT INTO import_review_events VALUES(?,?,?,?,?)',(str(uuid.uuid4()),job_id,action,'local-admin',now()))
        return dict(db.execute('SELECT * FROM imported_jobs WHERE id=?',(job_id,)).fetchone())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--db',type=Path,default=ROOT/'signal.sqlite3')
    parser.add_argument('--interval',type=int)
    args=parser.parse_args()
    if args.interval is not None and args.interval<60: parser.error('Interval must be at least 60 seconds')
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT): signal.signal(sig,lambda *_:stop.set())
    while not stop.is_set():
        try:
            summary=run_once(args.db,load_sources(args.config))
            print(json.dumps(summary),flush=True)
        except (ValueError,OSError) as exc:
            print(f'Ingestion configuration error: {exc}',file=sys.stderr)
            return 2
        if not args.interval: return 1 if summary['errors'] else 0
        stop.wait(args.interval)
    return 0

if __name__=='__main__': raise SystemExit(main())
