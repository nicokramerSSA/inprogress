import io
import os
import tempfile
import threading
import unittest

# Configure env BEFORE importing app (app reads secret key + cookie config at import).
_TMP = tempfile.mkdtemp()
_USERS_FILE = os.path.join(_TMP, "users.json")
os.environ["USERS_FILE"] = _USERS_FILE
os.environ["SESSION_SECRET"] = "test-secret-key-do-not-use-in-prod"
os.environ["SESSION_COOKIE_SECURE"] = "0"  # allow cookie over http in the test client

import app as appmod  # noqa: E402


class EvaluateBatchWiringTests(unittest.TestCase):
    """The batch endpoint must forward the saved upload paths so matrix extraction
    runs per vendor — the same treatment the single-vendor endpoints already get.
    Without file_paths, a batch upload of a requirements matrix silently falls back
    to fuzzy retrieval (the harsh-scoring bug this feature exists to fix)."""

    def setUp(self):
        os.environ["USERS_FILE"] = _USERS_FILE
        if os.path.exists(_USERS_FILE):
            os.unlink(_USERS_FILE)
        self.client = appmod.app.test_client()
        self.client.post("/api/login",
                         json={"email": "nkramer@ssaandco.com", "password": "ServiceLogic2026!"})

    def test_batch_forwards_saved_paths_to_run_job(self):
        captured = {}
        done = threading.Event()
        real_run_job = appmod._run_job

        def spy(jid, **kw):
            captured.update(kw)
            done.set()

        appmod._run_job = spy
        try:
            data = {
                "count": "1",
                "vendor_0": "TestVendor",
                "scoring_model": "mock",
                "vote_model": "mock",
                "files_0": (io.BytesIO(b"Proposal narrative about scheduling and dispatch."),
                            "proposal.txt"),
            }
            r = self.client.post("/api/evaluate_batch", data=data,
                                 content_type="multipart/form-data")
            self.assertEqual(r.status_code, 202, r.get_data(as_text=True))
            self.assertTrue(done.wait(timeout=5), "background job was never dispatched")
        finally:
            appmod._run_job = real_run_job

        self.assertIn("file_paths", captured,
                      "batch endpoint dropped file_paths — matrix extraction will not run")
        self.assertTrue(captured["file_paths"],
                        "file_paths should be the non-empty list of saved uploads")
        self.assertTrue(all(os.path.basename(p) == "proposal.txt"
                            for p in captured["file_paths"]))


if __name__ == "__main__":
    unittest.main()
