#!/usr/bin/env python3
"""Import Signal scraper JSON into the local SQLite database for review."""
import argparse
import json
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parent.parent
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input",type=Path,help="JSON file written by scraper.py")
    parser.add_argument("--db",type=Path,default=ROOT/"signal.sqlite3")
    parser.add_argument("--permission-basis",required=True,help="Reviewed API/license/permission basis for this source")
    parser.add_argument("--source-id",default="local-scraper")
    parser.add_argument("--source-label",default="Signal local import")
    parser.add_argument("--country",default="")
    parser.add_argument("--publish",action="store_true",help="Make imported jobs public after you have checked redistribution rights and data")
    args=parser.parse_args()
    data=json.loads(args.input.read_text()); jobs=data.get("jobs",data) if isinstance(data,dict) else data
    if not isinstance(jobs,list): parser.error("Input must be a list of jobs or an object containing a jobs list")
    connection=sqlite3.connect(args.db); connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("INSERT INTO ingest_sources(source_id,provider,label,country_code,permission_basis,terms_url,enabled) VALUES(?,?,?,?,?,?,0) ON CONFLICT(source_id) DO UPDATE SET permission_basis=excluded.permission_basis,label=excluded.label",(args.source_id,"local_import",args.source_label,args.country.upper() or None,args.permission_basis,None))
    changed=0
    for job in jobs:
        source_job_id=str(job.get("source_id") or job.get("id") or "").strip()
        title=str(job.get("title") or "").strip(); company=str(job.get("company") or job.get("company_name") or "").strip()
        apply_url=str(job.get("apply_url") or job.get("url") or "").strip()
        if not source_job_id or not title or not company or urlparse(apply_url).scheme not in ("http","https"): continue
        country=str(job.get("country") or args.country).upper() or None
        status="published" if args.publish else "needs_review"
        connection.execute("""INSERT INTO imported_jobs(id,source_id,source_job_id,title,company_name,description,source_url,apply_url,location,country_code,work_mode,employment_type,salary_min,salary_max,salary_currency,ai_signals,status)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id,source_job_id) DO UPDATE SET title=excluded.title,company_name=excluded.company_name,description=excluded.description,source_url=excluded.source_url,apply_url=excluded.apply_url,location=excluded.location,country_code=excluded.country_code,work_mode=excluded.work_mode,employment_type=excluded.employment_type,salary_min=excluded.salary_min,salary_max=excluded.salary_max,salary_currency=excluded.salary_currency,ai_signals=excluded.ai_signals,status=excluded.status,last_seen_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')""",(str(uuid.uuid4()),args.source_id,source_job_id,title,company,str(job.get("description") or ""),str(job.get("source_url") or apply_url),apply_url,str(job.get("location") or ""),country,str(job.get("work_mode") or job.get("mode") or "on-site"),str(job.get("employment_type") or "full-time"),job.get("salary_min"),job.get("salary_max"),job.get("salary_currency"),json.dumps(job.get("ai_signals") or job.get("ai") or []),status))
        changed+=1
    connection.commit(); connection.close()
    print(f"Imported or refreshed {changed} jobs as {'published' if args.publish else 'needs_review'}.")
    if not args.publish: print("They are hidden from public search until rights and records are reviewed.")
if __name__=="__main__": main()
