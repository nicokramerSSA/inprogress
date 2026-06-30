import os
import tempfile
import unittest

# Configure env BEFORE importing app (app reads secret key + cookie config at import).
_TMP = tempfile.mkdtemp()
_USERS_FILE = os.path.join(_TMP, "users.json")  # captured at module level; stable for setUp
os.environ["USERS_FILE"] = _USERS_FILE
os.environ["SESSION_SECRET"] = "test-secret-key-do-not-use-in-prod"
os.environ["SESSION_COOKIE_SECURE"] = "0"  # allow cookie over http in the test client

import app as appmod  # noqa: E402


class AuthApiTests(unittest.TestCase):
    def setUp(self):
        # Restore USERS_FILE in the environment before each test. test_auth.py's tearDown
        # pops the key entirely; without restoring it here, auth.load_users() would fall
        # back to the production path when both suites run under discover.
        os.environ["USERS_FILE"] = _USERS_FILE
        # Remove the users file so auth.load_users() re-seeds from defaults each test.
        # This prevents test_change_password_flow from poisoning subsequent tests that
        # rely on the original TEMP_PASSWORD.
        if os.path.exists(_USERS_FILE):
            os.unlink(_USERS_FILE)
        self.client = appmod.app.test_client()

    def login(self, email="nkramer@ssaandco.com", password="ServiceLogic2026!"):
        return self.client.post("/api/login", json={"email": email, "password": password})

    def test_health_is_open_without_login(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_results_blocked_without_login(self):
        self.assertEqual(self.client.get("/api/results").status_code, 401)

    def test_session_401_without_login(self):
        self.assertEqual(self.client.get("/api/session").status_code, 401)

    def test_login_then_session_and_results(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["name"], "Nick Kramer")
        self.assertEqual(self.client.get("/api/session").status_code, 200)
        self.assertEqual(self.client.get("/api/results").status_code, 200)

    def test_login_wrong_password_is_401_generic(self):
        r = self.login(password="wrong")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error"], "Invalid email or password.")

    def test_logout_reblocks(self):
        self.login()
        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/results").status_code, 401)

    def test_change_password_flow(self):
        self.login()
        r = self.client.post("/api/account/password",
                             json={"current": "ServiceLogic2026!", "new": "freshpass123"})
        self.assertEqual(r.status_code, 200)
        # old temp no longer works, new one does
        self.client.post("/api/logout")
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password="freshpass123").status_code, 200)

    def test_change_password_wrong_current_is_400(self):
        self.login()
        r = self.client.post("/api/account/password",
                             json={"current": "nope", "new": "freshpass123"})
        self.assertEqual(r.status_code, 400)

    def test_account_password_requires_auth(self):
        r = self.client.post("/api/account/password",
                             json={"current": "x", "new": "freshpass123"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
