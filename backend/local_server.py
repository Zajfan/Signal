#!/usr/bin/env python3
"""Loopback-only Signal API for local development (not production auth/payments)."""
import argparse
import json
import mimetypes
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
DB_DEFAULT = ROOT / "signal.sqlite3"
MIGRATION = Path(__file__).parent / "migrations" / "0001_marketplace.sql"
AI_TERMS = re.compile(r"\b(ai|artificial intelligence|machine learning|llm|copilot|cursor|claude code|generative ai|ai-assisted|ai-native|ai agent)\b", re.I)

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db
def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db: db.executescript(MIGRATION.read_text())

class Handler(BaseHTTPRequestHandler):
    db_path = DB_DEFAULT
    web_root = ROOT
    moderator_id = "local-admin"

    def log_message(self, fmt, *args): print("%s - %s" % (self.address_string(), fmt % args))
    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(raw)
    def body(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1_000_000: raise ValueError("Request body exceeds 1 MB")
        return json.loads(self.rfile.read(size) or b"{}")
    def identity(self):
        uid = self.headers.get("X-Local-User-Id", "").strip()
        if not uid: return None
        return uid, self.headers.get("X-Local-User-Email", "local@example.test").strip()[:254]
    def is_admin(self): return self.headers.get("X-Local-Admin") == "true"
    def do_GET(self):
        parsed = urlparse(self.path); path = parsed.path; query = parse_qs(parsed.query)
        if path == "/api/v1/health": return self.send_json(200, {"ok": True, "runtime": "local"})
        if path == "/api/v1/jobs": return self.list_jobs(query)
        if path == "/api/v1/employer/profile" or path == "/api/v1/employer/jobs":
            user = self.identity()
            if not user: return self.send_json(401, {"error": "Set X-Local-User-Id for local development"})
            if path.endswith("/profile"):
                with connect(self.db_path) as db:
                    db.execute("INSERT INTO employers(user_id,email) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email", user)
                    profile = dict(db.execute("SELECT user_id,email,company_name,website_url,verification_status,verified_at FROM employers WHERE user_id=?", (user[0],)).fetchone())
                return self.send_json(200, {"employer": profile})
            with connect(self.db_path) as db: jobs = [dict(x) for x in db.execute("SELECT id,title,company_name,location,country_code,work_mode,status,package_code,created_at,expires_at FROM employer_jobs WHERE employer_user_id=? ORDER BY created_at DESC", (user[0],))]
            return self.send_json(200, {"jobs": jobs})
        if path.startswith("/api/"): return self.send_json(404, {"error": "Route not found"})
        target = (self.web_root / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not target.is_relative_to(self.web_root.resolve()) or not target.is_file(): return self.send_error(404)
        content = target.read_bytes(); self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream"); self.send_header("Content-Length", str(len(content))); self.end_headers(); self.wfile.write(content)
    def list_jobs(self, query):
        terms = []; values = []
        q = query.get("q", [""])[0].strip()
        if q: terms.append("(title LIKE ? OR company_name LIKE ? OR description LIKE ? OR location LIKE ?)"); values.extend([f"%{q}%"] * 4)
        country = query.get("country", [""])[0].strip().upper()
        if country: terms.append("country_code = ?"); values.append(country)
        mode = query.get("work_mode", [""])[0]
        if mode in ("remote", "hybrid", "on-site"): terms.append("work_mode = ?"); values.append(mode)
        where = " AND ".join(terms)
        limit = min(100, max(1, int(query.get("limit", ["20"])[0]))); offset = max(0, int(query.get("offset", ["0"])[0]))
        sql = "SELECT id,title,company_name,description,apply_url,location,country_code,work_mode,employment_type,salary_min,salary_max,salary_currency,ai_signals,source_url,source_id,is_featured,created_at FROM (SELECT id,title,company_name,description,apply_url,location,country_code,work_mode,employment_type,salary_min,salary_max,salary_currency,'[]' AS ai_signals,NULL AS source_url,'employer' AS source_id,is_featured,created_at FROM employer_jobs WHERE status='published' UNION ALL SELECT id,title,company_name,description,apply_url,location,country_code,work_mode,employment_type,salary_min,salary_max,salary_currency,ai_signals,source_url,source_id,0 AS is_featured,last_seen_at AS created_at FROM imported_jobs WHERE status='published')"
        if where: sql += " WHERE " + where
        sql += " ORDER BY is_featured DESC,created_at DESC LIMIT ? OFFSET ?"; values.extend([limit, offset])
        try:
            with connect(self.db_path) as db: jobs = [dict(x) for x in db.execute(sql, values)]
            for job in jobs:
                try: job["ai_signals"] = json.loads(job["ai_signals"] or "[]")
                except (ValueError, TypeError): job["ai_signals"] = []
            return self.send_json(200, {"jobs": jobs, "limit": limit, "offset": offset})
        except sqlite3.Error as exc: return self.send_json(500, {"error": str(exc)})
    def do_POST(self):
        path = urlparse(self.path).path
        try: data = self.body()
        except (ValueError, json.JSONDecodeError) as exc: return self.send_json(400, {"error": str(exc)})
        user = self.identity()
        if path == "/api/v1/employer/jobs":
            if not user: return self.send_json(401, {"error": "Set X-Local-User-Id for local development"})
            return self.create_job(user, data)
        if path == "/api/v1/employer/company-verification":
            if not user: return self.send_json(401, {"error": "Set X-Local-User-Id for local development"})
            return self.verify_company(user, data)
        if path.startswith("/api/v1/employer/jobs/") and path.endswith("/checkout"):
            if not user: return self.send_json(401, {"error": "Set X-Local-User-Id for local development"})
            return self.checkout(user, path.split("/")[-2])
        if path.startswith("/api/v1/local/payments/") and path.endswith("/complete"):
            if not user: return self.send_json(401, {"error": "Set X-Local-User-Id for local development"})
            return self.complete_payment(user, path.split("/")[-2])
        if path.startswith("/api/v1/admin/jobs/") and path.endswith("/moderate"):
            if not self.is_admin(): return self.send_json(403, {"error": "Set X-Local-Admin: true for local moderation"})
            return self.moderate(path.split("/")[-2], data)
        if path.startswith("/api/v1/admin/employers/") and path.endswith("/verify"):
            if not self.is_admin(): return self.send_json(403, {"error": "Set X-Local-Admin: true for local moderation"})
            return self.moderate_employer(path.split("/")[-2], data)
        return self.send_json(404, {"error": "Route not found"})
    def create_job(self, user, data):
        required = [str(data.get(k, "")).strip() for k in ("title", "company_name", "description", "apply_url", "location")]
        title, company, description, apply_url, location = required
        if not all(required) or len(description) < 40: return self.send_json(400, {"error": "Title, company, 40+ character description, apply URL and location are required"})
        if not AI_TERMS.search(title + " " + description): return self.send_json(400, {"error": "The role must include an AI or AI-assisted development signal"})
        if not apply_url.startswith(("https://", "http://")): return self.send_json(400, {"error": "Apply URL must use HTTP or HTTPS"})
        mode = data.get("work_mode", "on-site")
        if mode not in ("remote", "hybrid", "on-site"): return self.send_json(400, {"error": "Invalid work mode"})
        job_id = str(uuid.uuid4()); country = (data.get("country_code") or "").upper() or None
        with connect(self.db_path) as db:
            db.execute("INSERT INTO employers(user_id,email) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email", user)
            db.execute("INSERT INTO employer_jobs(id,employer_user_id,title,company_name,description,apply_url,location,country_code,work_mode,employment_type,salary_min,salary_max,salary_currency,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'draft')", (job_id,user[0],title,company,description,apply_url,location,country,mode,data.get("employment_type","full-time"),data.get("salary_min"),data.get("salary_max"),data.get("salary_currency")))
        return self.send_json(201, {"job": {"id": job_id,"title": title,"company_name": company,"status":"draft"}})
    def verify_company(self, user, data):
        name = str(data.get("company_name", "")).strip(); website = str(data.get("website_url", "")).strip()
        if not name or not website.startswith("https://"): return self.send_json(400, {"error": "Company name and HTTPS website URL are required"})
        with connect(self.db_path) as db:
            db.execute("INSERT INTO employers(user_id,email,company_name,website_url,verification_status) VALUES(?,?,?,?, 'pending') ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,company_name=excluded.company_name,website_url=excluded.website_url,verification_status='pending',verified_at=NULL,updated_at=CURRENT_TIMESTAMP", (user[0],user[1],name,website))
        return self.send_json(202, {"verification_status":"pending"})
    def checkout(self, user, job_id):
        package = "standard"
        with connect(self.db_path) as db:
            row = db.execute("SELECT j.*,e.company_name AS verified_company,e.verification_status FROM employer_jobs j JOIN employers e ON e.user_id=j.employer_user_id WHERE j.id=? AND j.employer_user_id=?", (job_id,user[0])).fetchone()
            if not row: return self.send_json(404,{"error":"Job not found"})
            if row["verification_status"] != "verified" or row["company_name"].casefold()!=str(row["verified_company"] or "").casefold(): return self.send_json(403,{"error":"Verified company name must match the job company before checkout"})
            if row["status"] not in ("draft","awaiting_payment"): return self.send_json(409,{"error":"Job cannot be checked out in its current state"})
            db.execute("UPDATE employer_jobs SET status='awaiting_payment',package_code=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(package,job_id))
            db.execute("INSERT INTO payments(id,employer_job_id,employer_user_id,provider,idempotency_key,package_code,status) VALUES(?,?,?,'local_demo',?,?,'checkout_open')",(str(uuid.uuid4()),job_id,user[0],str(uuid.uuid4()),package))
        return self.send_json(200,{"checkout_url":f"/api/v1/local/payments/{job_id}/complete","mode":"local_demo","message":"No real payment will be taken."})
    def complete_payment(self, user, job_id):
        with connect(self.db_path) as db:
            row=db.execute("SELECT id FROM employer_jobs WHERE id=? AND employer_user_id=? AND status='awaiting_payment'",(job_id,user[0])).fetchone()
            if not row: return self.send_json(404,{"error":"Awaiting-payment job not found"})
            db.execute("UPDATE payments SET status='paid',updated_at=CURRENT_TIMESTAMP WHERE employer_job_id=? AND employer_user_id=? AND provider='local_demo' AND status='checkout_open'",(job_id,user[0]))
            db.execute("UPDATE employer_jobs SET status='pending_review',updated_at=CURRENT_TIMESTAMP WHERE id=?",(job_id,))
        return self.send_json(200,{"job_id":job_id,"status":"pending_review","mode":"local_demo"})
    def moderate(self, job_id, data):
        action=data.get("action")
        if action not in ("approve","reject"): return self.send_json(400,{"error":"Action must be approve or reject"})
        with connect(self.db_path) as db:
            row=db.execute("SELECT j.*,e.company_name AS verified_company,e.verification_status FROM employer_jobs j JOIN employers e ON e.user_id=j.employer_user_id WHERE j.id=?",(job_id,)).fetchone()
            if not row: return self.send_json(404,{"error":"Job not found"})
            if row["status"]!="pending_review" or row["verification_status"]!="verified" or row["company_name"].casefold()!=str(row["verified_company"] or "").casefold(): return self.send_json(409,{"error":"Verified employer and pending-review job are required"})
            status="published" if action=="approve" else "rejected"; published=now() if status=="published" else None; expires=(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(timespec="seconds").replace("+00:00","Z") if published else None
            db.execute("UPDATE employer_jobs SET status=?,published_at=?,expires_at=?,is_featured=0,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,published,expires,job_id))
            db.execute("INSERT INTO moderation_events(id,employer_job_id,moderator_user_id,action) VALUES(?,?,?,?)",(str(uuid.uuid4()),job_id,self.moderator_id,action))
        return self.send_json(200,{"job_id":job_id,"status":status,"expires_at":expires})
    def moderate_employer(self, user_id, data):
        action=data.get("action")
        if action not in ("approve","reject"): return self.send_json(400,{"error":"Action must be approve or reject"})
        status="verified" if action=="approve" else "rejected"
        with connect(self.db_path) as db:
            row=db.execute("SELECT user_id FROM employers WHERE user_id=?",(user_id,)).fetchone()
            if not row: return self.send_json(404,{"error":"Employer not found"})
            db.execute("UPDATE employers SET verification_status=?,verified_at=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",(status,now() if status=="verified" else None,user_id))
        return self.send_json(200,{"employer_user_id":user_id,"verification_status":status})
    def do_PUT(self): return self.send_json(405,{"error":"Method not allowed"})

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8000); parser.add_argument("--db",type=Path,default=DB_DEFAULT); args=parser.parse_args()
    if args.host not in ("127.0.0.1","localhost","::1"): parser.error("The local server only binds to loopback addresses")
    initialize(args.db); Handler.db_path=args.db.resolve()
    print(f"Signal local dev server: http://{args.host}:{args.port} (SQLite: {args.db})")
    print("Local identity headers and simulated checkout are development-only.")
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()

if __name__=="__main__": main()
