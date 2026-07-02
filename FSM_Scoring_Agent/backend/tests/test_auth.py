import os
import json
import tempfile
import unittest


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["USERS_FILE"] = os.path.join(self.tmp, "users.json")
        # import after env is set so call-time reads pick up the temp path
        import importlib, auth
        importlib.reload(auth)
        self.auth = auth

    def tearDown(self):
        os.environ.pop("USERS_FILE", None)

    def test_first_load_seeds_all_accounts_and_writes_file(self):
        users = self.auth.load_users()
        self.assertEqual(len(users), 8)
        self.assertIn("nkramer@ssaandco.com", users)
        self.assertIn("jbrown@ssaandco.com", users)  # Jeff Brown provisioned
        self.assertTrue(os.path.exists(os.environ["USERS_FILE"]))

    def test_load_adds_new_seed_account_without_clobbering_changed_passwords(self):
        # Simulate the live state: an existing users file that predates a roster
        # addition (no jbrown) and in which one user already changed their password.
        import json as _json
        existing = self.auth._seed_defaults()
        existing.pop("jbrown@ssaandco.com")               # roster member not yet in file
        existing["nkramer@ssaandco.com"]["password_hash"] = \
            self.auth.generate_password_hash("nicksOwnPass1", method="pbkdf2")
        existing["nkramer@ssaandco.com"]["must_change"] = False
        with open(os.environ["USERS_FILE"], "w", encoding="utf-8") as f:
            _json.dump(existing, f)

        users = self.auth.load_users()
        # Jeff was added with the temp password...
        self.assertIn("jbrown@ssaandco.com", users)
        self.assertIsNotNone(self.auth.verify("jbrown@ssaandco.com", self.auth.TEMP_PASSWORD))
        # ...and Nick's changed password is preserved (temp no longer works, his does).
        self.assertIsNone(self.auth.verify("nkramer@ssaandco.com", self.auth.TEMP_PASSWORD))
        self.assertIsNotNone(self.auth.verify("nkramer@ssaandco.com", "nicksOwnPass1"))

    def test_seed_passwords_are_hashed_not_plaintext(self):
        users = self.auth.load_users()
        with open(os.environ["USERS_FILE"], encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(self.auth.TEMP_PASSWORD, raw)
        self.assertTrue(users["nkramer@ssaandco.com"]["password_hash"].startswith("pbkdf2:"))

    def test_verify_accepts_temp_password_case_insensitive_email(self):
        self.auth.load_users()
        rec = self.auth.verify("NKramer@ssaandco.com", self.auth.TEMP_PASSWORD)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], "Nick Kramer")

    def test_verify_rejects_wrong_password_and_unknown_email(self):
        self.auth.load_users()
        self.assertIsNone(self.auth.verify("nkramer@ssaandco.com", "nope"))
        self.assertIsNone(self.auth.verify("ghost@nowhere.com", self.auth.TEMP_PASSWORD))

    def test_set_password_changes_login_and_clears_must_change(self):
        self.auth.load_users()
        self.auth.set_password("nkramer@ssaandco.com", "brandnew123")
        self.assertIsNone(self.auth.verify("nkramer@ssaandco.com", self.auth.TEMP_PASSWORD))
        rec = self.auth.verify("nkramer@ssaandco.com", "brandnew123")
        self.assertIsNotNone(rec)
        self.assertFalse(rec["must_change"])

    def test_set_password_rejects_too_short(self):
        self.auth.load_users()
        with self.assertRaises(ValueError):
            self.auth.set_password("nkramer@ssaandco.com", "short")

    def test_existing_file_is_not_overwritten_by_seed(self):
        self.auth.load_users()
        self.auth.set_password("nkramer@ssaandco.com", "persisted123")
        # reload from disk: the changed password must survive
        import importlib, auth
        importlib.reload(auth)
        self.assertIsNotNone(auth.verify("nkramer@ssaandco.com", "persisted123"))

    def test_public_view_never_leaks_hash(self):
        users = self.auth.load_users()
        view = self.auth.public_view(users["nkramer@ssaandco.com"])
        self.assertEqual(set(view), {"name", "email", "org", "must_change"})

    def test_get_secret_key_persists_and_is_stable(self):
        k1 = self.auth.get_secret_key()
        k2 = self.auth.get_secret_key()
        self.assertEqual(k1, k2)
        self.assertGreaterEqual(len(k1), 32)


if __name__ == "__main__":
    unittest.main()
