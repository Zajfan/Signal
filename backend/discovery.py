#!/usr/bin/env python3
"""Import licensed ATS mappings and validate disabled candidates without ingestion."""
import argparse
import csv
import hashlib
import html
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit

PROVIDERS = {'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'recruitee'}
MAX_RESPONSE_BYTES = 32_000_000
MAX_VALIDATIONS = 1000
AI_SIGNAL = re.compile(r'\b(?:ai|artificial intelligence|machine[- ]learning|llms?|large language models?|generative ai|genai|copilot|cursor|claude code|agentic|coding agents?|mlops|ml engineers?|deep learning|neural networks?)\b', re.I)
SLUG = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,199}')


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def checked_source(source):
    if not isinstance(source, dict): raise ValueError('Candidate must be an object')
    if any(k in source for k in ('endpoint', 'token_env', 'headers', 'credentials', 'api_key')):
        raise ValueError('Custom endpoints and credentials are not supported for discovery')
    provider, board, region = source.get('ats'), source.get('board'), source.get('region', 'us')
    if provider not in PROVIDERS: raise ValueError('Unsupported ATS provider')
    if not isinstance(board, str) or not SLUG.fullmatch(board) or '..' in board:
        raise ValueError('Invalid public board slug')
    if region not in ('us', 'eu') or (provider != 'lever' and region != 'us'):
        raise ValueError('Only Lever supports a separate EU endpoint')
    if provider == 'recruitee' and not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', board):
        raise ValueError('Recruitee board must be a single DNS label')
    return provider, board, region


def endpoint_for(source):
    provider, board, region = checked_source(source)
    if provider == 'greenhouse': return f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true'
    if provider == 'lever': return f'https://{"api.eu.lever.co" if region == "eu" else "api.lever.co"}/v0/postings/{board}?mode=json'
    if provider == 'ashby': return f'https://api.ashbyhq.com/posting-api/job-board/{board}'
    if provider == 'smartrecruiters': return f'https://api.smartrecruiters.com/v1/companies/{board}/postings?limit=100&offset=0'
    return f'https://{board.lower()}.recruitee.com/api/offers'


def board_url(source):
    provider, board, region = checked_source(source)
    if provider == 'greenhouse': return f'https://job-boards.greenhouse.io/{board}'
    if provider == 'lever': return f'https://{"jobs.eu.lever.co" if region == "eu" else "jobs.lever.co"}/{board}'
    if provider == 'ashby': return f'https://jobs.ashbyhq.com/{board}'
    if provider == 'smartrecruiters': return f'https://careers.smartrecruiters.com/{board}'
    return f'https://{board.lower()}.recruitee.com/'


def parse_board_url(value):
    """Extract only public, known ATS URL routes; never resolve arbitrary input hosts."""
    if not isinstance(value, str) or any(ord(c) < 33 for c in value) or '\\' in value: return None
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443): return None
        if any(any(secret in key.lower() for secret in ('token', 'key', 'auth', 'secret', 'internal')) for key in parse_qs(url.query)):
            return None
        if re.search(r'%2f|%5c', url.path, re.I): return None
        host, path = url.hostname, unquote(url.path)
        provider = board = None
        region = 'us'
        if host in ('boards.greenhouse.io', 'job-boards.greenhouse.io'):
            match = re.fullmatch(r'/([^/]+)(?:/jobs/[^/]+)?/?', path)
            provider, board = 'greenhouse', match[1] if match else None
        elif host == 'boards-api.greenhouse.io':
            match = re.fullmatch(r'/v1/boards/([^/]+)/jobs(?:/[^/]+)?/?', path)
            provider, board = 'greenhouse', match[1] if match else None
        elif host in ('jobs.lever.co', 'jobs.eu.lever.co'):
            match = re.fullmatch(r'/([^/]+)(?:/[^/]+(?:/apply)?)?/?', path)
            provider, board = 'lever', match[1] if match else None
            region = 'eu' if host == 'jobs.eu.lever.co' else 'us'
        elif host in ('api.lever.co', 'api.eu.lever.co'):
            match = re.fullmatch(r'/v0/postings/([^/]+)(?:/[^/]+)?/?', path)
            provider, board = 'lever', match[1] if match else None
            region = 'eu' if host == 'api.eu.lever.co' else 'us'
        elif host == 'jobs.ashbyhq.com':
            match = re.fullmatch(r'/([^/]+)(?:/[^/]+(?:/application)?)?/?', path)
            provider, board = 'ashby', match[1] if match else None
        elif host == 'api.ashbyhq.com':
            match = re.fullmatch(r'/posting-api/job-board/([^/]+)/?', path)
            provider, board = 'ashby', match[1] if match else None
        elif host in ('careers.smartrecruiters.com', 'jobs.smartrecruiters.com'):
            match = re.fullmatch(r'/([^/]+)(?:/[^/]+)?/?', path)
            provider, board = 'smartrecruiters', match[1] if match else None
        elif host == 'api.smartrecruiters.com':
            match = re.fullmatch(r'/v1/companies/([^/]+)/postings(?:/[^/]+)?/?', path)
            provider, board = 'smartrecruiters', match[1] if match else None
        elif host and host.endswith('.recruitee.com'):
            if re.fullmatch(r'/(?:api/offers|o/[^/]+(?:/c/new)?|jobs)?/?', path):
                provider, board = 'recruitee', host.removesuffix('.recruitee.com')
        source = dict(ats=provider, board=board, region=region)
        checked_source(source)
        return source
    except (ValueError, TypeError):
        return None


def import_directory(raw, provenance):
    """Convert reviewed LastRound-format CSV mappings; its licence does not permit job texts."""
    required = ('source_url', 'fetched_at', 'license', 'license_url', 'attribution', 'attribution_url')
    if not isinstance(provenance, dict) or any(not isinstance(provenance.get(k), str) or not provenance[k].strip() for k in required):
        raise ValueError('Directory source, fetch date, licence and attribution are required')
    if provenance['license'] != 'CC-BY-4.0': raise ValueError('This importer requires a reviewed CC-BY-4.0 directory')
    for key in ('source_url', 'license_url', 'attribution_url'):
        parsed = urlsplit(provenance[key])
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f'{key} must be a public HTTPS reference')
    try:
        fetched = datetime.fromisoformat(provenance['fetched_at'].replace('Z', '+00:00'))
        if not fetched.tzinfo: raise ValueError('Fetch date needs a timezone')
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), strict=True)
        if reader.fieldnames != ['ats_vendor', 'company_name', 'board_slug', 'last_crawled']:
            raise ValueError('Unexpected directory CSV columns')
        rows, seen, total, duplicates = [], set(), 0, 0
        for number, entry in enumerate(reader, start=2):
            total += 1
            if None in entry or any(not isinstance(v, str) or not v.strip() for v in entry.values()):
                raise ValueError(f'Directory row {number} contains missing fields')
            provider, board, label = entry['ats_vendor'], entry['board_slug'], entry['company_name']
            checked_source(dict(ats=provider, board=board))
            date.fromisoformat(entry['last_crawled'])
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', entry['last_crawled']): raise ValueError('Invalid crawl date')
            identity = (provider, board)
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            item = dict(source_id=f'{provider}:us:{board}', ats=provider, board=board, region='us',
                        label=label, company=label, enabled=False, auto_publish=False, permission_basis='',
                        directory_last_crawled=entry['last_crawled'])
            item['board_url'] = board_url(item)
            rows.append(item)
    except (UnicodeError, csv.Error, TypeError) as exc:
        raise ValueError(f'Invalid directory CSV: {exc}') from exc
    directory = dict(provenance, sha256=hashlib.sha256(raw).hexdigest(),
                     scope='Company-to-ATS board mapping only; employer job redistribution permission not reviewed')
    return dict(schema_version=1, directory=directory, imported_rows=total, duplicate_rows=duplicates,
                counts=dict(sorted(Counter(r['ats'] for r in rows).items())), candidates=rows)


def fetch_public_json(url, timeout=20):
    """Credential-free HTTPS to fixed public endpoints, pinned to globally routed DNS addresses."""
    source = parse_board_url(url)
    if source is None or endpoint_for(source) != url:
        raise ValueError('Only generated public provider endpoints may be requested')
    parsed = urlsplit(url)
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(address).is_global or ipaddress.ip_address(address).is_multicast for address in ips):
        raise ValueError('Provider DNS must resolve exclusively to public network addresses')
    # Connect to a checked address directly; a second DNS lookup cannot change the destination.
    conn = http.client.HTTPSConnection(parsed.hostname, timeout=timeout)
    raw_socket = None
    try:
        raw_socket = socket.create_connection((ips[0], 443), timeout=timeout)
        conn.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=parsed.hostname)
        conn.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''),
                     headers={'Accept': 'application/json', 'User-Agent': 'SignalSourceDiscovery/0.1 (public board metadata validation)'})
        response = conn.getresponse()
        if response.status != 200:
            reason = 'Provider redirects are disabled' if 300 <= response.status < 400 else response.reason
            raise HTTPError(url, response.status, reason, response.headers, None)
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES: raise ValueError('Provider response exceeds 32 MB limit')
        return json.loads(data)
    finally:
        conn.close()
        if raw_socket: raw_socket.close()


class ProviderPacer:
    def __init__(self, interval, clock=time.monotonic, sleeper=time.sleep):
        self.interval, self.clock, self.sleeper = interval, clock, sleeper
        self.lock, self.provider_locks, self.last = threading.Lock(), {}, {}

    def wait(self, provider):
        with self.lock:
            provider_lock = self.provider_locks.setdefault(provider, threading.Lock())
        with provider_lock:
            if provider in self.last:
                delay = self.last[provider] + self.interval - self.clock()
                if delay > 0: self.sleeper(delay)
            self.last[provider] = self.clock()


def count_jobs(provider, payload):
    if provider == 'lever':
        rows = payload
    else:
        if not isinstance(payload, dict): raise ValueError('Provider response must be an object')
        key = {'greenhouse': 'jobs', 'ashby': 'jobs', 'smartrecruiters': 'content', 'recruitee': 'offers'}[provider]
        if key not in payload: raise ValueError(f'Provider response is missing {key}')
        rows = payload[key]
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError('Provider jobs must be an array of objects')
    if provider == 'ashby': rows = [r for r in rows if r.get('isListed', True) is not False]
    ai_count = 0
    for row in rows:
        title_key = 'text' if provider == 'lever' else 'name' if provider == 'smartrecruiters' else 'title'
        if not isinstance(row.get(title_key), str) or not row[title_key].strip():
            raise ValueError('Provider job requires a nonempty title')
        fields = ('title', 'text', 'name', 'content', 'description', 'descriptionPlain', 'descriptionHtml', 'additional')
        text = html.unescape(' '.join(v for k in fields if isinstance((v := row.get(k)), str)))
        text = re.sub(r'<[^>]*>', ' ', text)
        lists = row.get('lists')
        if isinstance(lists, list):
            text += ' '.join(str(item.get('text', '')) + ' ' + str(item.get('content', '')) for item in lists if isinstance(item, dict))
        ai_count += int(bool(AI_SIGNAL.search(text)))
    total = len(rows)
    if provider == 'smartrecruiters':
        value = payload.get('totalFound', total)
        if type(value) is not int or value < len(rows): raise ValueError('Invalid totalFound')
        total = value
    return dict(job_count=len(rows), ai_job_count=ai_count, total_reported=total,
                complete=total == len(rows), ai_count_scope='Observed public title/description keyword matches; not reviewed relevance')


def validate_candidates(candidates, *, limit, workers=4, pace_seconds=.75, fetcher=fetch_public_json, on_result=None):
    if not isinstance(candidates, list): raise ValueError('Candidate input must be an array')
    if type(limit) is not int or not 1 <= limit <= MAX_VALIDATIONS: raise ValueError('Validation limit must be 1..1000')
    if type(workers) is not int or not 1 <= workers <= 4: raise ValueError('Workers must be 1..4')
    if not isinstance(pace_seconds, (int, float)) or not .5 <= pace_seconds <= 10:
        raise ValueError('Provider pacing must be .5..10 seconds')
    selected = candidates[:limit]
    pacer = ProviderPacer(pace_seconds)
    started = timestamp()
    def validate(item):
        result = {key: item.get(key) for key in ('source_id', 'ats', 'board', 'region', 'label')} if isinstance(item, dict) else {}
        result.update(checked_at=timestamp(), state='error', job_count=0, ai_job_count=0)
        try:
            endpoint = endpoint_for(item)
            result['endpoint'] = endpoint
            pacer.wait(item['ats'])
            metrics = count_jobs(item['ats'], fetcher(endpoint))
            result.update(metrics, state='reachable' if metrics['job_count'] else 'empty', checked_at=timestamp())
        except (ValueError, TypeError, KeyError, OSError, HTTPError, http.client.HTTPException) as exc:
            result['error'] = f'{type(exc).__name__}: {exc}'[:300]
            if isinstance(exc, HTTPError):
                result['http_status'] = exc.code
                exc.close()
        return result
    results = [None] * len(selected)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(validate, item): index for index, item in enumerate(selected)}
        for future in as_completed(futures):
            index = futures[future]
            results[index] = future.result()
            if on_result: on_result(results[index])
    counts = Counter(row['state'] for row in results)
    summary = dict(validated=len(results), reachable=counts['reachable'], empty=counts['empty'], error=counts['error'],
                   observed_jobs=sum(r['job_count'] for r in results), observed_ai_jobs=sum(r['ai_job_count'] for r in results),
                   providers=dict(sorted(Counter(r.get('ats') or 'unknown' for r in results).items())))
    return dict(schema_version=1, started_at=started, finished_at=timestamp(), workers=workers,
                provider_pace_seconds=pace_seconds, requested_limit=limit, summary=summary, results=results,
                notice='Endpoint observations only. No source enabled, no job texts retained, no jobs ingested or published.')


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    importer = sub.add_parser('import-directory', help='Import reviewed CC-BY-4.0 LastRound-format CSV')
    for name in ('input', 'output', 'license-file'):
        importer.add_argument('--' + name, required=True, type=Path)
    for name in ('source-url', 'fetched-at', 'attribution', 'attribution-url'):
        importer.add_argument('--' + name, required=True)
    importer.add_argument('--upstream-commit')
    importer.add_argument('--readme-file', type=Path)
    importer.add_argument('--method-file', type=Path)
    validator = sub.add_parser('validate', help='Observe bounded candidate boards; never activate feeds')
    validator.add_argument('--input', required=True, type=Path)
    validator.add_argument('--output', required=True, type=Path)
    validator.add_argument('--limit', required=True, type=int)
    validator.add_argument('--workers', type=int, default=4)
    validator.add_argument('--pace-seconds', type=float, default=.75)
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve(): parser.error('Input and output must be different files')
    try:
        if args.command == 'import-directory':
            license_bytes = args.license_file.read_bytes()
            text = license_bytes.decode('utf-8')
            if 'Creative Commons Attribution 4.0' not in text and 'CC BY 4.0' not in text and 'CC-BY-4.0' not in text:
                raise ValueError('Input licence file does not identify CC-BY-4.0')
            provenance = dict(source_url=args.source_url, fetched_at=args.fetched_at, license='CC-BY-4.0',
                license_url='https://creativecommons.org/licenses/by/4.0/', attribution=args.attribution,
                attribution_url=args.attribution_url, license_sha256=hashlib.sha256(license_bytes).hexdigest())
            if args.upstream_commit: provenance['upstream_commit'] = args.upstream_commit
            for name in ('readme', 'method'):
                path = getattr(args, name + '_file')
                if path: provenance[name + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            payload = import_directory(args.input.read_bytes(), provenance)
            write_json(args.output, payload)
            print(json.dumps(dict(imported_rows=payload['imported_rows'], candidates=len(payload['candidates']), counts=payload['counts'])))
            return 0
        payload = json.loads(args.input.read_text())
        candidates = payload['candidates'] if isinstance(payload, dict) else payload
        report = validate_candidates(candidates, limit=args.limit, workers=args.workers, pace_seconds=args.pace_seconds,
            on_result=lambda row: print(json.dumps({k: row.get(k) for k in ('source_id', 'state', 'job_count', 'ai_job_count', 'http_status', 'error')}), file=sys.stderr, flush=True))
        write_json(args.output, report)
        print(json.dumps(report['summary']))
        return 1 if report['summary']['error'] else 0
    except (ValueError, KeyError, OSError, UnicodeError) as exc:
        print(f'Discovery error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
