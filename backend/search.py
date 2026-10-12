"""Public visibility and search contract for the SQLite marketplace."""
import json
import re
from local_server import connect

PUBLIC = '''SELECT id,title,company_name,description,apply_url,location,country_code,work_mode,employment_type,
 salary_min,salary_max,salary_currency,'[]' ai_signals,apply_url source_url,'employer' source_id,
 'Employer posted' source_label,'employer' source_kind,is_featured,COALESCE(published_at,created_at) created_at,
 COALESCE(published_at,created_at) last_seen_at,expires_at
 FROM employer_jobs WHERE status='published' AND (expires_at IS NULL OR datetime(expires_at)>datetime('now'))
 UNION ALL
 SELECT j.id,j.title,j.company_name,j.description,j.apply_url,j.location,j.country_code,j.work_mode,j.employment_type,
 j.salary_min,j.salary_max,j.salary_currency,j.ai_signals,j.source_url,j.source_id,s.label source_label,
 'imported' source_kind,0 is_featured,j.first_seen_at created_at,j.last_seen_at,NULL expires_at
 FROM imported_jobs j JOIN ingest_sources s USING(source_id)
 WHERE j.status='published' AND datetime(j.last_seen_at)>=datetime('now','-35 days') AND trim(s.permission_basis)<>''
'''


def decode(row):
    job = dict(row)
    try: signals = json.loads(job['ai_signals'])
    except (TypeError, ValueError): signals = []
    job['ai_signals'] = signals if isinstance(signals,list) and all(isinstance(s,str) for s in signals) else []
    return job


def search_jobs(db_path, query):
    def value(key): return str(query.get(key,[''])[0]).strip()
    limit_raw, offset_raw = value('limit') or '20', value('offset') or '0'
    if not re.fullmatch(r'\d{1,9}',limit_raw) or not re.fullmatch(r'\d{1,9}',offset_raw): raise ValueError('Pagination must be nonnegative integers')
    limit, offset = min(100,max(1,int(limit_raw))), int(offset_raw)
    clauses, values = [], []
    text = value('q')
    if len(text)>200: raise ValueError('Search text must be at most 200 characters')
    if text:
        pattern = '%' + text.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') + '%'
        clauses.append("(title LIKE ? ESCAPE '\\' OR company_name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' OR location LIKE ? ESCAPE '\\')")
        values.extend([pattern]*4)
    for key,column,regex in (('country','country_code',r'[A-Z]{2}'),('currency','salary_currency',r'[A-Z]{3}')):
        v=value(key).upper()
        if v:
            if not re.fullmatch(regex,v): raise ValueError(f'Invalid {key}')
            clauses.append(column+'=?');values.append(v)
    for key,allowed in (('work_mode',('remote','hybrid','on-site')),('employment_type',('full-time','part-time','contract','temporary','internship','freelance'))):
        v=value(key)
        if v:
            if v not in allowed: raise ValueError(f'Invalid {key}')
            clauses.append(key+'=?');values.append(v)
    salary=value('salary_min')
    if salary:
        if not value('currency'): raise ValueError('Select a currency before filtering salary')
        if not re.fullmatch(r'\d{1,15}',salary): raise ValueError('Salary must be a nonnegative integer')
        clauses.append('salary_min>=?');values.append(int(salary))
    ids=value('ids')
    if ids:
        identities=ids.split(',')
        if len(identities)>200 or any(len(i)>200 for i in identities): raise ValueError('Too many saved jobs')
        clauses.append('id IN ('+','.join('?' for _ in identities)+')');values.extend(identities)
    where=' WHERE '+' AND '.join(clauses) if clauses else ''
    with connect(db_path, read_only=True) as db:
        total=db.execute('SELECT COUNT(*) FROM ('+PUBLIC+')'+where,values).fetchone()[0]
        rows=db.execute('SELECT * FROM ('+PUBLIC+')'+where+' ORDER BY is_featured DESC,datetime(created_at) DESC,id LIMIT ? OFFSET ?',(*values,limit,offset)).fetchall()
    return {'jobs':[decode(row) for row in rows],'total':total,'limit':limit,'offset':offset}


def public_job(db_path, identity):
    with connect(db_path, read_only=True) as db:
        row=db.execute('SELECT * FROM ('+PUBLIC+') WHERE id=?',(identity,)).fetchone()
    return decode(row) if row else None


def facets(db_path):
    with connect(db_path, read_only=True) as db:
        result={}
        for key,column in (('countries','country_code'),('currencies','salary_currency'),('employment_types','employment_type')):
            result[key]=[r[0] for r in db.execute('SELECT DISTINCT '+column+' FROM ('+PUBLIC+') WHERE '+column+' IS NOT NULL AND '+column+"<>'' ORDER BY "+column)]
    return result
