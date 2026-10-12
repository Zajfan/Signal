#!/usr/bin/env python3
"""Loopback-only Signal API for local development (not production auth/payments)."""
import argparse
import json
import mimetypes
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from marketplace import AI_TERMS, JOB_FIELDS, absolute_url, required_text, validate_job, validate_unicode

ROOT = Path(__file__).resolve().parent.parent
DB_DEFAULT = ROOT / "signal.sqlite3"
MIGRATION = Path(__file__).parent / "migrations" / "0001_marketplace.sql"
EMPLOYER_STATUS_SQL = "CASE WHEN status='published' AND expires_at IS NOT NULL AND datetime(expires_at)<=datetime('now') THEN 'expired' ELSE status END"

def now(): return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path, *, read_only=False):
    target = Path(path).resolve().as_uri() + '?mode=ro' if read_only else path
    db = sqlite3.connect(target, uri=read_only, factory=ClosingConnection)
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
        if size < 0 or size > 1_000_000: raise ValueError("Request body must be at most 1 MB")
        data = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(data, dict): raise ValueError("Request body must be a JSON object")
        validate_unicode(data)
        return data
    def identity(self):
        uid = self.headers.get("X-Local-User-Id", "").strip()
        if not uid: return None
        return uid, self.headers.get("X-Local-User-Email", "local@example.test").strip()[:254]
    def is_admin(self): return self.headers.get("X-Local-Admin") == "true"
    def do_GET(self):
        parsed = urlparse(self.path); path = parsed.path; query = parse_qs(parsed.query)
        if path == "/api/v1/health": return self.send_json(200, {"ok": True, "runtime": "local"})
        if path == "/api/v1/jobs": return self.list_jobs(query)
        if path == "/api/v1/jobs/facets":
            from search import facets
            return self.send_json(200, facets(self.db_path))
        detail = re.fullmatch(r"/api/v1/jobs/([^/]+)", path)
        if detail:
            from search import public_job
            job = public_job(self.db_path, unquote(detail[1]))
            return self.send_json(200, {"job": job}) if job else self.send_json(404, {"error": "This job is no longer available"})
        if path == "/api/v1/employer/profile" or path == "/api/v1/employer/jobs":
            user = self.identity()
            if not user: return self.send_json(401, {"error": "Set X-Local-User-Id for local development"})
            if path.endswith("/profile"):
                with connect(self.db_path) as db:
                    db.execute("INSERT INTO employers(user_id,email) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email", user)
                    profile = dict(db.execute("SELECT user_id,email,company_name,website_url,verification_status,verified_at FROM employers WHERE user_id=?", (user[0],)).fetchone())
                return self.send_json(200, {"employer": profile})
            with connect(self.db_path) as db: jobs = [dict(x) for x in db.execute(f"SELECT id,title,company_name,location,country_code,work_mode,{EMPLOYER_STATUS_SQL} AS status,package_code,created_at,expires_at FROM employer_jobs WHERE employer_user_id=? ORDER BY created_at DESC", (user[0],))]
            return self.send_json(200, {"jobs": jobs})
        match = re.fullmatch(r"/api/v1/employer/jobs/([^/]+)", path)
        if match:
            user = self.identity()
            if not user: return self.send_json(401, {"error": "Set X-Local-User-Id for local development"})
            return self.get_job(user, unquote(match[1]))
        if path in ("/api/v1/admin/employers", "/api/v1/admin/jobs"):
            if not self.is_admin(): return self.send_json(403, {"error": "Set X-Local-Admin: true for local moderation"})
            return self.admin_queue(path.rsplit("/", 1)[1])
        if path in ("/api/v1/admin/sources", "/api/v1/admin/imports"):
            if not self.is_admin(): return self.send_json(403, {"error": "Local moderator access required"})
            from ingestion import list_sources, list_imports
            key = path.rsplit("/", 1)[1]
            return self.send_json(200, {key: list_sources(self.db_path) if key == "sources" else list_imports(self.db_path)})
        if path.startswith("/api/"): return self.send_json(404, {"error": "Route not found"})
        return self.serve_static(path)
    def list_jobs(self, query):
        from search import search_jobs
        try: result = search_jobs(self.db_path, query)
        except ValueError as exc: return self.send_json(400, {"error": str(exc)})
        return self.send_json(200, result)

    def do_POST(self):
        path = urlparse(self.path).path
        try: data = self.body()
        except (ValueError, json.JSONDecodeError) as exc: return self.send_json(400, {"error": str(exc)})
        user = self.identity()
        imported = re.fullmatch(r"/api/v1/admin/imports/([^/]+)/moderate", path)
        if imported:
            if not self.is_admin(): return self.send_json(403, {"error": "Local moderator access required"})
            from ingestion import review_import
            try:
                job = review_import(self.db_path, unquote(imported[1]), data.get("action"))
            except LookupError:
                return self.send_json(404, {"error": "Imported job not found"})
            except ValueError as exc:
                return self.send_json(400, {"error": str(exc)})
            return self.send_json(200, {"job": job})
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
            return self.moderate_employer(unquote(path.split("/")[-2]), data)
        return self.send_json(404, {"error": "Route not found"})
    def create_job(self, user, data):
        try: fields = validate_job(data)
        except ValueError as exc: return self.send_json(400, {"error": str(exc)})
        job_id = str(uuid.uuid4())
        with connect(self.db_path) as db:
            db.execute("INSERT INTO employers(user_id,email) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email", user)
            columns = ",".join(JOB_FIELDS)
            db.execute(f"INSERT INTO employer_jobs(id,employer_user_id,{columns}) VALUES(?,?{',?' * len(JOB_FIELDS)})", (job_id, user[0], *(fields[key] for key in JOB_FIELDS)))
            job = dict(db.execute("SELECT * FROM employer_jobs WHERE id=?", (job_id,)).fetchone())
        return self.send_json(201, {"job": job})

    def get_job(self, user, job_id):
        with connect(self.db_path) as db:
            row = db.execute(f"SELECT *,{EMPLOYER_STATUS_SQL} AS effective_status FROM employer_jobs WHERE id=? AND employer_user_id=?", (job_id, user[0])).fetchone()
        if not row: return self.send_json(404, {"error": "Job not found"})
        job = dict(row)
        job['status'] = job.pop('effective_status')
        return self.send_json(200, {"job": job})

    def do_PATCH(self):
        match = re.fullmatch(r"/api/v1/employer/jobs/([^/]+)", urlparse(self.path).path)
        if not match: return self.send_json(404, {"error": "Route not found"})
        user = self.identity()
        if not user: return self.send_json(401, {"error": "Set X-Local-User-Id for local development"})
        try: data = self.body()
        except ValueError as exc: return self.send_json(400, {"error": str(exc)})
        return self.update_job(user, unquote(match[1]), data)

    def update_job(self, user, job_id, data):
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM employer_jobs WHERE id=? AND employer_user_id=?", (job_id, user[0])).fetchone()
            if not row: return self.send_json(404, {"error": "Job not found"})
            if row["status"] != "draft": return self.send_json(409, {"error": "Only drafts can be edited"})
            if not isinstance(data, dict) or any(key not in JOB_FIELDS for key in data):
                return self.send_json(400, {"error": "Only editable job fields may be updated"})
            try: fields = validate_job(dict(row) | data)
            except ValueError as exc: return self.send_json(400, {"error": str(exc)})
            assignments = ",".join(f"{key}=?" for key in JOB_FIELDS)
            db.execute(f"UPDATE employer_jobs SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE id=?", (*(fields[key] for key in JOB_FIELDS), job_id))
            job = dict(db.execute("SELECT * FROM employer_jobs WHERE id=?", (job_id,)).fetchone())
        return self.send_json(200, {"job": job})

    def admin_queue(self, kind):
        with connect(self.db_path) as db:
            if kind == "employers":
                rows = db.execute("SELECT * FROM employers WHERE verification_status='pending' ORDER BY updated_at,user_id")
            else:
                rows = db.execute("SELECT j.*,e.email,e.verification_status FROM employer_jobs j JOIN employers e ON e.user_id=j.employer_user_id WHERE j.status='pending_review' AND EXISTS (SELECT 1 FROM payments p WHERE p.employer_job_id=j.id AND p.employer_user_id=j.employer_user_id AND p.package_code=j.package_code AND p.status='paid') ORDER BY j.updated_at,j.id")
            queue = [dict(row) for row in rows]
        return self.send_json(200, {kind: queue})

    def serve_static(self, path):
        path = unquote(path)
        if "\x00" in path: return self.send_error(404)
        root = self.web_root.resolve()
        if path == "/":
            target, boundary = root / "index.html", root
        elif path in ("/employer", "/admin", "/sources") or re.fullmatch(r"/jobs/[^/]+", path):
            target, boundary = root / "web" / "app.html", root / "web"
        elif path.startswith("/web/"):
            target, boundary = root / path.lstrip("/"), root / "web"
        elif path in ("/scraper.py", "/boards.json", "/sources.json", "/README.md"):
            target, boundary = root / path.lstrip("/"), root
        else:
            return self.send_error(404)
        if target.is_symlink() or boundary.is_symlink(): return self.send_error(404)
        target = target.resolve()
        if not target.is_relative_to(boundary.resolve()) or not target.is_file(): return self.send_error(404)
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def verify_company(self, user, data):
        try:
            name = required_text(data, "company_name")
            website = absolute_url(required_text(data, "website_url"), https_only=True)
        except ValueError as exc: return self.send_json(400, {"error": str(exc)})
        with connect(self.db_path) as db:
            db.execute("INSERT INTO employers(user_id,email,company_name,website_url,verification_status) VALUES(?,?,?,?, 'pending') ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,company_name=excluded.company_name,website_url=excluded.website_url,verification_status='pending',verified_at=NULL,updated_at=CURRENT_TIMESTAMP", (user[0],user[1],name,website))
        return self.send_json(202, {"verification_status":"pending"})
    def checkout(self, user, job_id):
        package = "standard"
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT j.*,e.company_name AS verified_company,e.verification_status FROM employer_jobs j JOIN employers e ON e.user_id=j.employer_user_id WHERE j.id=? AND j.employer_user_id=?", (job_id,user[0])).fetchone()
            if not row: return self.send_json(404, {"error": "Job not found"})
            if row["verification_status"] != "verified" or row["company_name"].casefold() != str(row["verified_company"] or "").casefold(): return self.send_json(403, {"error": "Verified company name must match the job company before checkout"})
            if row["status"] not in ("draft", "awaiting_payment"): return self.send_json(409, {"error": "Job cannot be checked out in its current state"})
            payment = db.execute("SELECT id FROM payments WHERE employer_job_id=? AND employer_user_id=? AND provider='local_demo' AND package_code=? AND status='checkout_open' ORDER BY created_at,id LIMIT 1", (job_id, user[0], package)).fetchone()
            payment_id = payment["id"] if payment else str(uuid.uuid4())
            if not payment:
                db.execute("INSERT INTO payments(id,employer_job_id,employer_user_id,provider,idempotency_key,package_code,status) VALUES(?,?,?,'local_demo',?,?,'checkout_open')", (payment_id, job_id, user[0], str(uuid.uuid4()), package))
            db.execute("UPDATE employer_jobs SET status='awaiting_payment',package_code=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (package, job_id))
        return self.send_json(200, {"checkout_url": f"/api/v1/local/payments/{job_id}/complete", "payment_id": payment_id, "mode": "local_demo", "message": "No real payment will be taken."})

    def complete_payment(self, user, job_id):
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM employer_jobs WHERE id=? AND employer_user_id=? AND status='awaiting_payment'", (job_id,user[0])).fetchone()
            if not row: return self.send_json(404, {"error": "Awaiting-payment job not found"})
            payment = db.execute("SELECT id FROM payments WHERE employer_job_id=? AND employer_user_id=? AND provider='local_demo' AND status='checkout_open' AND package_code=? ORDER BY created_at,id LIMIT 1", (job_id,user[0],row["package_code"])).fetchone()
            if not payment: return self.send_json(409, {"error": "Matching open local checkout required"})
            db.execute("UPDATE payments SET status='paid',updated_at=CURRENT_TIMESTAMP WHERE id=?", (payment["id"],))
            db.execute("UPDATE employer_jobs SET status='pending_review',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
        return self.send_json(200, {"job_id": job_id, "status": "pending_review", "mode": "local_demo"})
    def moderate(self, job_id, data):
        action=data.get("action")
        if action not in ("approve","reject"): return self.send_json(400,{"error":"Action must be approve or reject"})
        with connect(self.db_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT j.*,e.company_name AS verified_company,e.verification_status FROM employer_jobs j JOIN employers e ON e.user_id=j.employer_user_id WHERE j.id=?",(job_id,)).fetchone()
            if not row: return self.send_json(404,{"error":"Job not found"})
            if row["status"]!="pending_review" or row["verification_status"]!="verified" or row["company_name"].casefold()!=str(row["verified_company"] or "").casefold(): return self.send_json(409,{"error":"Verified employer and pending-review job are required"})
            paid = db.execute("SELECT 1 FROM payments WHERE employer_job_id=? AND employer_user_id=? AND package_code=? AND status='paid' LIMIT 1", (job_id,row["employer_user_id"],row["package_code"])).fetchone()
            if not paid: return self.send_json(409, {"error": "A matching paid job payment is required"})
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
