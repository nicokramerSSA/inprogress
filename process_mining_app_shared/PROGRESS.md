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

## Next steps
- Test the full project UI in browser (create project, upload log, reload log)
- Deploy to Render web service (point at dev-ap branch, set DATABASE_URL env var)
