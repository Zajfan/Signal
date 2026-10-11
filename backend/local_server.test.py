import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs

from local_server import Handler, initialize


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
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute(
                "SELECT company_name, verification_status FROM employers WHERE user_id=?",
                (self.user[0],),
            ).fetchone(), ("Example Ltd", "pending"))

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
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT provider FROM payments").fetchone()[0], "local_demo")

    def test_unverified_or_company_mismatch_cannot_checkout(self):
        self.handler.create_job(self.user, {
            "title": "AI engineer", "company_name": "Different Ltd",
            "description": "Build software using AI-assisted workflows and carefully review generated code.",
            "apply_url": "https://example.test/jobs/1", "location": "Remote",
        })
        job_id = self.response["payload"]["job"]["id"]
        self.handler.checkout(self.user, job_id)
        self.assertEqual(self.response["status"], 403)
        self.handler.verify_company(self.user, {"company_name": "Example Ltd", "website_url": "https://example.test"})
        self.handler.moderate_employer("employer-1", {"action": "approve"})
        self.handler.checkout(self.user, job_id)
        self.assertEqual(self.response["status"], 403)


if __name__ == "__main__":
    unittest.main()
