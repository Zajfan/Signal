import tempfile
import unittest
from pathlib import Path
from local_server import initialize, connect
try:
    from search import search_jobs, public_job, facets
except ImportError:
    search_jobs = public_job = facets = None

class SearchTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(search_jobs)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'search.db';initialize(self.path)
        with connect(self.path) as db:
            db.execute("INSERT INTO employers(user_id,email) VALUES('owner','owner@example.test')")
            for id,title,country,currency,salary,status,expires in [
                ('a','AI Engineer','SE','SEK',800000,'published','2099-01-01'),
                ('b','AI Researcher','US','USD',150000,'published','2099-01-01'),
                ('c','AI Draft','SE','SEK',900000,'draft','2099-01-01'),
                ('d','AI Expired','SE','SEK',900000,'published','2000-01-01')]:
                db.execute('''INSERT INTO employer_jobs(id,employer_user_id,title,company_name,description,apply_url,location,country_code,salary_currency,salary_min,status,expires_at,work_mode)
                    VALUES(?,'owner',?,'Example','Build AI systems','https://example.test/jobs','Remote',?,?,?,?,?,'remote')''',(id,title,country,currency,salary,status,expires))
            db.execute("INSERT INTO ingest_sources(source_id,provider,label,permission_basis,enabled) VALUES('fixture','lever','Original feed','Fixture license',1)")
            db.execute("INSERT INTO imported_jobs(id,source_id,source_job_id,title,company_name,source_url,apply_url,status,last_seen_at) VALUES('stale','fixture','stale','AI stale','Example','https://example.test/1','https://example.test/1','published','2000-01-01')")
    def test_visibility_pagination_and_details(self):
        result=search_jobs(self.path,{'limit':['1']})
        self.assertEqual(result['total'],2);self.assertEqual(len(result['jobs']),1)
        second=search_jobs(self.path,{'limit':['1'],'offset':['1']})
        self.assertNotEqual(result['jobs'][0]['id'],second['jobs'][0]['id'])
        for id in ('c','d','stale','unknown'): self.assertIsNone(public_job(self.path,id))
        self.assertEqual(public_job(self.path,'a')['source_kind'],'employer')
    def test_global_filters_and_salary_currency(self):
        result=search_jobs(self.path,{'country':['SE'],'work_mode':['remote'],'employment_type':['full-time'],'currency':['SEK'],'salary_min':['700000']})
        self.assertEqual([j['id'] for j in result['jobs']],['a'])
        self.assertEqual(search_jobs(self.path,{'q':['Researcher']})['jobs'][0]['id'],'b')
        self.assertEqual(search_jobs(self.path,{'q':['%']})['total'],0)
        for query in ({'salary_min':['100']},{'offset':['oops']},{'work_mode':['anywhere']},{'country':['not-a-country']}):
            with self.assertRaises(ValueError): search_jobs(self.path,query)
    def test_saved_ids_and_facets_do_not_reveal_hidden_jobs(self):
        self.assertEqual([j['id'] for j in search_jobs(self.path,{'ids':['a,c,stale']})['jobs']],['a'])
        values=facets(self.path)
        self.assertEqual(values['countries'],['SE','US']);self.assertEqual(values['currencies'],['SEK','USD'])

if __name__=='__main__':unittest.main()
