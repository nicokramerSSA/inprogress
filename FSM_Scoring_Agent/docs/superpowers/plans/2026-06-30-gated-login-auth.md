# Gated Login + Self-Service Password Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the hosted FSM RFP Evaluation Agent behind an email/password login with seven seed accounts on a shared temp password, plus an in-app password-reset tab, while keeping one shared evaluation dataset.

**Architecture:** A new `backend/auth.py` owns the user store (hashed passwords in a JSON file), session helpers, and a `require_auth` decorator. `app.py` gains login/logout/session/password endpoints, signed-cookie config, and `@auth.require_auth` on every existing `/api/*` route except health/login/logout/session. The React SPA checks `/api/session` on load and renders a login screen until authenticated, with an Account tab for password change + logout. Auth sits in front of the existing shared store — no per-user data partitioning.

**Tech Stack:** Python 3.12 / Flask, Werkzeug security (PBKDF2, ships with Flask — no new dependency), Flask signed-cookie sessions, React 18 via CDN (no build step). Tests use Python stdlib `unittest` + Flask's test client.

## Global Constraints

- **No new runtime dependency.** Hashing and sessions use `werkzeug.security` and `flask.session`, both already present. (Verbatim from spec: "PBKDF2 — already ships with Flask, no new dependency".)
- **Login identity is the email address** (lowercased, case-insensitive match). No separate username.
- **Temp password for all seven seed accounts:** `ServiceLogic2026!`
- **Minimum password length:** 8 characters.
- **The offline `mock` engine and the STATIC standalone build must keep working.** STATIC mode (`window.__BOOT__` present) bypasses auth entirely — the standalone file has no server.
- **API keys / passwords are never written in plaintext or logged.** Only PBKDF2 hashes persist; the hash is never returned by any endpoint.
- **Atomic disk writes** via temp file + `os.replace` (match the existing `store.py` pattern). A failed write must never crash boot or an in-flight request.
- **Seed roster (emails resolved via Outlook 2026-06-30, stored lowercased):**
  `fasbeck@ssaandco.com` (Fred Asbeck, SSA), `nkramer@ssaandco.com` (Nick Kramer, SSA), `chagood@ssaandco.com` (Camp Hagood, SSA), `sadiwidjaja@ssaandco.com` (Samantha Adiwidjaja, SSA), `ksoviero@baincapital.com` (Kim Soviero, Bain Capital), `eashworth@baincapital.com` (Emily Ashworth, Bain Capital), `demo@servicelogic-rfp.local` (Demo User, Demo).

---

## File Structure

- **Create** `backend/auth.py` — user store, hashing, password ops, secret-key resolution, session helpers, `require_auth`. Single responsibility: authentication. Holds no Flask routes.
- **Create** `backend/tests/__init__.py` — makes `tests` a package for `unittest`.
- **Create** `backend/tests/test_auth.py` — unit tests for the non-session parts of `auth.py`.
- **Create** `backend/tests/test_auth_api.py` — Flask-test-client tests for login/logout/session/gating/password.
- **Modify** `backend/app.py` — import auth, secret-key + cookie config, seed users on boot, four new endpoints, `@auth.require_auth` on existing routes.
- **Modify** `frontend/index.html` — `credentials` + 401 handling in `jget`/`jpost`; `<Login/>` gate and `<Account/>` tab in `App`; `must_change` banner; STATIC bypass; small CSS block.
- **Modify** `backend/.env.example` — add `SESSION_SECRET`, `USERS_FILE`, `RESULTS_STORE_DIR`, `SESSION_COOKIE_SECURE`.
- **Modify** `README.md` and `CLAUDE.md` — short auth section (accounts, temp password, reset, admin recovery, Render disk + env vars).

---

### Task 1: `auth.py` — user store, password ops, secret key

**Files:**
- Create: `backend/auth.py`
- Create: `backend/tests/__init__.py`
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: nothing (leaf module). Imports `werkzeug.security`.
- Produces (used by Task 2 and `app.py`):
  - `TEMP_PASSWORD: str`, `MIN_PASSWORD_LEN: int`
  - `load_users() -> dict[str, dict]`
  - `save_users(users: dict[str, dict]) -> None`
  - `verify(email: str, password: str) -> dict | None`
  - `set_password(email: str, new_password: str) -> None` (raises `ValueError` if too short / unknown user)
  - `public_view(record: dict) -> dict` (keys: `name, email, org, must_change`)
  - `get_secret_key() -> str`

- [ ] **Step 1: Create the tests package marker**

Create `backend/tests/__init__.py` as an empty file:

```python
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_auth.py`:

```python
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

    def test_first_load_seeds_seven_accounts_and_writes_file(self):
        users = self.auth.load_users()
        self.assertEqual(len(users), 7)
        self.assertIn("nkramer@ssaandco.com", users)
        self.assertTrue(os.path.exists(os.environ["USERS_FILE"]))

    def test_seed_passwords_are_hashed_not_plaintext(self):
        users = self.auth.load_users()
        raw = open(os.environ["USERS_FILE"], encoding="utf-8").read()
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
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && python3 -m unittest tests.test_auth -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'auth'`.

- [ ] **Step 4: Write `backend/auth.py`**

Create `backend/auth.py`:

```python
"""
auth.py — authentication for the hosted FSM RFP Evaluation Agent.

Owns the user store (hashed passwords in human-inspectable JSON, one map keyed by
email), password verification/change, Flask session helpers, and the require_auth
decorator. Consistent with the project ethos: no DB, atomic JSON writes, secrets
never written in plaintext. API/data behaviour is unchanged — this only gates it.
"""
from __future__ import annotations

import os
import json
import secrets
import logging
import tempfile
from functools import wraps
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Callable

from flask import session, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

_log = logging.getLogger("auth")

TEMP_PASSWORD = "ServiceLogic2026!"
MIN_PASSWORD_LEN = 8

_HERE = os.path.dirname(os.path.abspath(__file__))

# Seed roster: (email, display name, org). Emails resolved via Outlook 2026-06-30.
_SEED_ACCOUNTS = [
    ("fasbeck@ssaandco.com", "Fred Asbeck", "SSA"),
    ("nkramer@ssaandco.com", "Nick Kramer", "SSA"),
    ("chagood@ssaandco.com", "Camp Hagood", "SSA"),
    ("sadiwidjaja@ssaandco.com", "Samantha Adiwidjaja", "SSA"),
    ("ksoviero@baincapital.com", "Kim Soviero", "Bain Capital"),
    ("eashworth@baincapital.com", "Emily Ashworth", "Bain Capital"),
    ("demo@servicelogic-rfp.local", "Demo User", "Demo"),
]


def _users_path() -> str:
    """Resolved at call time so tests (and Render) can point USERS_FILE elsewhere."""
    return os.environ.get("USERS_FILE", os.path.join(_HERE, "data", "store", "users.json"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: str, data: Dict[str, Any]) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _seed_defaults() -> Dict[str, Dict[str, Any]]:
    users: Dict[str, Dict[str, Any]] = {}
    for email, name, org in _SEED_ACCOUNTS:
        e = email.lower()
        users[e] = {
            "email": e,
            "name": name,
            "org": org,
            # Pin PBKDF2 explicitly: Werkzeug 3.x defaults to scrypt, which is
            # non-deterministic across hosts (OpenSSL memory-cost) and breaks the test.
            "password_hash": generate_password_hash(TEMP_PASSWORD, method="pbkdf2"),
            "must_change": True,
            "updated_at": _now(),
        }
    return users


def load_users() -> Dict[str, Dict[str, Any]]:
    """Load the {email: record} map. If the file is missing, seed it and write once.
    If it exists, it wins (changed passwords are never clobbered by the seed). A
    corrupt/empty file logs a warning and falls back to in-memory seeds — never crashes."""
    path = _users_path()
    if not os.path.exists(path):
        users = _seed_defaults()
        try:
            _atomic_write(path, users)
        except Exception as e:
            _log.warning("could not write seeded users file %s: %s", path, e)
        return users
    try:
        with open(path, "r", encoding="utf-8") as f:
            users = json.load(f)
        if not isinstance(users, dict) or not users:
            raise ValueError("users file empty or not an object")
        return users
    except Exception as e:
        _log.warning("unreadable users file %s: %s; using in-memory seeds", path, e)
        return _seed_defaults()


def save_users(users: Dict[str, Dict[str, Any]]) -> None:
    _atomic_write(_users_path(), users)


def public_view(record: Dict[str, Any]) -> Dict[str, Any]:
    """Safe-to-return projection. Never includes password_hash."""
    return {k: record.get(k) for k in ("name", "email", "org", "must_change")}


def verify(email: str, password: str) -> Optional[Dict[str, Any]]:
    if not email or not password:
        return None
    rec = load_users().get(email.strip().lower())
    if rec and check_password_hash(rec.get("password_hash", ""), password):
        return rec
    return None


def set_password(email: str, new_password: str) -> None:
    if not new_password or len(new_password) < MIN_PASSWORD_LEN:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    users = load_users()
    e = (email or "").strip().lower()
    rec = users.get(e)
    if not rec:
        raise ValueError("Unknown user.")
    rec["password_hash"] = generate_password_hash(new_password, method="pbkdf2")
    rec["must_change"] = False
    rec["updated_at"] = _now()
    users[e] = rec
    save_users(users)


def get_secret_key() -> str:
    """Flask SECRET_KEY: env var, else a key file next to the users file (generated
    once and reused so sessions survive restarts), else an ephemeral key."""
    env = os.environ.get("SESSION_SECRET")
    if env:
        return env
    key_path = os.path.join(os.path.dirname(_users_path()), "secret_key")
    try:
        if os.path.exists(key_path):
            with open(key_path, "r", encoding="utf-8") as f:
                k = f.read().strip()
            if k:
                return k
        k = secrets.token_hex(32)
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(k)
        return k
    except Exception as e:
        _log.warning("could not persist secret key (%s); using ephemeral key", e)
        return secrets.token_hex(32)


# ---- session helpers (used by app.py; exercised in Task 2) ----------------- #
def login_user(record: Dict[str, Any]) -> None:
    session.permanent = True
    session["email"] = record["email"]


def logout_user() -> None:
    session.pop("email", None)


def current_user() -> Optional[Dict[str, Any]]:
    email = session.get("email")
    if not email:
        return None
    return load_users().get(email)


def require_auth(fn: Callable) -> Callable:
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return jsonify({"error": "auth required"}), 401
        return fn(*args, **kwargs)
    return wrapper
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && python3 -m unittest tests.test_auth -v`
Expected: PASS — 9 tests OK.

- [ ] **Step 6: Commit**

```bash
git add backend/auth.py backend/tests/__init__.py backend/tests/test_auth.py
git commit -m "feat(auth): user store, password hashing, secret key"
```

---

### Task 2: Wire auth into `app.py` (config, endpoints, gating) + session helpers

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes (from Task 1): `auth.verify`, `auth.login_user`, `auth.logout_user`, `auth.current_user`, `auth.require_auth`, `auth.set_password`, `auth.public_view`, `auth.get_secret_key`, `auth.load_users`.
- Produces (used by Task 3 / frontend): HTTP endpoints
  - `POST /api/login {email, password}` → `200 {name,email,org,must_change}` or `401 {error}`
  - `POST /api/logout` → `200 {ok:true}`
  - `GET /api/session` → `200 {name,email,org,must_change}` or `401 {error}`
  - `POST /api/account/password {current, new}` → `200 {ok:true}` or `400 {error}`
  - All other `/api/*` (except `/api/health`) → `401 {error:"auth required"}` without a session.

- [ ] **Step 1: Write the failing API tests**

Create `backend/tests/test_auth_api.py`:

```python
import os
import tempfile
import unittest

# Configure env BEFORE importing app (app reads secret key + cookie config at import).
_TMP = tempfile.mkdtemp()
os.environ["USERS_FILE"] = os.path.join(_TMP, "users.json")
os.environ["SESSION_SECRET"] = "test-secret-key-do-not-use-in-prod"
os.environ["SESSION_COOKIE_SECURE"] = "0"  # allow cookie over http in the test client

import app as appmod  # noqa: E402


class AuthApiTests(unittest.TestCase):
    def setUp(self):
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_auth_api -v`
Expected: FAIL — `test_results_blocked_without_login` returns 200 (no gating yet) and the login/session/account endpoints 404.

- [ ] **Step 3: Add the import and config to `app.py`**

In `backend/app.py`, add `from datetime import timedelta` to the imports near the top (with the other stdlib imports, after `import uuid`).

Add `import auth` immediately after the existing `import store` line:

```python
import store  # app-layer disk persistence for runtime evaluations (sibling module)
import auth   # authentication: user store, sessions, require_auth gate
```

Then, immediately after the existing block that sets `app.config["MAX_CONTENT_LENGTH"] = ...` (right after the `app = Flask(...)` / `APP_VERSION` / `MAX_UPLOAD_MB` lines), add:

```python
# --- Authentication: signed-cookie sessions over a hashed-password user store --- #
app.secret_key = auth.get_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    # Secure by default (Render serves HTTPS). Set SESSION_COOKIE_SECURE=0 for local
    # http testing so the browser/test client will store the cookie.
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "1") != "0",
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
auth.load_users()  # seed users.json on boot (idempotent; works under gunicorn too)
```

- [ ] **Step 4: Add the four auth endpoints to `app.py`**

Insert these route handlers just before the `# Read endpoints` section header (i.e., immediately after the `index()` route that serves the SPA):

```python
# --------------------------------------------------------------------------- #
# Auth endpoints (open: login/logout/session)                                 #
# --------------------------------------------------------------------------- #
@app.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(force=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    rec = auth.verify(email, password)
    if not rec:
        # Generic message + same status for unknown-email vs wrong-password (no enumeration).
        return jsonify({"error": "Invalid email or password."}), 401
    auth.login_user(rec)
    return jsonify(auth.public_view(rec))


@app.route("/api/logout", methods=["POST"])
def logout():
    auth.logout_user()
    return jsonify({"ok": True})


@app.route("/api/session")
def session_whoami():
    rec = auth.current_user()
    if not rec:
        return jsonify({"error": "auth required"}), 401
    return jsonify(auth.public_view(rec))


@app.route("/api/account/password", methods=["POST"])
@auth.require_auth
def account_password():
    body = request.get_json(force=True) or {}
    user = auth.current_user()
    if not auth.verify(user["email"], body.get("current") or ""):
        return jsonify({"error": "Current password is incorrect."}), 400
    try:
        auth.set_password(user["email"], body.get("new") or "")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})
```

- [ ] **Step 5: Gate every existing `/api/*` route**

Add the decorator line `    @auth.require_auth` between the `@app.route(...)` decorator and the `def` for each handler below. `/api/health` and the three auth endpoints above stay open. The route decorator stays outermost; `functools.wraps` preserves each function name so Flask endpoint names remain unique.

Decorate these handlers (function name in parentheses):
- `/api/models` (`models`)
- `/api/knowledge` (`knowledge`)
- `/api/vendors` (`vendors`)
- `/api/results` (`results`)
- `/api/committee` GET (`committee_get`)
- `/api/committee` POST (`committee_post`)
- `/api/committee` DELETE (`committee_delete`)
- `/api/committee/template` (`committee_template`)
- `/api/evaluate` (`evaluate`)
- `/api/evaluate_upload` (`evaluate_upload`)
- `/api/evaluate_batch` (`evaluate_batch`)
- `/api/evaluate/status/<job_id>` (`evaluate_status`)
- `/api/evaluate/cancel/<job_id>` (`evaluate_cancel`)
- `/api/chat` (`chat`)

Example (the `results` route — apply the identical one-line insertion to each handler above):

```python
@app.route("/api/results")
@auth.require_auth
def results():
    with _RESULTS_LOCK:
        return jsonify(list(_RESULTS.values()))
```

- [ ] **Step 6: Run the API tests to verify they pass**

Run: `cd backend && python3 -m unittest tests.test_auth_api -v`
Expected: PASS — 9 tests OK.

- [ ] **Step 7: Run the full backend test set**

Run: `cd backend && python3 -m unittest discover -s tests -v`
Expected: PASS — all tests from `test_auth.py` and `test_auth_api.py` OK.

- [ ] **Step 8: Commit**

```bash
git add backend/app.py backend/tests/test_auth_api.py
git commit -m "feat(auth): login/logout/session/password endpoints + gate /api routes"
```

---

### Task 3: Frontend login gate, Account tab, must-change banner

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes (from Task 2): `GET /api/session`, `POST /api/login`, `POST /api/logout`, `POST /api/account/password`.
- Produces: a login wall before the app renders; an Account tab; session-expiry handling.

No JS unit harness exists in this project (no npm/build). Verification is via the running server + curl + browser, per project convention.

- [ ] **Step 1: Add `credentials` + 401 handling to `jget`/`jpost`**

In `frontend/index.html`, replace the non-STATIC fetch line in `jget` (currently `  const r=await fetch(API+u);return r.json();`) with:

```javascript
  const r=await fetch(API+u,{credentials:"same-origin"});
  if(r.status===401){ if(window.__onAuthExpired) window.__onAuthExpired(); return {}; }
  return r.json();
```

And replace the non-STATIC fetch line in `jpost` (currently `  const r=await fetch(API+u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});return r.json();`) with:

```javascript
  const r=await fetch(API+u,{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify(b)});
  if(r.status===401){ if(window.__onAuthExpired) window.__onAuthExpired(); return {}; }
  return r.json();
```

- [ ] **Step 2: Add `Login` and `Account` components**

Add these two components immediately above the `// ---- app ----` comment / `function App(){` line in `frontend/index.html`:

```javascript
function Login({onAuthed}){
  const [email,setEmail]=useState("");
  const [pw,setPw]=useState("");
  const [err,setErr]=useState("");
  const [busy,setBusy]=useState(false);
  const [logo,setLogo]=useState("");
  useEffect(()=>{ (async()=>{ try{ const t=await (await fetch("/ssa_logo_long_white_b64.txt")).text(); setLogo(t.trim()); }catch(e){} })(); },[]);
  async function submit(e){
    e.preventDefault(); setErr(""); setBusy(true);
    try{
      const r=await fetch("/api/login",{method:"POST",headers:{"Content-Type":"application/json"},
        credentials:"same-origin",body:JSON.stringify({email,password:pw})});
      if(!r.ok){ const d=await r.json().catch(()=>({})); setErr(d.error||"Login failed."); setBusy(false); return; }
      onAuthed(await r.json());
    }catch(e){ setErr("Network error — is the server running?"); setBusy(false); }
  }
  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        {logo ? <img src={logo} alt="SSA & Company" className="login-logo"/> : <b style={{fontSize:18}}>SSA &amp; Company</b>}
        <h1>FSM RFP Evaluation Agent</h1>
        <p className="small muted">Service Logic · sign in to continue</p>
        <label>Email<input type="email" value={email} autoFocus autoComplete="username"
          onChange={e=>setEmail(e.target.value)} required/></label>
        <label>Password<input type="password" value={pw} autoComplete="current-password"
          onChange={e=>setPw(e.target.value)} required/></label>
        {err && <div className="login-err">{err}</div>}
        <button type="submit" disabled={busy}>{busy?"Signing in…":"Sign in"}</button>
      </form>
    </div>
  );
}

function Account({user,onLogout}){
  const [cur,setCur]=useState("");
  const [nw,setNw]=useState("");
  const [conf,setConf]=useState("");
  const [msg,setMsg]=useState(null);
  const [busy,setBusy]=useState(false);
  async function submit(e){
    e.preventDefault(); setMsg(null);
    if(nw.length<8){ setMsg({ok:false,text:"New password must be at least 8 characters."}); return; }
    if(nw!==conf){ setMsg({ok:false,text:"New password and confirmation do not match."}); return; }
    setBusy(true);
    const r=await jpost("/api/account/password",{current:cur,new:nw});
    setBusy(false);
    if(r&&r.ok){ setMsg({ok:true,text:"Password updated."}); setCur("");setNw("");setConf(""); }
    else { setMsg({ok:false,text:(r&&r.error)||"Could not update password."}); }
  }
  async function logout(){ await jpost("/api/logout",{}); onLogout(); }
  return (
    <div className="card">
      <h2>Account</h2>
      <p className="small muted">Signed in as <b>{user.name}</b> · {user.email} · {user.org}</p>
      <form onSubmit={submit} style={{maxWidth:420}}>
        <label>Current password<input type="password" value={cur} autoComplete="current-password" onChange={e=>setCur(e.target.value)} required/></label>
        <label>New password<input type="password" value={nw} autoComplete="new-password" onChange={e=>setNw(e.target.value)} required/></label>
        <label>Confirm new password<input type="password" value={conf} autoComplete="new-password" onChange={e=>setConf(e.target.value)} required/></label>
        {msg && <div className={msg.ok?"login-ok":"login-err"}>{msg.text}</div>}
        <button type="submit" disabled={busy}>{busy?"Saving…":"Change password"}</button>
      </form>
      <hr style={{margin:"18px 0",border:"none",borderTop:"1px solid #e5e7eb"}}/>
      <button onClick={logout}>Log out</button>
    </div>
  );
}
```

- [ ] **Step 3: Add the auth state + session bootstrap to `App`**

In `function App(){`, add this state line directly below `const [tab,setTab]=useState("dashboard");`:

```javascript
  const [auth,setAuth]=useState(null); // null=loading, false=logged out, object=user
```

Add this NEW effect immediately above the existing `useEffect(()=>{ (async()=>{ const m=await jget("/api/models"); ...` data-loading effect:

```javascript
  useEffect(()=>{ window.__onAuthExpired=()=>setAuth(false); return ()=>{ window.__onAuthExpired=null; }; },[]);
  useEffect(()=>{(async()=>{
    if(STATIC){ setAuth({name:"Demo User",email:"demo",org:"Demo",must_change:false}); return; }
    try{ const r=await fetch("/api/session",{credentials:"same-origin"});
      setAuth(r.ok ? await r.json() : false);
    }catch(e){ setAuth(false); }
  })();},[]);
```

Change the existing data-loading effect so it only runs once authenticated. Replace its header line `  useEffect(()=>{` (the one whose body starts `    (async()=>{\n      const m=await jget("/api/models");`) and its dependency array `  },[]);` so the effect reads:

```javascript
  useEffect(()=>{
    if(!auth) return;
    (async()=>{
      const m=await jget("/api/models"); setModels(m);
```

...(body unchanged)... and its closing becomes:

```javascript
    })();
  },[auth]);
```

- [ ] **Step 4: Add the login/loading gate before the main render**

In `App`, immediately before the `return (` that renders `<div><header className="app">...`, insert:

```javascript
  if(auth===null) return <div className="login-wrap"><div className="login-card"><p className="small muted">Loading…</p></div></div>;
  if(auth===false) return <Login onAuthed={(rec)=>setAuth(rec)}/>;
```

- [ ] **Step 5: Add the Account tab + must-change banner**

In the tab array, add `["account","Account"]` as the final entry:

```javascript
        {[["dashboard","Dashboard"],["detail","Vendor detail"],["compare","Compare"],["batch","Batch evaluate"],["method","Methodology & rubric"],["chat","Ask the agent"],["committee","Committee scores"],["account","Account"]].map(([k,l])=>(
```

Immediately after the opening `<div className="wrap" ...>` line (before the `{!anyLive && ...}` banner), add the must-change banner:

```javascript
        {auth && auth.must_change && <div className="demowarn">You're still on the temporary password — set your own under the <b>Account</b> tab.</div>}
```

Add the Account tab render block alongside the other `{tab===...}` blocks (e.g., right after the `{tab==="committee" && ...}` block):

```javascript
        {tab==="account" && <Account user={auth} onLogout={()=>{setAuth(false);setTab("dashboard");}}/>}
```

- [ ] **Step 6: Add CSS for the login screen**

Append this block immediately before the closing `</style>` tag in `frontend/index.html`:

```css
.login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f172a;padding:24px;}
.login-card{background:#fff;border-radius:14px;padding:32px;width:100%;max-width:380px;box-shadow:0 12px 40px rgba(0,0,0,.35);display:flex;flex-direction:column;gap:10px;}
.login-card h1{font-size:18px;margin:6px 0 0;}
.login-logo{height:34px;align-self:flex-start;margin-bottom:6px;}
.login-card label{display:flex;flex-direction:column;font-size:13px;font-weight:600;gap:4px;margin-top:6px;}
.login-card input{padding:9px 11px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;}
.login-card button{margin-top:14px;padding:10px;border:none;border-radius:8px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer;}
.login-card button:disabled{opacity:.6;cursor:default;}
.login-err{color:#b91c1c;font-size:13px;}
.login-ok{color:#15803d;font-size:13px;}
```

- [ ] **Step 7: Verify in the browser + via curl (server running)**

Start the server: `cd backend && SESSION_COOKIE_SECURE=0 python3 app.py`

Curl checks (gating + login round-trip):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/results        # expect 401
curl -s -c /tmp/jar.txt -X POST http://127.0.0.1:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"email":"nkramer@ssaandco.com","password":"ServiceLogic2026!"}'             # expect {"must_change":true,...}
curl -s -b /tmp/jar.txt -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/api/results  # expect 200
```

Browser checklist at `http://127.0.0.1:8000`:
- Login screen appears; bad password shows the inline error.
- Correct temp password logs in; the must-change banner shows.
- All existing tabs render and load data.
- Account tab: change password to something ≥8 chars; success line shows; banner disappears.
- Log out → back to the login screen. Old password now fails; new password works.

- [ ] **Step 8: Commit**

```bash
git add frontend/index.html
git commit -m "feat(auth): login gate, Account tab, session handling in SPA"
```

---

### Task 4: Config, docs, standalone build, and Render deploy notes

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Verify (likely no change): `backend/build_static.py`

**Interfaces:**
- Consumes: env vars read by `auth.py` / `app.py` (`USERS_FILE`, `SESSION_SECRET`, `SESSION_COOKIE_SECURE`) and by `store.py` (`RESULTS_STORE_DIR`).
- Produces: documentation + the standalone-build confirmation that auth is bypassed in STATIC mode.

- [ ] **Step 1: Update `backend/.env.example`**

Replace the contents of `backend/.env.example` with:

```bash
# Copy to backend/.env and fill in. backend/.env is gitignored and never committed.
# Models without a present key are greyed out in the UI.
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
PORT=8000

# --- Auth / persistence (hosted app) ---
# Signed-session secret. Generate: python3 -c "import secrets;print(secrets.token_hex(32))"
SESSION_SECRET=
# Where the hashed-password user store lives. On Render, point this at the persistent disk.
USERS_FILE=
# Set to 0 for local http testing so the browser stores the session cookie (default: secure/HTTPS-only).
SESSION_COOKIE_SECURE=1
# Durable evaluation-results store (also makes runs survive redeploys). On Render: /var/data/results
RESULTS_STORE_DIR=
```

- [ ] **Step 2: Verify the standalone build stays ungated**

Run: `cd backend && python3 build_static.py`
Then confirm STATIC bypass works:

```bash
grep -c "window.__BOOT__" ../FSM_Evaluation_Agent_Standalone.html   # expect >= 1
```

Open `FSM_Evaluation_Agent_Standalone.html` in a browser: it must load straight to the Dashboard with **no** login prompt (STATIC sets `auth` to the demo stub). If a login prompt appears, the STATIC branch in the Step-3 session bootstrap (Task 3) is wrong — fix there. No code change expected here.

- [ ] **Step 3: Add an auth section to `README.md`**

Add this section to `README.md` (after the run/setup instructions):

```markdown
## Access control (hosted app)

The hosted app is gated by email + password. Seven seed accounts (six named reviewers
across SSA and Bain Capital, plus a Demo User) all start on the temporary password
**`ServiceLogic2026!`**. Log in with your email, then change your password under the
**Account** tab (Log out lives there too). All reviewers share one evaluation dataset —
a run by one user is visible to everyone.

The double-clickable `FSM_Evaluation_Agent_Standalone.html` has no server and is **not**
gated.

### Render setup (one-time)
1. Add a disk: mount `/var/data`, 1 GB.
2. Set env vars: `RESULTS_STORE_DIR=/var/data/results`, `USERS_FILE=/var/data/users.json`,
   `SESSION_SECRET=<token_hex(32)>`.
3. Redeploy. The user store seeds on first boot and persists across deploys.

### Recovering a locked-out user
There is no email reset. An admin edits `users.json` on the disk: delete that user's
entry (it re-seeds to the temp password with `must_change` on next boot) or replace
their `password_hash`.

### Local testing
Run with `SESSION_COOKIE_SECURE=0 python3 app.py` so the browser stores the session
cookie over http.
```

- [ ] **Step 4: Add a short auth note to `CLAUDE.md`**

Under the "Conventions" section of `FSM_Scoring_Agent/CLAUDE.md`, add this bullet:

```markdown
- **Auth gates the hosted app, not the data model.** `auth.py` owns the hashed-password
  user store (`USERS_FILE`) and a `require_auth` decorator on every `/api/*` route except
  health/login/logout/session. Sessions are Flask signed cookies keyed by `SESSION_SECRET`.
  Passwords are PBKDF2 hashes (werkzeug) — never plaintext, never returned by an endpoint.
  STATIC standalone builds bypass auth. The shared result store is unchanged — no per-user
  data partitioning.
```

- [ ] **Step 5: Run the full test set once more and commit**

Run: `cd backend && python3 -m unittest discover -s tests -v`
Expected: PASS — all tests OK.

```bash
git add backend/.env.example README.md CLAUDE.md FSM_Evaluation_Agent_Standalone.html
git commit -m "docs(auth): env example, README access-control section, CLAUDE.md note; rebuild standalone"
```

---

## Self-Review

**Spec coverage:**
- Gate whole app → Task 2 Step 5 (decorate all `/api/*`) + Task 3 login gate. ✓
- Seven seed accounts on shared temp password → Task 1 `_SEED_ACCOUNTS` + `TEMP_PASSWORD`. ✓
- Email identity, case-insensitive → Task 1 `verify`/`set_password` lowercasing + test. ✓
- In-app password reset tab → Task 3 `Account` component + Task 2 `/api/account/password`. ✓
- Shared dataset, no partitioning → no store changes; gating only. Spec acceptance #6 covered by leaving `_RESULTS` untouched. ✓
- Hashed passwords + signed cookie → Task 1 hashing/secret + Task 2 cookie config. ✓
- Survive redeploys (persistent disk) → Task 4 Step 3 Render setup + `RESULTS_STORE_DIR`/`USERS_FILE`. ✓
- Standalone stays ungated → Task 3 STATIC bypass + Task 4 Step 2 verification. ✓
- Soft must-change nudge (decision a) → Task 3 Step 5 banner (non-blocking). ✓
- First-login reset not mandatory; login by email (decision b) → reflected throughout. ✓
- Admin recovery, no enumeration, generic login error → Task 2 login handler + Task 4 README. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; commands have expected output. ✓

**Type/name consistency:** `auth.verify/set_password/public_view/login_user/logout_user/current_user/require_auth/get_secret_key/load_users/save_users` are defined in Task 1 and consumed with matching signatures in Task 2. Endpoint shapes used by Task 3 match Task 2's returns. `window.__onAuthExpired`, `setAuth(null|false|record)` consistent across Task 3 steps. ✓
