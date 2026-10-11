import http.client
import json
import threading
from http.server import ThreadingHTTPServer
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, quote

from local_server import Handler, connect, initialize


class LocalMarketplaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "signal.sqlite3"
        initialize(self.db_path)
        self.handler = Handler.__new__(Handler)
        self.handler.db_path = self.db_path
        self.handler.moderator_id = "local-admin"
        self.response = {}
        self.handler.send_json = lambda status, payload: self.response.update(status=status, payload=payload)
        self.user = ("employer-1", "employer@example.test")

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_preserves_existing_data(self):
        self.handler.verify_company(self.user, {
            "company_name": "Example Ltd", "website_url": "https://example.test",
        })
        initialize(self.db_path)
        with connect(self.db_path) as db:
            self.assertEqual(tuple(db.execute(
                "SELECT company_name, verification_status FROM employers WHERE user_id=?",
                (self.user[0],),
            ).fetchone()), ("Example Ltd", "pending"))

    def test_employer_lifecycle_and_publication_gate(self):
        self.handler.verify_company(self.user, {"company_name": "Example Ltd", "website_url": "https://example.test"})
        self.assertEqual(self.response["status"], 202)
        self.handler.moderate_employer("employer-1", {"action": "approve"})
        self.assertEqual(self.response["payload"]["verification_status"], "verified")

        self.handler.create_job(self.user, {
            "title": "AI assisted software engineer", "company_name": "Example Ltd",
            "description": "Build software using AI-assisted workflows and carefully review generated code.",
            "apply_url": "https://example.test/jobs/1", "location": "Remote", "country_code": "US", "work_mode": "remote",
        })
        self.assertEqual(self.response["status"], 201)
        job_id = self.response["payload"]["job"]["id"]
        self.handler.checkout(self.user, job_id)
        self.assertEqual(self.response["payload"]["mode"], "local_demo")
        self.handler.complete_payment(self.user, job_id)
        self.assertEqual(self.response["payload"]["status"], "pending_review")
        self.handler.moderate(job_id, {"action": "approve"})
        self.assertEqual(self.response["payload"]["status"], "published")
        self.handler.list_jobs(parse_qs("limit=10"))
        self.assertEqual(len(self.response["payload"]["jobs"]), 1)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT provider FROM payments").fetchone()[0], "local_demo")

    def test_unverified_or_company_mismatch_cannot_checkout(self):
        self.handler.create_job(self.user, {
            "title": "AI engineer", "company_name": "Different Ltd",
            "description": "Build software using AI-assisted workflows and carefully review generated code.",
            "apply_url": "https://example.test/jobs/1", "location": "Remote", "country_code": "US",
        })
        job_id = self.response["payload"]["job"]["id"]
        self.handler.checkout(self.user, job_id)
        self.assertEqual(self.response["status"], 403)
        self.handler.verify_company(self.user, {"company_name": "Example Ltd", "website_url": "https://example.test"})
        self.handler.moderate_employer("employer-1", {"action": "approve"})
        self.handler.checkout(self.user, job_id)
        self.assertEqual(self.response["status"], 403)


class LocalEmployerRoutesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "signal.sqlite3"
        initialize(self.db_path)
        (self.root / "web").mkdir()
        (self.root / "web" / "app.html").write_text("Employer app")
        (self.root / "web" / "app.js").write_text("asset")
        (self.root / "index.html").write_text("Home")
        (self.root / "scraper.py").write_text("download")
        (self.root / "backend").mkdir()
        (self.root / "backend" / "secret.py").write_text("secret")
        (self.root / "web" / "secret.txt").symlink_to(self.db_path)
        (self.root / "boards.json").symlink_to(self.db_path)
        handler = type("TestHandler", (Handler,), {
            "db_path": self.db_path, "web_root": self.root,
            "log_message": lambda *args: None,
        })
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.valid = {
            "title": "AI software engineer", "company_name": "Example Ltd",
            "description": "Build AI-assisted software with careful reviews.\n\nUse machine learning responsibly.",
            "apply_url": "https://example.test/jobs/1", "location": "Stockholm",
            "country_code": "SE", "work_mode": "hybrid", "employment_type": "full-time",
            "salary_min": 0, "salary_max": 100000, "salary_currency": "SEK",
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, data=None, user="owner", admin=False, raw=None):
        headers = {"Content-Type": "application/json"}
        if user:
            headers["X-Local-User-Id"] = user
        if admin:
            headers["X-Local-Admin"] = "true"
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        conn.request(method, path, body=raw if raw is not None else json.dumps(data) if data is not None else None, headers=headers)
        response = conn.getresponse()
        payload = response.read().decode(errors="replace")
        status = response.status
        conn.close()
        return status, json.loads(payload) if response.getheader("Content-Type", "").startswith("application/json") else payload

    def create(self):
        status, data = self.request("POST", "/api/v1/employer/jobs", self.valid)
        self.assertEqual(status, 201)
        return data["job"]["id"]

    def verify(self):
        self.request("POST", "/api/v1/employer/company-verification", {"company_name": "Example Ltd", "website_url": "https://example.test"})
        self.request("POST", "/api/v1/admin/employers/owner/verify", {"action": "approve"}, admin=True)

    def test_owned_details_and_partial_edit_preserve_multiline_description(self):
        job_id = self.create()
        status, data = self.request("GET", f"/api/v1/employer/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data["job"]["description"], self.valid["description"])
        self.assertEqual(data["job"]["salary_min"], 0)
        status, data = self.request("PATCH", f"/api/v1/employer/jobs/{job_id}", {"title": "AI platform engineer"})
        self.assertEqual(status, 200)
        self.assertEqual(data["job"]["title"], "AI platform engineer")
        self.assertEqual(data["job"]["description"], self.valid["description"])
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT title FROM employer_jobs").fetchone()[0], "AI platform engineer")

    def test_employer_status_reflects_expiry_without_ingestion(self):
        job_id = self.create()
        with connect(self.db_path) as db:
            db.execute("UPDATE employer_jobs SET status='published',expires_at='2020-01-01T00:00:00Z' WHERE id=?", (job_id,))
        status, data = self.request("GET", f"/api/v1/employer/jobs/{job_id}")
        self.assertEqual(status, 200)
        self.assertEqual(data['job']['status'], 'expired')
        status, data = self.request("GET", "/api/v1/employer/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(data['jobs'][0]['status'], 'expired')
        self.assertEqual(self.request("GET", f"/api/v1/jobs/{job_id}")[0], 404)

    def test_job_ownership_and_draft_only_edit(self):
        job_id = self.create()
        for method in ("GET", "PATCH"):
            self.assertEqual(self.request(method, f"/api/v1/employer/jobs/{job_id}", {} if method == "PATCH" else None, user="other")[0], 404)
            self.assertEqual(self.request(method, f"/api/v1/employer/jobs/{job_id}", {} if method == "PATCH" else None, user=None)[0], 401)
        self.verify()
        self.request("POST", f"/api/v1/employer/jobs/{job_id}/checkout", {})
        self.assertEqual(self.request("PATCH", f"/api/v1/employer/jobs/{job_id}", {"title": "AI changed title"})[0], 409)

    def test_invalid_creation_fields_are_rejected_without_inserting(self):
        changes = [
            {"title": 42}, {"company_name": []}, {"location": True}, {"description": "Too short AI"},
            {"title": "Engineer", "description": "Build ordinary software with careful reviews and excellent engineering."},
            {"apply_url": "https://"}, {"apply_url": "https:///jobs"}, {"apply_url": "ftp://example.test"},
            {"country_code": ""}, {"country_code": "USA"}, {"country_code": 12},
            {"work_mode": "anywhere"}, {"employment_type": "unicorn"},
            {"salary_min": -1}, {"salary_max": 2.5}, {"salary_min": True}, {"salary_max": "100"},
            {"salary_min": 200000}, {"salary_currency": ""}, {"salary_currency": "EURO"},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(self.request("POST", "/api/v1/employer/jobs", self.valid | change)[0], 400)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM employer_jobs").fetchone()[0], 0)

    def test_partial_edit_revalidates_complete_salary_range_and_blocks_status(self):
        job_id = self.create()
        for changes in ({"salary_min": 200000}, {"country_code": ""}, {"status": "published"}, {"employer_user_id": "other"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.request("PATCH", f"/api/v1/employer/jobs/{job_id}", changes)[0], 400)
        with connect(self.db_path) as db:
            self.assertEqual(tuple(db.execute("SELECT salary_min,status,employer_user_id FROM employer_jobs").fetchone()), (0, "draft", "owner"))

    def test_checkout_retry_reuses_payment(self):
        job_id = self.create()
        self.verify()
        first = self.request("POST", f"/api/v1/employer/jobs/{job_id}/checkout", {})
        second = self.request("POST", f"/api/v1/employer/jobs/{job_id}/checkout", {})
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1], second[1])
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM payments").fetchone()[0], 1)

    def test_completion_requires_matching_open_checkout(self):
        job_id = self.create()
        with connect(self.db_path) as db:
            db.execute("UPDATE employer_jobs SET status='awaiting_payment',package_code='standard'")
        self.assertEqual(self.request("POST", f"/api/v1/local/payments/{job_id}/complete", {})[0], 409)
        with connect(self.db_path) as db:
            db.execute("INSERT INTO payments(id,employer_job_id,employer_user_id,provider,idempotency_key,package_code,status) VALUES('bad',?,'owner','local_demo','bad','featured','checkout_open')", (job_id,))
        self.assertEqual(self.request("POST", f"/api/v1/local/payments/{job_id}/complete", {})[0], 409)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT status FROM employer_jobs").fetchone()[0], "awaiting_payment")

    def test_review_requires_actual_paid_matching_payment(self):
        job_id = self.create()
        self.verify()
        with connect(self.db_path) as db:
            db.execute("UPDATE employer_jobs SET status='pending_review',package_code='standard'")
        self.assertEqual(self.request("POST", f"/api/v1/admin/jobs/{job_id}/moderate", {"action": "approve"}, admin=True)[0], 409)

    def test_admin_queues_only_pending_companies_and_paid_jobs(self):
        job_id = self.create()
        self.request("POST", "/api/v1/employer/company-verification", {"company_name": "Example Ltd", "website_url": "https://example.test"})
        for route in ("/api/v1/admin/employers", "/api/v1/admin/jobs"):
            self.assertEqual(self.request("GET", route)[0], 403)
        status, data = self.request("GET", "/api/v1/admin/employers", admin=True)
        self.assertEqual(status, 200)
        self.assertEqual([x["user_id"] for x in data["employers"]], ["owner"])
        self.verify()
        self.assertEqual(self.request("GET", "/api/v1/admin/employers", admin=True)[1]["employers"], [])
        self.request("POST", f"/api/v1/employer/jobs/{job_id}/checkout", {})
        self.assertEqual(self.request("GET", "/api/v1/admin/jobs", admin=True)[1]["jobs"], [])
        self.request("POST", f"/api/v1/local/payments/{job_id}/complete", {})
        status, data = self.request("GET", "/api/v1/admin/jobs", admin=True)
        self.assertEqual(status, 200)
        self.assertEqual([x["id"] for x in data["jobs"]], [job_id])
        self.request("POST", f"/api/v1/admin/jobs/{job_id}/moderate", {"action": "reject"}, admin=True)
        self.assertEqual(self.request("GET", "/api/v1/admin/jobs", admin=True)[1]["jobs"], [])

    def test_malformed_json_and_nonobject_body_return_json_400(self):
        for body in ('[1]', 'null', 'true', '"text"', '{broken'):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/v1/employer/jobs", raw=body)[0], 400)
        for route in ("/api/v1/employer/company-verification", "/api/v1/admin/jobs/missing/moderate", "/api/v1/admin/employers/missing/verify"):
            self.assertEqual(self.request("POST", route, raw='[]', admin=True)[0], 400)
        self.assertEqual(self.request("GET", "/api/v1/jobs?limit=banana")[0], 400)
        self.assertEqual(self.request("GET", "/api/v1/jobs?offset=9223372036854775808")[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/employer/company-verification", {"company_name": [], "website_url": "https://"})[0], 400)

    def test_encoded_employer_id_can_be_moderated(self):
        user_id = "owner+team@example.test"
        self.assertEqual(self.request("POST", "/api/v1/employer/company-verification", {"company_name": "Example Ltd", "website_url": "https://example.test"}, user=user_id)[0], 202)
        status, data = self.request("POST", f"/api/v1/admin/employers/{quote(user_id, safe='')}/verify", {"action": "approve"}, admin=True)
        self.assertEqual(status, 200)
        self.assertEqual(data["employer_user_id"], user_id)
        self.assertEqual(self.request("GET", "/api/v1/employer/profile", user=user_id)[1]["employer"]["verification_status"], "verified")

    def test_invalid_unicode_json_fields_are_json_400_without_writes(self):
        job_id = self.create()
        for method, route, data in (
            ("POST", "/api/v1/employer/jobs", self.valid | {"title": "AI engineer\ud800"}),
            ("PATCH", f"/api/v1/employer/jobs/{job_id}", {"description": self.valid["description"] + "\udfff"}),
            ("POST", "/api/v1/employer/company-verification", {"company_name": "Example\ud800", "website_url": "https://example.test"}),
            ("POST", "/api/v1/employer/jobs", self.valid | {"extra": {"nested": ["\ud800"]}}),
            ("POST", "/api/v1/employer/jobs", self.valid | {"\ud800": "extra"}),
        ):
            with self.subTest(method=method, route=route, data=data):
                status, payload = self.request(method, route, data)
                self.assertEqual(status, 400)
                self.assertIn("error", payload)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM employer_jobs").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT description FROM employer_jobs").fetchone()[0], self.valid["description"])

    def test_field_length_bounds_apply_to_create_and_partial_edit(self):
        job_id = self.create()
        for field, too_long in (("title", "AI " + "a" * 178), ("company_name", "b" * 181), ("location", "c" * 181), ("description", "AI " + "d" * 11998)):
            with self.subTest(field=field):
                self.assertEqual(self.request("POST", "/api/v1/employer/jobs", self.valid | {field: too_long})[0], 400)
                self.assertEqual(self.request("PATCH", f"/api/v1/employer/jobs/{job_id}", {field: too_long})[0], 400)
        values_at_limit = {"title": "AI " + "a" * 177, "company_name": "b" * 180, "location": "c" * 180, "description": "AI " + "d" * 11997}
        status, payload = self.request("PATCH", f"/api/v1/employer/jobs/{job_id}", values_at_limit)
        self.assertEqual(status, 200)
        for field, value in values_at_limit.items():
            self.assertEqual(payload["job"][field], value)
        self.assertEqual(self.request("POST", "/api/v1/employer/company-verification", {"company_name": "b" * 181, "website_url": "https://example.test"})[0], 400)

    def test_null_byte_static_paths_return_404(self):
        for path in ("/web/app.js%00", "/web/%00/app.js", "/jobs/%00"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)

    def test_static_allowlist_serves_app_and_denies_repository_internals(self):
        for route in ("/employer", "/admin", "/sources", "/jobs/example-id"):
            with self.subTest(route=route):
                self.assertEqual(self.request("GET", route), (200, "Employer app"))
        self.assertEqual(self.request("GET", "/"), (200, "Home"))
        self.assertEqual(self.request("GET", "/web/app.js"), (200, "asset"))
        self.assertEqual(self.request("GET", "/scraper.py"), (200, "download"))
        for route in ("/signal.sqlite3", "/backend/secret.py", "/.git/config", "/web/../signal.sqlite3", "/web/%2e%2e/signal.sqlite3", "/web/secret.txt", "/boards.json"):
            with self.subTest(route=route):
                self.assertEqual(self.request("GET", route)[0], 404)


if __name__ == "__main__":
    unittest.main()
