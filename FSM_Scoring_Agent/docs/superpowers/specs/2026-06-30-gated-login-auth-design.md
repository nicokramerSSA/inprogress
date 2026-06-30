# Gated login + self-service password reset — design spec

**Date:** 2026-06-30
**Status:** Approved for planning
**Author:** Camp Hagood (with Claude Code)

## Problem

The FSM RFP Evaluation Agent runs on a public Render URL with no access control —
anyone with the link sees vendor scores, the Nick Kramer persona, and the chat
assistant. We need a login wall so only named SSA and Bain Capital reviewers (plus a
demo account) can reach the app. Reviewers should be able to change their own password
in-app after first login. All reviewers share one evaluation dataset: a run by one user
is visible to all.

## Goals

- Gate the entire hosted app behind email + password login.
- Seed seven fixed accounts (six named reviewers + one demo), all starting on a shared
  temporary password.
- Let a logged-in user change their own password from an in-app "Account" tab.
- Keep the existing single shared result store — no per-user data partitioning. A run by
  user A is immediately visible to user B.
- Survive Render redeploys: password changes and evaluation runs persist across deploys.

## Non-goals (deliberately out of scope)

- Per-user roles or permissions. Every authenticated user has identical access.
- Email-based password recovery / "forgot password" flows. Reset is in-app only, and
  requires knowing the current password. A locked-out user is recovered by an admin
  editing the users file (see Admin recovery).
- Self-service account registration. The seven accounts are fixed; changing the roster is
  a code/data edit + redeploy.
- Guarding the prebuilt `FSM_Evaluation_Agent_Standalone.html`. That file has no server to
  authenticate against, so it stays unguarded. The login protects only the hosted Flask app.
- Forced password rotation. First-login reset is a soft nudge (banner), never mandatory
  (confirmed decision (a)).

## Seed accounts

Login identity is the email address (confirmed decision (b) — no separate username).
Emails resolved via the Microsoft 365 / Outlook connector on 2026-06-30.

| Display name | Email | Org |
|---|---|---|
| Fred Asbeck | `fasbeck@ssaandco.com` | SSA |
| Nick Kramer | `nkramer@ssaandco.com` | SSA |
| Camp Hagood | `chagood@ssaandco.com` | SSA |
| Samantha Adiwidjaja | `sadiwidjaja@ssaandco.com` | SSA |
| Kim Soviero | `ksoviero@baincapital.com` | Bain Capital |
| Emily Ashworth | `eashworth@baincapital.com` | Bain Capital |
| Demo User | `demo@servicelogic-rfp.local` | Demo |

- **Temporary password (all seven):** `ServiceLogic2026!`
- Email matching is case-insensitive (stored and compared lowercased). The demo email uses
  a non-routable `.local` domain on purpose — it is not a real mailbox.

## Architecture

Auth sits *in front* of the existing shared store. The store, scoring engine, vote, chat,
and frontend tabs are unchanged in behavior; they simply become unreachable until a valid
session cookie is present. No data model changes to evaluations.

```
Browser ──GET /api/session──▶ 401  ──▶ render Login screen
        ──POST /api/login───▶ set signed cookie ──▶ render existing App
        ──any /api/* with cookie──▶ require_auth passes ──▶ existing handlers
```

### Password hashing & sessions

- **Hashing:** `werkzeug.security.generate_password_hash` / `check_password_hash`
  (PBKDF2-SHA256, salted). Werkzeug already ships with Flask — **no new dependency**.
- **Sessions:** Flask's built-in signed-cookie session (`flask.session`), keyed by
  `SECRET_KEY`. The cookie is configured:
  - `SESSION_COOKIE_HTTPONLY = True`
  - `SESSION_COOKIE_SECURE = True` (HTTPS-only; Render serves HTTPS)
  - `SESSION_COOKIE_SAMESITE = "Lax"`
  - `PERMANENT_SESSION_LIFETIME = 7 days`; sessions are marked permanent on login.
- **`SECRET_KEY` source (in priority order):**
  1. `SESSION_SECRET` env var if set.
  2. Else a `secret_key` file on the persistent disk; generated with
     `secrets.token_hex(32)` on first boot and reused thereafter.
  This keeps existing sessions valid across restarts. If the key ever rotates, all users
  simply re-login — acceptable.

## Backend: new module `backend/auth.py`

Keeps `app.py` thin. Each function is independently testable and has one job.

**User store**
- `STORE PATH`: `USERS_FILE` env var, default `<DATA_DIR>/store/users.json`. On Render this
  is pointed at the persistent disk (see Deploy).
- `_seed_defaults()` → returns the seven seed account dicts with `generate_password_hash(TEMP_PASSWORD)`
  and `must_change=True`.
- `load_users()` → reads `users.json`. **If the file is missing, seed it and write it once.**
  If it exists, it wins — the seed never overwrites an existing file, so password changes
  are durable. One bad/unreadable file logs a warning and falls back to in-memory seeds
  (never crashes boot), mirroring `store.py`'s defensive load.
- `save_users(users)` → atomic write via temp file + `os.replace` (same pattern as
  `store.py.save`).

**User record schema** (one entry per email in a `{email: record}` map):
```json
{
  "email": "nkramer@ssaandco.com",
  "name": "Nick Kramer",
  "org": "SSA",
  "password_hash": "pbkdf2:sha256:...",
  "must_change": true,
  "updated_at": "2026-06-30T00:00:00+00:00"
}
```

**Auth operations**
- `verify(email, password) -> record | None` — lowercases email, checks hash.
- `set_password(email, new_password)` — validates length (min 8), updates hash, sets
  `must_change=False`, stamps `updated_at`, persists. Raises on too-short password.
- `public_view(record) -> {name, email, org, must_change}` — never leaks the hash.

**Session helpers**
- `get_secret_key() -> str` — resolves the Flask `SECRET_KEY` per the priority order under
  "Password hashing & sessions" (env var → disk file → generate-and-persist). Called once
  by `app.py` at config time.
- `login_user(record)` — writes `session["email"]`, marks session permanent.
- `logout_user()` — clears the session.
- `current_user() -> record | None` — resolves `session["email"]` against the store
  (returns `None` if the session points at an email no longer in the store).
- `require_auth(fn)` — decorator returning `401 {"error": "auth required"}` when
  `current_user()` is `None`.

## Backend: changes to `app.py`

**App config (after `app = Flask(...)`):**
- Set `app.secret_key` from `auth.get_secret_key()`.
- Set the four `SESSION_COOKIE_*` / lifetime config values above.

**New endpoints:**
- `POST /api/login` — body `{email, password}`. On success: `login_user`, return
  `public_view`. On failure: `401 {"error": "Invalid email or password."}` (generic
  message — do not reveal which field was wrong).
- `POST /api/logout` — `logout_user`, return `{ok: true}`.
- `GET /api/session` — return `public_view` of `current_user()`, or `401`.
- `POST /api/account/password` — `@require_auth`. Body `{current, new}`. Verify `current`
  against the logged-in user; on mismatch `400 {"error": "Current password is incorrect."}`.
  On success `set_password`, return `{ok: true}`.

**Gating existing routes:**
- Apply `@require_auth` to every `/api/*` route **except** `/api/health`, `/api/login`,
  `/api/logout`, `/api/session`. That includes `/api/models`, `/api/knowledge`,
  `/api/vendors`, `/api/results`, `/api/evaluate*`, `/api/chat`, `/api/committee*`.
- `GET /` (the SPA shell) and static assets stay open — the page itself loads, then the
  React app calls `/api/session` and shows the login screen if unauthenticated. (Serving
  the HTML shell unauthenticated is fine; it contains no evaluation data — all data comes
  from gated API calls.)
- Call `auth.load_users()` inside `_seed_results()` (or alongside it) at boot so the users
  file is seeded on first run.

## Frontend: changes to `frontend/index.html`

**Session bootstrap**
- Add `credentials:"same-origin"` to the `fetch` calls in `jget`/`jpost` (explicit; cookies
  already ride same-origin requests, but make it intentional).
- `jget`/`jpost` gain light 401 handling: on a `401`, surface an `authRequired` signal so
  the app flips back to the login screen (covers session expiry mid-use).

**Login gate (in `App`)**
- New state `auth` (`null` = unknown/loading, `false` = logged out, `record` = logged in).
- On mount, before loading models/results, call `GET /api/session`:
  - `STATIC` mode (`BOOT` present): skip auth entirely — the standalone build is ungated.
  - `401` → `setAuth(false)` and render `<Login/>`.
  - `200` → `setAuth(record)` and run the existing load sequence.
- `<Login/>` component: SSA logo, email + password fields, submit → `POST /api/login`,
  inline error line on failure. On success, store the record and proceed to the app.

**Account tab**
- Add `["account","Account"]` to the tab array.
- `<Account user={auth}/>` shows: signed-in identity (name · email · org), a change-password
  form (current / new / confirm, with client-side "new == confirm" and min-length checks),
  a success/error line wired to `POST /api/account/password`, and a **Log out** button
  (`POST /api/logout` → `setAuth(false)`).
- If `auth.must_change` is true, render a soft dismissible banner at the top of the app:
  "You're still on the temporary password — set your own under the Account tab." Non-blocking.

## Persistence / deploy (Render)

One-time setup in the Render dashboard for service `fsm-rfp-evaluation-agent`:

1. **Add a disk:** Disks → Add Disk. Mount path `/var/data`, size 1 GB.
2. **Set environment variables:**
   - `RESULTS_STORE_DIR=/var/data/results` (existing `store.py` already reads this — also
     makes evaluation runs survive deploys, fixing a latent reset-on-deploy issue).
   - `USERS_FILE=/var/data/users.json`
   - `SESSION_SECRET=<paste output of: python -c "import secrets;print(secrets.token_hex(32))">`
3. Redeploy. On first boot the users file is seeded with the seven accounts on the disk.

Until the disk is attached, the app still runs (users seed to local disk), but resets and
runs reset on each deploy — so the disk step is required for the feature to behave as
specified. This aligns with `docs/superpowers/specs/2026-06-24-disk-persistence-design.md`.

## Admin recovery (locked-out user)

Since there is no email recovery: to reset a user who forgot their changed password, an
admin edits `users.json` on the disk — delete that user's entry (it re-seeds to the temp
password on next boot with `must_change=True`) or replace `password_hash`. Document this in
the README auth section.

## Security considerations

- Passwords are never stored or logged in plaintext; only PBKDF2 hashes are persisted. The
  hash is never returned by any endpoint (`public_view` strips it).
- Login failures return a generic message and the same status for unknown-email vs
  wrong-password (no user enumeration).
- Session cookie is HTTP-only + Secure + SameSite=Lax + 7-day expiry.
- This is appropriate-for-internal protection, not bank-grade: there is no rate limiting,
  MFA, or lockout. Acceptable for a small fixed reviewer roster on a private link. Noted so
  it is a conscious choice, not an oversight.

## Acceptance criteria

1. Hitting the app URL unauthenticated shows the login screen; no vendor data, persona, or
   chat is reachable, and direct `GET /api/results` returns `401`.
2. Each of the seven seed emails logs in with `ServiceLogic2026!`.
3. A wrong password returns a generic `401` and does not log in.
4. After login, all existing tabs (Dashboard, Vendor detail, Compare, Batch, Methodology,
   Chat, Committee) work exactly as before.
5. The Account tab changes the password: after changing, the old password fails and the new
   one works; the `must_change` banner disappears.
6. A run made while logged in as user A is visible after logging in as user B (shared store).
7. Logout returns to the login screen and re-blocks the API.
8. With the Render disk attached, a password change and an evaluation run both survive a
   redeploy.
9. The standalone `FSM_Evaluation_Agent_Standalone.html` opens and works with no login
   prompt.

## Verification (no test suite in this project)

Manual, per project convention (offline demo + inspection):
- Run `python3 app.py` locally with a scratch `USERS_FILE`; walk criteria 1–7 in a browser.
- `curl -i localhost:8000/api/results` → expect `401`; then `curl` login to get the cookie
  jar, re-request with the cookie → expect `200`.
- Confirm `users.json` on disk contains hashes (no plaintext) and that deleting it re-seeds.
- Rebuild standalone (`python3 build_static.py`) and confirm criterion 9.

## File-by-file change list

- **New** `backend/auth.py` — user store, hashing, session helpers, `require_auth`.
- **Edit** `backend/app.py` — secret key + cookie config; four new endpoints; `@require_auth`
  on existing `/api/*` routes (except health/login/logout/session); seed users at boot.
- **Edit** `frontend/index.html` — `credentials` + 401 handling in `jget`/`jpost`; session
  bootstrap and `<Login/>` gate in `App`; `<Account/>` tab; `must_change` banner; STATIC
  bypass.
- **Edit** `backend/.env.example` — add `SESSION_SECRET`, `USERS_FILE`, `RESULTS_STORE_DIR`.
- **Edit** `backend/build_static.py` — confirm it does not bundle auth state and the STATIC
  build remains ungated (likely no change; verify).
- **Edit** `README.md` / `CLAUDE.md` — short auth section: accounts, temp password, reset
  tab, admin recovery, the three Render env vars + disk.

## Open decisions — resolved

- (a) First-login reset is a soft nudge, not mandatory. **Confirmed.**
- (b) Login identity is the email address, not a separate username. **Confirmed.**
- Credential persistence: Render persistent disk. **Confirmed.**
- Auth strength: hashed passwords + signed session cookie. **Confirmed.**
- Temp password: `ServiceLogic2026!`. **Confirmed.**
