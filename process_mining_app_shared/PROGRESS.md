# FlowScope Miner — Dev Progress (Branch: dev-ap)

## Setup
- [x] Sparse-cloned repo from `nicokramerSSA/inprogress` (only `process_mining_app_shared`)
- [x] Created `dev-ap` branch — all changes go here, `main` is untouched
- [x] Created Python venv (`venv/`) with all dependencies installed
- [x] App runs locally at http://127.0.0.1:8000

## How to run the app
```bash
cd process_mining_app_shared
venv/Scripts/activate       # Windows
uvicorn backend.main:app --reload --app-dir .
```
Then open: http://127.0.0.1:8000

## Changes log

### Persistence layer (2026-04-29)
- Added `backend/database.py` — Postgres connection via `.env`, defines `projects` and `logs` tables
- Added `psycopg2-binary`, `sqlalchemy`, `python-dotenv` to `requirements.txt`
- Modified `backend/main.py`:
  - Startup hook creates DB tables automatically on first boot
  - Upload endpoint now saves raw file bytes + metadata to Postgres
  - `_get_log_or_404` checks in-memory cache first, then reloads from DB if missing (survives restarts)
  - New endpoints: `POST /api/projects`, `GET /api/projects`, `GET /api/projects/{id}/logs`, `POST /api/projects/{id}/logs/{log_id}/assign`
- Connected to Render managed Postgres (Virginia region, free tier)
- `.env` holds `DATABASE_URL`, protected from GitHub via `.gitignore`

## Architecture summary
- **In-memory cache** (`LOG_STORE`): parsed DataFrames for fast access during a session
- **Postgres** (`logs` table): raw file bytes + metadata, survives restarts
- **Projects** (`projects` table): named workspaces; logs can be assigned to a project so teams share the same data

### Frontend project UI (2026-04-29)
- Added "Step 0: Select or Create a Project" card to `index.html` above the upload form
- Added project state (`projectId`, `projectName`) to `app.js` central state object
- Added DOM references for all new project UI elements
- Added `loadProjects()` — fetches project list on page load, populates dropdown
- Added `loadProjectLogs(projectId)` — shows existing logs for selected project with Load buttons
- Added `reloadLogFromProject(logId)` — restores a previously uploaded log from DB without re-uploading
- Modified upload submit handler — after upload, auto-assigns log to selected project and refreshes log list
- Added project management CSS to `styles.css`
- Fixed health endpoint return type annotation (`dict[str, str]` → `dict[str, Any]`) for FastAPI 0.136 compatibility

### Known issue (2026-04-29)
- Multiple zombie uvicorn processes accumulate across sessions (WSL process isolation).
  **Workaround:** restart VS Code / WSL terminal between sessions to clear them.
  For development, always use a new port (`--port 8002`, `--port 8003`, etc.) if the default is taken.

### Deployed to Render (2026-04-30)
- Live URL: https://flowscope-miner.onrender.com/
- Web service connected to `nicokramerSSA/inprogress` repo, `dev-ap` branch, root dir `process_mining_app_shared`
- `DATABASE_URL` set as environment variable on Render using Internal Database URL
- Verified: projects and logs created locally are visible on Render (shared Postgres DB)
- Verified: full flow works on Render — create project, upload log, reload log across sessions

### SSA Brand Theme (2026-04-29)
- Full dark theme rewrite of `frontend/styles.css`:
  - Page background: dark navy gradient (`#001233 → #002060 → #001a4d`)
  - Cards: light gray (#f0f2f7) with near-black text and SSA Blue (#003399) headers
  - Primary buttons: SSA Blue (#003399) → Curious Blue (#0A7CC1) gradient
  - Persimmon (#DE4702) reserved for alerts, warnings, error states only
  - Muted text: #4b5873; inputs: white background with dark text
  - Process map viewport stays dark navy (#001233) for diagram contrast
- Updated `FLOW_COLORS` in `frontend/app.js` for SVG diagram colors on dark background:
  - Edge markers/secondary strokes: Nepal (#8CA3B2)
  - Backbone/anchor strokes: Eastern Blue / Curious Blue family
  - Case ball: Persimmon (#DE4702) — high contrast on dark, warm vs. cool
  - Frequency heat map: dark navy (low) → Curious Blue (high)
  - Performance heat map: dark navy (low) → Persimmon (high, signals "slow/bad")

### Per-user login and data isolation (2026-05-01)
- Replaced HTTP Basic Auth popup with a styled form-based login page (`frontend/login.html`)
- `USERS` env var replaces `APP_PASSWORD` — format: `user1:pass1,user2:pass2`
- Session cookie auth (`fs_session`) — sessions stored in-memory, cleared on server restart
- Added `owner` column to `projects` and `logs` tables (existing rows default to `flowteam`)
- DB schema migration runs automatically on startup via `migrate_schema()` (idempotent)
- All project/log DB queries now filter by owner — each login sees only their own data
- Added Sign Out button to app hero header
- Auth disabled in local dev when `USERS` env var is not set

**Render env var change required:**
- Remove `APP_PASSWORD`
- Add `USERS` = `flowteam:yourpassword,flowtestuser:theirpassword`

## Next steps
- Share URL with team: https://flowscope-miner.onrender.com/
- Note: Render free tier spins down after 15 min of inactivity — first load after idle takes ~30 sec to wake up
