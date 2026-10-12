"""Public aggregate feed contracts; no live requests in this suite."""
import io
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scraper


def himalaya(**changes):
    return dict(title='AI infrastructure engineer', companyName='Acme', companySlug='acme',
                employmentType='Full Time', minSalary=140000, maxSalary=180000, currency='USD', salaryPeriod='annual',
                locationRestrictions=['United States'], timezoneRestrictions=[], categories=['Developer'],
                description='<p>Build machine learning systems.</p>', pubDate=1704067200, expiryDate=4070908800,
                applicationLink='https://external.test/apply/1', guid='https://himalayas.app/companies/acme/jobs/ai') | changes


def remotive(**changes):
    return dict(id=123, title='AI platform engineer', company_name='Acme', category='Software Development',
                tags=['Machine Learning'], job_type='full_time', publication_date='2024-01-01T00:00:00',
                candidate_required_location='Worldwide', salary='$40,000 - $50,000',
                description='<p>Build machine learning systems.</p>',
                url='https://remotive.com/remote-jobs/software-dev/ai-platform-engineer-123') | changes


class HimalayasTest(unittest.TestCase):
    def test_search_pages_use_response_page_size_and_do_not_send_unsupported_limit(self):
        def fetch(url, headers=None):
            parsed = urlsplit(url)
            self.assertEqual(parsed.scheme + '://' + parsed.netloc + parsed.path, 'https://himalayas.app/jobs/api/search')
            query = parse_qs(parsed.query)
            self.assertEqual(query['q'], ['machine learning'])
            self.assertNotIn('limit', query)
            page = int(query['page'][0])
            self.assertIn(page, (1, 2))
            raw = himalaya(guid=f'https://himalayas.app/companies/acme/jobs/{page}')
            return {'jobs': [raw], 'offset': page - 1, 'limit': 1, 'totalCount': 2}
        with patch.object(scraper, 'fetch_json', fetch):
            rows = scraper.source_jobs({'ats': 'himalayas', 'query': 'machine learning', 'limit': 100, 'max_pages': 5})
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['id'], rows[1]['id'])

    def test_browse_uses_opaque_cursor_and_stops_when_absent(self):
        def fetch(url, headers=None):
            parsed = urlsplit(url)
            self.assertEqual(parsed.netloc + parsed.path, 'himalayas.app/jobs/api')
            query = parse_qs(parsed.query)
            self.assertEqual(query['limit'], ['20'])
            self.assertNotIn('offset', query)
            if 'cursor' not in query:
                return {'jobs': [himalaya()], 'nextCursor': 'opaque+/=', 'limit': 20, 'totalCount': 100}
            self.assertEqual(query['cursor'], ['opaque+/='])
            return {'jobs': [himalaya(guid='https://himalayas.app/companies/acme/jobs/second')], 'limit': 20, 'totalCount': 100}
        with patch.object(scraper, 'fetch_json', fetch):
            rows = scraper.source_jobs({'ats': 'himalayas', 'limit': 100, 'max_pages': 5})
        self.assertEqual(len(rows), 2)

    def test_page_bound_and_repeated_cursor_do_not_loop(self):
        calls = []
        def fetch(url, headers=None):
            calls.append(url)
            return {'jobs': [himalaya()], 'nextCursor': 'same', 'limit': 20, 'totalCount': 100}
        with patch.object(scraper, 'fetch_json', fetch):
            rows = scraper.source_jobs({'ats': 'himalayas', 'max_pages': 2})
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(rows), 1)

    def test_normalization_preserves_attribution_salary_type_description_expiry(self):
        raw = himalaya(description='<p>Machine learning ' + 'x' * 6000 + '</p>', employmentType='Contractor', salaryPeriod='hourly', minSalary=50, maxSalary=80)
        row = scraper.normalize('himalayas', 'Himalayas', 'query-one', raw)
        self.assertEqual(row['id'], 'himalayas:public:https://himalayas.app/companies/acme/jobs/ai')
        self.assertEqual(row['company'], 'Acme')
        self.assertEqual(row['url'], raw['guid'])
        self.assertEqual(row['source_url'], raw['guid'])
        self.assertEqual(row['work_mode'], 'Remote')
        self.assertEqual(row['type'], 'Contract')
        self.assertEqual(row['country_code'], 'US')
        self.assertEqual(row['salary_min'], 50)
        self.assertEqual(row['salary_max'], 80)
        self.assertEqual(row['currency'], 'USD')
        self.assertEqual(row['salary_period'], 'hourly')
        self.assertEqual(row['posted_at'], '2024-01-01')
        self.assertEqual(row['expires_at'], '2099-01-01T00:00:00Z')
        self.assertGreater(len(row['description']), 6000)
        self.assertNotIn('<p>', row['description'])
        self.assertTrue(row['ai_explicit'])
        other = scraper.normalize('himalayas', 'Other', 'query-two', raw)
        self.assertEqual(other['id'], row['id'])

    def test_multiple_country_and_timezone_restrictions_are_not_single_country(self):
        raw = himalaya(locationRestrictions=['United States', 'Canada'], timezoneRestrictions=[-5, -8])
        row = scraper.normalize('himalayas', 'Himalayas', 'query', raw)
        self.assertIsNone(row['country_code'])
        self.assertIn('United States', row['location'])
        self.assertIn('Canada', row['location'])
        self.assertIn('UTC-5', row['location'])
        global_row = scraper.normalize('himalayas', 'Himalayas', 'query', himalaya(locationRestrictions=[]))
        self.assertEqual(global_row['location'], 'Worldwide')
        self.assertIsNone(global_row['country_code'])
        timezone_only = scraper.normalize('himalayas', 'Himalayas', 'query', himalaya(locationRestrictions=[], timezoneRestrictions=[2]))
        self.assertIn('UTC+2', timezone_only['location'])
        self.assertNotIn('Worldwide', timezone_only['location'])

    def test_known_single_countries_and_country_codes_support_global_filters(self):
        for label, expected in (('Argentina', 'AR'), ('China', 'CN'), ('Ukraine', 'UA'), ('South Korea', 'KR'), ('Czechia', 'CZ'), ('Costa Rica', 'CR'), ('Hong Kong', 'HK'), ('Malaysia', 'MY'), ('CO', 'CO')):
            with self.subTest(label=label):
                row = scraper.normalize('himalayas', 'Himalayas', 'query', himalaya(locationRestrictions=[label]))
                self.assertEqual(row['country_code'], expected)
        self.assertIsNone(scraper.restriction_country('Argentina, China'))

    def test_provider_listing_url_is_required_instead_of_external_apply_fallback(self):
        for raw in (himalaya(guid='opaque-id'), himalaya(guid='https://evil.test/job'), himalaya(guid=None)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                scraper.normalize('himalayas', 'Himalayas', 'query', raw)

    def test_missing_jobs_and_malformed_entries_fail_instead_of_empty_success(self):
        for response in ({'error': 'bad query'}, {'jobs': {}}, {'jobs': [None]}):
            with self.subTest(response=response), patch.object(scraper, 'fetch_json', return_value=response), self.assertRaises(ValueError):
                scraper.source_jobs({'ats': 'himalayas', 'query': 'AI'})

    def test_invalid_cursor_and_bad_expiry_raise_provider_validation_errors(self):
        with patch.object(scraper, 'fetch_json', return_value={'jobs': [himalaya()], 'nextCursor': ['bad']}), self.assertRaises(ValueError):
            scraper.source_jobs({'ats': 'himalayas'})
        with self.assertRaises(ValueError):
            scraper.normalize('himalayas', 'Himalayas', 'query', himalaya(expiryDate='unknown date'))

    def test_millisecond_and_iso_expiry_keep_the_full_instant(self):
        for value in (4070908800000, '2099-01-01T01:00:00+01:00'):
            with self.subTest(value=value):
                row = scraper.normalize('himalayas', 'Himalayas', 'query', himalaya(expiryDate=value))
                self.assertEqual(row['expires_at'], '2099-01-01T00:00:00Z')
                self.assertTrue(row['ai_explicit'])


class RemotiveTest(unittest.TestCase):
    def test_single_fetch_uses_search_and_category_and_preserves_global_id(self):
        def fetch(url, headers=None):
            parsed = urlsplit(url)
            self.assertEqual(parsed.netloc + parsed.path, 'remotive.com/api/remote-jobs')
            self.assertEqual(parse_qs(parsed.query), {'search': ['machine learning'], 'category': ['software-dev'], 'limit': ['100']})
            return {'job-count': 1, 'jobs': [remotive()]}
        with patch.object(scraper, 'fetch_json', fetch):
            rows = scraper.source_jobs({'ats': 'remotive', 'query': 'machine learning', 'category': 'software-dev', 'limit': 100})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['id'], 'remotive:public:123')
        self.assertEqual(row['url'], 'https://remotive.com/remote-jobs/software-dev/ai-platform-engineer-123')
        self.assertEqual(row['source_url'], row['url'])
        self.assertEqual(row['work_mode'], 'Remote')
        self.assertEqual(row['company'], 'Acme')
        self.assertEqual(row['salary_min'], 40000)
        self.assertEqual(row['salary_max'], 50000)
        self.assertEqual(row['currency'], 'USD')
        self.assertEqual(row['type'], 'Full-time')
        self.assertIsNone(row['country_code'])
        self.assertEqual(row['location'], 'Worldwide')

    def test_location_restriction_and_reported_currency_are_preserved(self):
        row = scraper.normalize('remotive', 'Remotive', 'query', remotive(candidate_required_location='United Kingdom', salary='GBP 60k - 80k', job_type='part_time'))
        self.assertEqual(row['country_code'], 'GB')
        self.assertEqual(row['location'], 'United Kingdom')
        self.assertEqual(row['type'], 'Part-time')
        self.assertEqual(row['currency'], 'GBP')
        self.assertEqual((row['salary_min'], row['salary_max']), (60000, 80000))
        multi = scraper.normalize('remotive', 'Remotive', 'other-query', remotive(candidate_required_location='USA, Canada', salary='Competitive'))
        self.assertIsNone(multi['country_code'])
        self.assertEqual(multi['location'], 'USA, Canada')
        self.assertIsNone(multi['currency'])
        self.assertIsNone(multi['salary_min'])
        self.assertEqual(multi['id'], row['id'])

    def test_employment_types_and_full_plain_description(self):
        for value, expected in (('contract', 'Contract'), ('part_time', 'Part-time'), ('freelance', 'Freelance'), ('internship', 'Internship')):
            with self.subTest(value=value):
                row = scraper.normalize('remotive', 'Remotive', 'query', remotive(job_type=value, description='<p>Machine learning ' + 'x' * 6000 + '</p>'))
                self.assertEqual(row['type'], expected)
                self.assertGreater(len(row['description']), 6000)
                self.assertNotIn('<p>', row['description'])

    def test_decimal_comma_thousands_and_ambiguous_salary_text_do_not_reverse_ranges(self):
        for salary, low, high in (('$35,3k- $52k', 35300, 52000), ('$35,300 - $52,000', 35300, 52000),
                                  ('$100k plus $10k bonus', 100000, None), ('$100k - $50k', None, None)):
            with self.subTest(salary=salary):
                row = scraper.normalize('remotive', 'Remotive', 'query', remotive(salary=salary))
                self.assertEqual((row['salary_min'], row['salary_max']), (low, high))

    def test_rejects_missing_provider_ids_and_attribution_links(self):
        for raw in (remotive(id=None), remotive(url='https://external.test/jobs/123'), remotive(url='https://remotive.com.evil.test/jobs/123')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                scraper.normalize('remotive', 'Remotive', 'query', raw)


class MatchingAndExpiryTest(unittest.TestCase):
    def test_substring_and_html_attribute_matches_do_not_create_ai_jobs(self):
        for text in ('Work on recursive precursors and code quality.', 'Build billing software and improve code review.', '<p style="cursor:pointer">Build ordinary software.</p>'):
            with self.subTest(text=text):
                row = scraper.normalize('remotive', 'Remotive', 'query', remotive(title='Software engineer', tags=[], description=text))
                self.assertFalse(row['ai_explicit'])

    def test_body_and_title_ai_terms_still_match(self):
        for text in ('Build AI-assisted software.', 'Use Cursor and GitHub Copilot to ship systems.', 'Deploy machine learning models.'):
            with self.subTest(text=text):
                row = scraper.normalize('remotive', 'Remotive', 'query', remotive(title='Software engineer', tags=[], description=text))
                self.assertTrue(row['ai_explicit'])

    def test_expired_himalayas_and_unlisted_ashby_are_not_import_eligible(self):
        expired = int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp())
        row = scraper.normalize('himalayas', 'Himalayas', 'query', himalaya(expiryDate=expired))
        self.assertFalse(row['ai_explicit'])
        ashby = {'id': '1', 'title': 'AI infrastructure engineer', 'location': 'London', 'descriptionPlain': 'Build machine learning systems',
                 'jobUrl': 'https://jobs.ashbyhq.com/acme/1', 'isListed': False}
        self.assertFalse(scraper.normalize('ashby', 'Acme', 'acme', ashby)['ai_explicit'])
        self.assertTrue(scraper.normalize('ashby', 'Acme', 'acme', ashby | {'isListed': True})['ai_explicit'])


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.clock = 1000.0
        if hasattr(scraper, '_REQUEST_STARTS'):
            scraper._REQUEST_STARTS.clear()
        self.delays = []
        def sleep(delay):
            self.delays.append(delay)
            self.clock += delay
        self.patches = [patch.object(time, 'monotonic', lambda: self.clock), patch.object(time, 'sleep', sleep)]
        for active in self.patches:
            active.start()
            self.addCleanup(active.stop)

    def error(self, status, headers=None):
        return HTTPError('https://example.test/jobs', status, 'fixture failure', headers or {}, None)

    def test_retry_429_honors_retry_after_then_returns_parsed_response(self):
        with patch.object(scraper.urllib.request, 'urlopen', side_effect=[self.error(429, {'Retry-After': '3'}), io.BytesIO(b'{"jobs": []}')]):
            self.assertEqual(scraper.fetch_json('https://example.test/jobs'), {'jobs': []})
        self.assertIn(3.0, self.delays)

    def test_server_errors_exhaust_exactly_three_attempts(self):
        with patch.object(scraper.urllib.request, 'urlopen', side_effect=self.error(503)) as request:
            with self.assertRaises(HTTPError):
                scraper.fetch_json('https://example.test/jobs')
        self.assertEqual(request.call_count, 3)

    def test_remotive_does_not_retry_inside_reserved_six_hour_request_slot(self):
        for status in (429, 503):
            with self.subTest(status=status):
                if hasattr(scraper, '_REQUEST_STARTS'):
                    scraper._REQUEST_STARTS.clear()
                with patch.object(scraper.urllib.request, 'urlopen', side_effect=self.error(status)) as request, self.assertRaises(HTTPError):
                    scraper.fetch_json('https://remotive.com/api/remote-jobs')
                self.assertEqual(request.call_count, 1)
        self.assertEqual(self.delays, [])

    def test_oversized_retry_after_and_other_client_errors_fail_without_retry(self):
        for failure in (self.error(429, {'Retry-After': '120'}), self.error(429, {'Retry-After': 'Thu, 01 Jan 2099 00:00:00 GMT'}), self.error(404)):
            with self.subTest(failure=failure):
                if hasattr(scraper, '_REQUEST_STARTS'):
                    scraper._REQUEST_STARTS.clear()
                with patch.object(scraper.urllib.request, 'urlopen', side_effect=failure) as request, self.assertRaises(HTTPError):
                    scraper.fetch_json('https://example.test/jobs')
                self.assertEqual(request.call_count, 1)
        self.assertEqual(self.delays, [])

    def test_requests_to_same_host_are_paced_independently_of_other_hosts(self):
        with patch.object(scraper.urllib.request, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(b'{}')):
            scraper.fetch_json('https://one.test/jobs')
            scraper.fetch_json('https://two.test/jobs')
            self.assertEqual(self.delays, [])
            scraper.fetch_json('https://one.test/jobs/2')
        self.assertEqual(self.delays, [.5])


if __name__ == '__main__':
    unittest.main()
