# FlowScope Miner — Dev Progress (Branch: dev-ap)

## Setup
- [x] Sparse-cloned repo from `nicokramerSSA/inprogress` (only `process_mining_app_shared`)
- [x] Created `dev-ap` branch — all changes go here, `main` is untouched
- [x] Created Python venv (`venv/`) with all dependencies installed
- [x] App runs locally at http://127.0.0.1:8000

## How to run the app
```powershell
cd process_mining_app_shared
.\venv\Scripts\python.exe -m uvicorn backend.main:app --reload --app-dir . --port 8001
```
Then open: http://127.0.0.1:8001

> **Important — zombie server issue (Windows):** Multiple uvicorn processes can accumulate across VS Code sessions and all bind to port 8000, causing the wrong (old) server to handle requests. **Always use a port that isn't already taken** (`--port 8001`, `--port 8002`, etc.) or restart VS Code entirely before starting. To check what's on a port: `netstat -ano | findstr :8001`. To kill: `taskkill /F /PID <pid>`.

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

### Known issue — zombie uvicorn workers (2026-04-29, updated 2026-05-06)
- Windows `uvicorn --reload` spawns multiprocessing worker children. Killing the parent leaves orphan workers alive, holding the port. A new server launch silently dies (port already bound), so all requests continue to be served by the stale workers — **including routes that don't exist in the new code**. Symptom: a freshly added endpoint returns 404.
- **Diagnosis**: `Get-WmiObject Win32_Process | Where-Object { $_.Name -eq "python.exe" }` lists all Python PIDs. If more than one exists, they are likely zombie workers. Confirm by importing the app object in a fresh Python shell (`from backend.main import app; [r.path for r in app.routes]`) — if the route exists in code but the running server 404s, stale workers are serving requests.
- **Fix**: `taskkill /F /PID <pid>` for every orphan PID; then start a fresh server.
- **Prevention**: always start with an unused port (`--port 8001`, `--port 8002`, etc.); confirm startup with a `GET /health` check before testing new routes.

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

### Left-to-right process maps + white viewport (2026-05-01)
- `computeProcessLayout` in `app.js` — added `orientation: "ltr"` option; stages now spread on X axis, nodes stack vertically within each stage; returns `stageXs`, `leftAnchor`, `rightAnchor` instead of `stageYs`/`topAnchor`/`bottomAnchor`; existing TTB path unchanged (handoff views unaffected)
- Added `processEdgeGeometryLTR` — LTR edge routing: forward exits right/enters left, same-stage loops arc left, backward edges swing above/below via outer Y
- `processEdgeGeometry` now accepts `(edge, source, target, dimension, orientation)` — delegates to LTR variant when orientation is `"ltr"`
- `bpmnOrthogonalPath` — added `orientation` param; LTR mode bends at X midpoint instead of Y midpoint
- `computeBpmnGateways` — added `orientation` param; split gateways now appear to the right of source nodes and merge gateways to the left of target nodes in LTR mode
- `bpmnFlowEdgeGeometry` — updated connection points to exit right/enter left in LTR mode
- `renderBpmnFlowDiagram` — uses `orientation: "ltr"` layout; start/end events moved to left/right center; guide lines are now vertical; start→node and node→end paths flow horizontally
- Process map renderer — uses `orientation: "ltr"`; guide lines vertical; START/END anchors are vertical pills on left/right edge; anchor connection paths flow left-to-right
- `FLOW_COLORS.edgeMarker` changed to `#003399` for visibility on white background
- `frontend/styles.css` — `.process-map-viewport` background changed from `#001233` to `#ffffff`; hero card border changed to `rgba(255,255,255,0.45)` (white)
- `backend/main.py` `_report_map_svg` — rewritten to LTR layout: stages on X axis, node positions computed vertically within each stage, guide lines vertical, anchors vertical pills on left/right, edge geometry updated for LTR routing

### LTR polish — Process + BPMN Flow (2026-05-03)
- Fixed bezier control-point inversion in `processEdgeGeometryLTR`: switched from center-to-center distance to edge-to-edge (`edgeSpan = entryX - exitX`) for control-point offsets; offsets now `edgeSpan * 0.45` so they never cross when nodes are close
- Increased default stage gap: Process view `minStageGap: 400`, `stageGapBase: 340`; BPMN view same — leaves ~220 px edge-to-edge for typical 140–160 px nodes
- Node boxes narrower: `widthByFrequency = 88 + scale * 56` (was 112 + 80), max clamped to 200 px (was 268), height 50 px (was 54)
- Arrowheads fixed-size: added `markerUnits="userSpaceOnUse"` to `process-arrowhead` and `bpmn-arrowhead`; `markerWidth/Height: 9` px in canvas coordinates (was 6 × stroke-width, which ballooned to ~84 px on thick lines)
- START/END pills changed from vertical (28×96) to horizontal (72×26) pills; label text moved inside pill using `dominant-baseline="central"`; anchor path exit/entry points updated to right/left edges of horizontal pill
- Anchor X positions now computed from `leftPad`/`rightPad` minus `maxNodeHalfW + 60` so pills always sit visibly left/right of stage-0/last nodes regardless of diagram size; Process map passes `topPad: 240, bottomPad: 220` to provide adequate margin
- Node height 50→68 px; activity label 12→15 px, data/stat line 11→13 px (matching Handoff Actor sizing) across Process, BPMN Flow views and Python export
- Arrowheads scaled 9→27 px (`markerUnits="userSpaceOnUse"`); `refX` changed 7→10 so tip lands exactly at the path endpoint (node left edge) rather than 30% into the node box
- Sticky table header `background` changed from `rgba(0,51,153,0.07)` (semi-transparent) to solid `#f0f2f7` so row content no longer bleeds through while scrolling
- Node height 68→100 px; activity label 15→25 px bold, stat line 13→20 px, edge labels 12→20 px — Process, BPMN Flow, and Python export
- Filter grid 5→4 columns so datetime-local inputs have adequate width; Filter Stack column narrowed from `0.9fr / 300px` to `0.7fr / 240px`
- Play/Pause animation button: inline SVG triangle (play) and two-bar (pause) icons added; HTML initial state and both JS `textContent` → `innerHTML` assignments updated
- Added "Restart" button (`#restart-animation`) to the right of "Rewind" in the animation controls; resets frameIndex to 0 and immediately calls `startAnimation()`, always playing from the beginning

### Node / text / layout refinements (2026-05-03)
- Node height 100→200 px; activity label 25→30 px bold with multi-line SVG `<tspan>` word-wrap (`wrapActivityLabel` helper, max 4 lines); stat line 20→25 px; edge labels 20→25 px — Process, BPMN Flow, Python export
- `wrapActivityLabel` breaks on word boundaries, falls back to character-level hyphenation for long single words; `_wrap_label` Python equivalent added to `_report_map_svg`
- BPMN Flow nodes +25% wider via `nodeWidthScale: 1.25` option in `computeProcessLayout`
- START/END pill size 72×26→110×40, label 11→25 px; path connection offsets updated for new pill half-width (55px); Python export matched
- BPMN START/END circle labels 12→25 px, label y-offset +44→+54
- Handoff (Actor/Activity) arrowhead fixed to `markerUnits="userSpaceOnUse"` at 14 px (50% smaller than process/BPMN)
- Handoff diagrams pushed down 68 px by increasing topPad (Actor 142→210, Activity 190→260)
- Same gap and arrowhead fixes applied to `backend/main.py` `_report_map_svg`

### Bug fixes and diagram polish (2026-05-03, session 2)

**Critical bug fix**
- Fixed `label is not defined` ReferenceError that prevented map loading — `appendSvgTitle(label, …)` in `renderProcessMap` node loop was not updated when `const label` was renamed to `const labelEl` for tspan multi-line; changed to `appendSvgTitle(labelEl, …)`

**BPMN Flow — arrow width**
- Stroke-width multiplier bumped: `× 1.3 → × 1.95` (another 1.5× pass on top of prior session)

**BPMN Flow — node stat two-line split**
- Stat text (frequency mode) now renders as two `<tspan>` lines: `"N events"` / `"X% cases"` instead of one concatenated line
- `statGap` reduced 32→24 to accommodate second line; centering offset adjusted (`+12−17`) so the label+stat block stays vertically centered in 200 px node

**BPMN Flow — edge label visibility**
- Added semi-transparent white background rect (`opacity: 0.92, rx: 4`) behind each edge label so text is readable over colored arrow strokes
- Reordered SVG layers so `labelLayer` is appended **after** `nodeLayer` — node boxes had been painted on top of labels, clipping any label near a node edge

**Process view — node stat spacing**
- `statGap` increased 32→46 in `renderProcessMap`; centering offset adjusted (`−10`) — matches the additional breathing room added to BPMN in the same session

**BPMN Flow + Process — stat gap breathing room**
- BPMN: `statGap` 24→38, centering offset `+12→+19`
- Both views: extra vertical space between activity label text and data/stat line

**Process view — animation anchor path geometry**
- Fixed S-curve / crossing-node visual artifact: `leftAnchorX` and `rightAnchorX` formulas in `computeProcessLayout` changed from `±60` offset to `±120`, giving bezier control points clearance past stage-0/last-stage node edges

**Animation — Pause behaviour**
- `toggleAnimation()` now calls `stopAnimation({ hideOverlay: false, … })` when pausing — the map freezes on the current animation frame instead of reverting to the static (no-overlay) view

**Handoff (Actor/Activity) — node size and spacing**
- `nodeHeightOverride: 67` added to `computeProcessLayout` options in `renderGenericNetwork` — reduces node height from 200 px to ~67 px (one-third), eliminating vertical overlap between adjacent stage rows
- `horizontalGap` increased: Actor 44→80, Activity 58→100 — prevents sibling nodes in the same row from crowding each other

**Performance mode — SSA brand colour palette**
- `FLOW_COLORS` performance entries replaced with SSA blue scale:
  - `performanceNodeLow`: `#C5E7FC` (light sky blue — fast)
  - `performanceNodeMid`: `#0A7CC1` (Curious Blue)
  - `performanceNodeHigh`: `#053E60` (dark navy — slow/bottleneck)
  - `performanceEdgeLow`: `#8CA3B2`, `performanceEdgeMid`: `#0A7CC1`, `performanceEdgeHigh`: `#053E60`
- Performance-mode node text colour: `#20170e` (warm brown) → `#08152a` (dark navy) for better contrast on light-blue low-duration nodes; applied in both `renderProcessMap` and `renderBpmnFlowDiagram`

### Arrow routing and BPMN label polish (2026-05-03, session 3)

**Obstacle avoidance for backward edges**
- `processEdgeGeometry` now accepts `bounds = {}` (6th param) and passes it to `processEdgeGeometryLTR`
- TTB backward edge `outerX` replaced with bounds-aware calculation: routes 60 px outside the actual x-extent of all nodes, falling back to canvas edge only when bounds are absent
- `renderProcessMap` computes `processNodeBounds` (minNodeY / maxNodeY from positionedNodes) and passes to LTR edge call — backward arcs now clear the node cluster with 60 px margin
- `renderGenericNetwork` (Handoff views) computes `handoffNodeBounds` (minNodeX / maxNodeX) and passes to TTB edge call — Handoff backward arcs now clear node cluster

**Arrow routing — final approach (no highway, larger vertical spacing)**
- Reverted all highway routing (stageDiff > 1 multi-bezier approach) — it caused multiple highway arcs to overlap each other at the same Y corridor
- Instead: increased Process view `horizontalGap` 160 → 300 (sibling gap between nodes in same stage); added `leftPad: 120, rightPad: 100` Y-axis margins; reduced `verticalShift` 60 → 20 — canvas height auto-expands to ~920px giving bezier arcs ample vertical room
- With 300px gap between Approve Claim and Request Additional Info (same stage), any edge going from center to bottom has a natural clear corridor above the bottom-path nodes
- Handoff (Actor/Activity) TTB backward edges: changed routing to exit source BOTTOM and enter target RIGHT SIDE (or left, if source is right of target) — avoids crossing through other nodes. Path: `M src.x srcBottom C src.x srcBottom+60 entryEdgeX±60 target.y entryEdgeX target.y`
- Python `_edge_geometry` highway routing removed; backward edges in Python export use LTR above/below routing (static SVG draws edges behind node boxes so visual overlap is a non-issue there)

**BPMN Flow — arrow width fixed**
- Stroke-width multiplier reduced from `× 1.95` back to `× 0.65` — eliminates the "thick rectangle" appearance on high-frequency edges; visible range is now ~1–8 px instead of ~3–25 px

**BPMN Flow — edge labels split to two lines**
- Frequency mode arrow label split into two `<tspan>` lines: `formatNumber(edge.frequency)` / `formatPct(edge.outgoing_share)` with `dy="1.3em"` between lines
- Label y raised to `labelPoint.y - 36` and font-size reduced 25→22 px to keep block centered over arrow
- White background rect removed from edge labels (clean, no highlight)

### Analytics view palette — SSA 6-color scheme (2026-05-03, session 4)

**SSA palette applied to all remaining views (unconditionally, not gated on mode)**
- **Handoff (Actor/Activity)** — performance mode: edges use `twoStopHeat(performanceEdgeLow, …, performanceEdgeHigh, durationStrength)`; nodes use `twoStopHeat(performanceNodeLow, …, performanceNodeHigh, durationHeat^0.7)`; text flips white above 64% intensity
- **Sankey** — link stroke replaced `FLOW_COLORS.secondaryStroke()` with `twoStopHeat(performanceEdgeLow, performanceEdgeMid, performanceEdgeHigh, strength)`; node box fill `#003399` → `#336179`
- **Rework (bar chart)** — bar fill `rgba(0,51,153,…)` → `twoStopHeat(performanceNodeLow, performanceNodeMid, performanceNodeHigh, intensity)`
- **Queue Heatmap** — cell fill same `twoStopHeat` ramp; cell border stroke `rgba(0,51,153,0.18)` → `#A0C4D7`
- **Rework Treemap** — tile fill same `twoStopHeat` ramp; text contrast threshold unchanged (>0.42 = white)
- **Variant Boxplot** — row stripe `rgba(0,51,153,0.035)` → `rgba(160,196,215,0.18)`; whisker/endcap strokes `secondaryStroke()` → `#336179`; IQR box fill `rgba(0,51,153,0.74)` → `#336179`

**Arrow routing (earlier in this session)**
- Handoff (Actor/Activity) TTB forward edges replaced with orthogonal elbow routing — exits node bottom, horizontal at mid-Y inter-row gap, enters top — structurally prevents node-box overlap
- `waypointPoint(t, waypoints)` helper added for arc-length linear interpolation along polyline (used by animation dots and label midpoints on orthogonal edges)
- `geometryMidpoint(geometry)` helper checks `waypoints` first, then falls back to bezier `points` — used everywhere a label or dot needs the path midpoint
- Process view `horizontalGap` raised to 500px, `topPad: 300, bottomPad: 280` for more breathing room; bezier bypass routing reverted (accepted as known limitation)

### UI polish and diagram overhaul (2026-05-04)

**Frequency palette — all remaining tab views**
- SSA 6-color frequency palette (`#C5E7FC` → `#50B7F6` → `#053E60` for nodes; `#8ACFF9` → `#0A7CC1` → `#085D91` for edges) applied to every frequency-mode view: Handoff Actor/Activity edges and nodes, Sankey links and nodes, Rework bar chart, Queue Heatmap cells, Rework Treemap tiles, Variant Boxplot stripes/whiskers/IQR box
- Added `frequencyNodeMid` and `frequencyEdgeMid` tokens to `FLOW_COLORS` so all views pull from one source

**Sankey — label and edge fixes**
- Left/right-column labels were clipping at the SVG edge; increased `leftPad`/`rightPad` from 40 to 100 and switched text-anchor to `"start"`/`"end"` for the first and last stages
- Count line split to a second `<tspan>` on its own line below the node name

**Export HTML — START/END pills**
- Pill size halved: `pill_w/h/r` 110/40/20 → 55/20/10, font size 25 → 13
- Anchor X positions now computed post-layout using actual node half-widths to prevent pills overlapping first/last nodes

**Animation controls**
- Added SVG icons to zoom buttons: minus (−), magnifying glass, plus (+)
- Added step-back (◀) and step-forward (▶) buttons flanking the Frame slider; Frame slider `min-width` reduced 220 → 120 px to make room
- Fixed: step buttons did nothing before Play had been pressed — added `state.animation.overlayVisible = true` in both step handlers before calling `advanceAnimationFrame`
- Fixed: clicking the Frame slider caused arrow labels to flash (briefly showed frame data then reverted to static) — `change` event handler no longer clears `overlayVisible`; scrubbing the slider now immediately enters frame view and stays there
- Removed Rewind button (identical behaviour to Restart)

**Process tab — top-to-bottom orientation**
- Switched Process view from LTR to TTB layout: removed `orientation: "ltr"` from `computeProcessLayout` options
- Guide lines changed from vertical (stageXs) to horizontal (stageYs)
- START/END pills moved from `leftAnchor`/`rightAnchor` to `topAnchor`/`bottomAnchor`
- Anchor bezier paths now fan vertically (top pill → node top, node bottom → bottom pill) with adaptive control points (50% of gap) so curves scale correctly regardless of padding
- Edge geometry call changed from `"ltr"` to `"ttb"` with horizontal bounds

**Process tab — box and text sizing**
- `nodeWidthScale: 1.5` (×1.5 of base width), `nodeHeightOverride: 72`
- `minStageGap: 132`, `stageGapBase: 108` — ~60 SVG-unit gap between box rows
- `horizontalGap: 160` — sibling spacing within a stage row
- Label font 30 → 17 px, stat font 25 → 15 px, `lineH` 36 → 22, `statGap` 46 → 20
- Edge label font 25 → 18 px; position changed to `text-anchor: "start"`, `dominant-baseline: "central"`; X = `max(source.x, target.x) + 23` (path's rightmost point + ~2 character widths); Y = exact vertical midpoint between box rows

**Process tab — arrow thickness**
- Static stroke multiplier reduced: frequency `× 13 → × 5`, performance `× 12 → × 4`; backbone bonus `+1.2 → +0.6` — max backbone ~6.6 SVG units, consistent with animation inactive-edge weight so the jump on Play is minimised

**Handoff Actor — layout and thickness**
- `minStageGap` 120 → 200, `stageGapBase` 96 → 160 — ~130 SVG-unit gap between actor rows
- Static stroke multiplier `× 10 → × 7`; backbone bonus `+1.2 → +1.0`

### Log management and project UI polish (2026-05-06, session 7)

**Log deletion**
- New `DELETE /api/projects/{project_id}/logs/{log_id}` endpoint in `backend/main.py` — deletes log row from Postgres and evicts from `LOG_STORE` in-memory cache
- Trash icon button added per log row in the project logs list (`frontend/app.js`)
- Clicking trash opens a custom styled confirm modal (see below) before sending DELETE; on success removes the row from the DOM
- If the deleted log was the currently active log, resets all dashboard state (`logId`, `dashboard`, `activities`, `baseSummary`), hides dashboard, re-renders empty map, and shows status message

**Active log UI**
- Active log row shows a green **ACTIVE** badge (`#C1EFD5` fill, `#186037` text, `rgba(24,96,55,0.35)` border)
- Load button changes to **Clear** (solid `#003399` background, white text) when that log is active; tooltip "Clear page of loaded data" appears on hover
- Clicking **Clear** resets page state without deleting the log from the project
- `refreshLogRowStates()` helper syncs all row badges and buttons against `state.logId` — called after load, clear, and page init

**Log timestamp**
- Timestamp label prefixed with "Uploaded " (e.g. `Uploaded 5/6/2026, 8:43:15 AM`)

**Delete button styling**
- `.btn-delete-log`: orange-tinted ghost button (`#DE4702`) with trash-can SVG icon; hover darkens orange tint (updated from red in session 8)

### Bug fix — delete log 500 error (2026-05-06, session 8)

- **Root cause**: `DELETE` endpoint used `text("DELETE FROM logs WHERE id = :log_id::uuid …")` — SQLAlchemy's parameter parser found both `:log_id` AND `:uuid` (from the `::` PostgreSQL cast operator) as bind parameters; `uuid` was not in the params dict → unhandled `CompileError` → HTTP 500
- **Fix**: Replaced raw `text()` with `delete(logs).where(logs.c.id == log_id).where(logs.c.owner == owner)` — matches the ORM pattern used everywhere else in the file; SQLAlchemy handles UUID coercion automatically
- Added `delete` to the `from sqlalchemy import select, insert, delete` import line

### Custom confirm modal (2026-05-06, session 8)

- Replaced native `confirm()` dialog on log delete with a Promise-based `showConfirm(filename)` helper (`frontend/app.js`)
- Modal renders over a dimmed/blurred backdrop (`.confirm-overlay`), animates in via existing `@keyframes enter`, dismisses on Cancel click, Delete click, backdrop click, or Escape key
- **Orange danger color scheme** (`--danger: #DE4702`, `--danger-light: #FED8C6`) added to `:root` CSS variables
- `.btn-danger` class added — solid orange, pill-shaped, matches button radius/weight of existing button system
- Trash can icon color updated from red (`#b42828`) to orange (`#DE4702`) to match

### Sample log files added (2026-05-06, session 8)

- `sample_loan_approval_log.csv` — 12 cases (LOAN-2001–2012); actors Emma/Frank/Grace/Henry/System; paths: straight-through approval, one/two document-request loops, rejection, rejection after docs
- `sample_onboarding_log.csv` — 10 cases (EMP-3001–3010); actors HR/IT/Manager/Employee/System; paths: standard full path, reschedule orientation loop, IT equipment delay, declined offer (early exit), extended probation (second review loop)

### Delete Project feature (2026-05-06, session 9)

**Backend**
- New `DELETE /api/projects/{project_id}` endpoint in `backend/main.py`
- Cascades: fetches all log IDs for the project first, deletes all project logs via `delete(logs).where(logs.c.project_id == project_id)`, then deletes the project — all in one `engine.begin()` transaction
- Evicts deleted log IDs from `LOG_STORE` in-memory cache after the transaction commits
- Returns `{ "deleted": project_id, "logs_deleted": N }`

**Frontend**
- Delete Project button added next to the project dropdown in `index.html` — orange pill style (`.btn-delete-project`) with trash-can SVG; starts grayed out (`.no-project`) until a project is selected
- `deleteProjectBtn` added to `els` cache in `app.js`; `projectSelect` change handler and create-project handler toggle `.no-project` accordingly
- On click: opens `showConfirm()` modal with a custom title ("Delete project?") and body that names the project and warns about log cascade
- On confirm: DELETE fetch → `clearActiveLog()` if a log from that project was active → reset project state → `loadProjects()` → reset dropdown to blank

### Bug fix — DELETE project 404 (zombie uvicorn workers) (2026-05-06, session 9)

- **Symptom**: `DELETE /api/projects/{project_id}` returned 404 even though the route existed in `main.py`
- **Root cause**: 8 orphan Python/uvicorn worker processes from previous sessions were holding port 8001; each new server launch silently died (port already bound), so stale workers — which had no knowledge of the new route — continued serving all requests
- **Diagnosis**: `Get-WmiObject Win32_Process | Where-Object { $_.Name -eq "python.exe" }` revealed 8 PIDs; confirming with a fresh Python shell import (`from backend.main import app`) showed the route existed in code — divergence proved the running process was stale
- **Fix**: `taskkill /F /PID` for all 7 orphan PIDs; fresh server start resolved the 404 immediately
- See updated "Known issue" section above for full diagnosis steps and prevention

### UI polish (2026-05-06, session 9)

- **Project switch clears active log**: `projectSelect` change handler now calls `clearActiveLog()` at the top when `state.logId` is set — switching projects resets the dashboard, data fields, and process map to blank immediately
- **Matched button sizing**: `min-width: 158px; justify-content: center;` added to both `.btn-delete-project` and `#create-project-btn` so the two project-row buttons are the same width and height; `#create-project-btn` also gets `font-size: 0.875rem` to match delete button
- **Create button disabled guard**: `#create-project-btn` starts with `no-name` class in `index.html`; `input` event on `#project-name-input` toggles `no-name` live; `.btn-ghost.no-name` CSS dims to 40% opacity, suppresses hover transform, and shows a "Enter a project name to enable create" tooltip — same `position: relative` + `::after` pattern as `.btn-delete-project.no-project` and `.btn-ghost.zoom-disabled`; `no-name` is re-applied after a successful project creation clears the input

### UI overhaul — collapsible sections, section reorder, and import UX (2026-05-06, session 10)

**CSS specificity bug fix — hidden dashboard on project switch**
- Root cause: `.dashboard { display: grid }` was defined after `.hidden { display: none }` in the stylesheet; equal specificity → last rule won → `display: grid` overrode `display: none` when both classes were present
- Fix: changed `.hidden { display: none !important }` so utility class always wins regardless of declaration order

**Project switch / create always clears dashboard**
- `projectSelect` change handler: removed `if (state.logId)` guard — `clearActiveLog()` now called unconditionally on every project switch
- Create project handler: `clearActiveLog()` added immediately after the successful POST response, before updating `state.projectId`

**Paths filter default: 50% → 100%**
- `resetFiltersToDefaults()` in `app.js`: `els.pathDetail.value = "50"` → `"100"`
- HTML `value="50"` and initial label text updated to `100` / `"100% of path volume"`

**Section grouping and reorder**
- Six analysis tables (Top Paths, Variants, Bottlenecks, Activity Statistics, Rework Insights, Informational Columns) wrapped in a new `section.card.analysis-section` with heading "5. Analysis"
- Export Analysis and Export HTML Report buttons moved from the Explore and Filter header into a new `section.card.export-section` ("6. Export") at the bottom of the dashboard
- Section order in `#dashboard` changed: Summary → Process Map & Animation → Explore and Filter → Analysis → Export

**Collapsible sections**
- All seven dashboard sections and the two setup sections (Select or Create a Project, Import Event Log) are now collapsible via a `#003399` chevron button next to each heading
- Smooth slide animation via CSS `max-height` transition (0.35s ease); chevron rotates −90° when collapsed
- `localStorage` key `flowscope_collapsed` persists which sections are collapsed across page refreshes
- `expandAllSections()` clears localStorage and removes `.collapsed` from all sections — called from `clearActiveLog()` on log clear, project switch, and project create
- `section-project` and `section-upload` are excluded from localStorage restore — they always start expanded on page load (can still be manually collapsed within a session)
- Action buttons (Apply Filters / Reset for Explore and Filter; Frequency / Performance for Process Map) moved inside `.collapsible-body` so they are hidden when those sections are collapsed

**Sticky header with solid backing**
- `<header class="hero">` wrapped in `<div class="hero-strip">` which carries `position: sticky; top: 0; z-index: 200; background: #001233; padding-bottom: 10px; margin-bottom: -10px`
- Dark navy backing fills the rounded-corner transparent areas so scrolling card content does not show through
- Hero padding reduced `24px → 12px` (vertical) to make the header slightly less tall

**Section numbering and naming**
- Sections numbered 0–6: 0. Select or Create a Project, 1. Import Event Log, 2. Log Summary, 3. Process Map & Animation, 4. Explore and Filter, 5. Analysis, 6. Export
- Log Summary heading updated in HTML and in all three JS assignment sites (`clearActiveLog`, `reloadLogFromProject`, upload handler)

**Import Event Log — progressive disclosure**
- On initial load (and after every `clearActiveLog()`): only the Choose File input and a grayed-out Load Log button are visible; CSV mapping fields are hidden in `#csv-details`
- Selecting a file reveals `#csv-details` and enables the Load Log button (removes `no-file` class)
- `no-file` CSS: `opacity: 0.45`, `cursor: not-allowed`, `pointer-events: auto` (keeps hover active); `::after` tooltip "No file has been chosen" shown on hover
- `resetUploadSection()` helper resets file input, re-hides `#csv-details`, re-adds `no-file` — called from `clearActiveLog()`

### Filter group clusters and tooltips (2026-05-06, session 11)

**Grouped filter clusters in Explore and Filter**
- Replaced flat `filters-grid` with `filter-groups` — 5 labeled clusters in a 2-column layout:
  - **Time Range**: Start Time, End Time
  - **Frequency Thresholds**: Min Activity Frequency, Min Path Frequency
  - **Variant Controls**: Variant Rows, Keep Top Variants
  - **Case Duration**: Min Case Duration, Max Case Duration
  - **Activity Filters**: Keep/Exclude Cases (spans full width, `grid-column: 1 / -1`)
- Each cluster has a small uppercase navy heading (`.filter-group-label`) and subtle blue-tinted background (`rgba(0,51,153,0.05)`)
- `data-tooltip` attribute on every filter `<label>` shows ≤10-word definition on hover
- Unified `[data-tooltip]` CSS rule (was `label[data-tooltip]`) so the same pattern works on any element — covers both filter labels and the mode-toggle inactive state
- Responsive: groups collapse to 1-column at ≤1280px; inner grids collapse to 1-column at ≤900px

### Process Map & Animation panel redesign (2026-05-06, session 11)

**View tab clusters**
- Tab row split into two labeled groups separated by a subtle vertical divider:
  - **Animated Views**: Process, Handoff (Actor), Handoff (Activity)
  - **Analysis Views**: BPMN Flow, Sankey, Rework, Queue Heatmap, Rework Treemap, Variant Boxplot
- BPMN Flow moved from Animated Views to Analysis Views (no animation support)
- Each tab has a `data-tooltip` ≤10-word description on hover
- Group labels are small, muted, uppercase — low visual weight so they inform without competing

**Frequency / Performance toggle**
- Order changed: tabs first, then Frequency/Performance toggle below
- Grays out (`opacity: 0.45`, `pointer-events: none` on buttons) for pure analysis views (Sankey, Rework, Queue Heatmap, Rework Treemap, Variant Boxplot)
- Tooltip "Not applicable to this view" shown on hover when inactive (via `data-tooltip` on `.mode-toggle` wrapper)
- Remains active for BPMN Flow despite being in Analysis Views group
- `viewSupportsFreqPerf()` helper added to `app.js`; `renderCurrentMap()` toggles `.mode-toggle-inactive` class and sets/removes `data-tooltip`

**Animation controls bar**
- Always visible; grays out entirely (`.anim-controls-inactive`: `opacity: 0.45`, `pointer-events: none`) when a non-animated view is active
- Step-back (◀) and step-forward (▶) buttons moved to sit **side-by-side at the left end** of the frame slider (`.frame-slider-group` wrapper); slider extends to the right
- Timestamp label sits flush right of the group

**Map Detail sliders**
- "Map Detail" uppercase navy label added above both sliders (`.map-detail-label`)
- Both sliders now in a two-column side-by-side layout (`.detail-sliders-row` / `.detail-slider-group`)
- Each slider has ◀▶ step buttons at left end; clicking steps ±5% via `stepDown()` / `stepUp()` on the range input + synthetic `"input"` event dispatch
- New element refs: `stepBackActivity`, `stepForwardActivity`, `stepBackPath`, `stepForwardPath`

**Zoom controls**
- Removed from main control bar entirely (no more `diagram-zoom-controls` row)
- Reset Zoom button removed
- New compact `zoom-overlay` div pinned `position: absolute; top: 8px; right: 8px` inside `.map-canvas-wrapper` (`position: relative`)
- Format: 🔍 (SVG magnifying glass) `−` `78%` `+` — subtle pill with `rgba(255,255,255,0.88)` background and backdrop blur
- Does not scroll with the map; always visible in upper-right corner of canvas
- `zoomReset` element ref and event listener removed; `updateMapZoomControls` simplified

**Asset versions**: `styles.css?v=13`, `app.js?v=13`

## Next steps
- Push all local changes to Render when ready
- Share URL with team: https://flowscope-miner.onrender.com/
- Note: Render free tier spins down after 15 min of inactivity — first load after idle takes ~30 sec to wake up

### Edge label overhaul (2026-05-05, session 5)

**Animation reconfiguration fix**
- Diagram was reconfiguring mid-animation (nodes/edges appearing/disappearing during playback)
- Root cause: `preserveEdgeKeys: currentAnimationEdgeKeys()` in two `simplifyProcessGraph` calls was forcing animation-frame edges into the visible set, triggering layout changes
- Fix: removed `preserveEdgeKeys` from both `renderProcessMap` and `renderGenericNetwork` calls to `simplifyProcessGraph`
- Paths slider and other filters now remain fully interactive during animation (no locking needed)

**Two-pass edge label system**
- Replaced per-edge immediate label rendering with a collect → resolve → render pipeline
- `edgeLabelItems[]` collects `{ x, y, yOffset, text, fontSize, textAnchor, edge, source, target, ... }` for all labeled edges
- `resolveEdgeLabelCollisions(items)` — greedy vertical lane de-collision: groups items by corridor Y (`Math.round(item.y)`), sorts by X left-edge within each corridor, assigns `yOffset` from `[0, -13, 13, -26, 26, ...]` to prevent horizontal overlap; handles both `"start"` and `"middle"` text anchors correctly for xMin/xMax calculation
- `estimateLabelWidth(text, fontSize)` helper: `text.length * fontSize * 0.61`
- Labels rendered after full collection, in a `labelsLayer` painted above `nodesLayer` (layer order fix)
- Gray background rects behind labels removed

**Label positioning by edge type**
- Regular elbow/straight edges (single arrow from source): `text-anchor: "start"` anchored at `Math.max(source.x, target.x) + 23` — label sits to the right of both nodes, clear of the arrow
- Same-stage curved arcs: `text-anchor: "middle"` at `geometryMidpoint(geometry)` with `y - 15` — label floats above the arc apex
- Split-source edges (2+ arrows leaving same box): label at arc midpoint offset to the **convex/outer side** of the bend — never overlaps the arrow or animation dots

**Split-source outward offset (`geometryLabelPosition`)**
- Pre-computes `sourceOutDegreeProcess` / `sourceOutDegreeHandoff` maps before edge loop
- For edges where source has >1 outgoing connections: calls `geometryLabelPosition(geometry, source, target, 15)`
- `waypointMidTangent(t, waypoints)` — like `waypointPoint` but also returns unit tangent `(tx, ty)` at parameter `t`
- `geometryLabelPosition`: computes two perpendicular normals from tangent; picks the one with **negative dot product** against the straight-line source→target vector (= outward/convex side); offsets midpoint by 15px in that direction
- For bezier arcs (no waypoints): falls back to `mid.y - 15` (above apex)
- Applied to both `renderProcessMap` (Process tab) and `renderGenericNetwork` (Handoff Actor/Activity tabs)

### BPMN Flow — orthogonal routing and label polish (2026-05-05, session 6)

**Uniform node sizing**
- `nodeBoxDimensions` now returns a fixed `{ width: 160, height: 200 }` for all nodes — width no longer varies by label length or frequency, so all BPMN boxes are identical size

**Orthogonal edge routing**
- All BPMN Flow edges now use 90-degree (H/V only) paths with 5 px rounded corners via `bpmnOrthogonalPath`
- `bpmnFlowEdgeGeometry` refactored into distinct cases: self-loop (bezier), same-stage vertical (straight line), backward U-arc (below nodes), non-LTR fallback (bezier), skip-forward horizontal-middle, forward adjacent (orthogonal through gateways)
- **Backward edges** (e.g. RAI → Review Claim): U-arc routes below all nodes at `maxNodeY + 60`; label placed at `laneY + 30` (below arc bottom, clear of path)
- **Skip-forward edges** (e.g. Review Claim → Reject Claim): travels right at `source.y` through split gateway, descends at `mergeGw.x` (left of target column) — avoids passing through intermediate nodes in the same column
- **Same-stage vertical edges**: straight vertical line; label offset 28 px to the right of midpoint
- **Forward adjacent edges**: label anchored at `source.right + 20` with `textAnchor="start"` (grows rightward away from source node); `direction: "above"` places label 60 px above the outgoing horizontal; `direction: "below"` places it 50 px below — naturally separates two outgoing edge labels without collision resolution

**ViewBox expansion**
- BPMN Flow viewBox expands downward after layout if backward arc labels (`maxNodeY + 110`) exceed the static layout height — mirrors the Handoff diagram approach

**Handoff diagrams — text wrap and viewBox**
- Node labels now use `wrapActivityLabel` for multi-line `<tspan>` word-wrap (same helper used by Process/BPMN views)
- ViewBox expands upward to prevent loop arcs from being clipped at the top edge; `svgTop` computed from actual node bounds minus `maxLoopH`

**Two-pass label system for BPMN Flow**
- Collect → `resolveEdgeLabelCollisions` → render pipeline (same as Process/Handoff tabs)
- Vertical edges and directional (`above`/`below`) edges excluded from collision resolution (already naturally separated)
- Arc labels (`direction: "arc"`) placed at `laneY + 30` — below the backward arc horizontal, clear of the path

### Animation zoom fix and tooltip (2026-05-05, session 6)

**Zoom works when paused**
- Root cause: `stopAnimation({ hideOverlay: false })` on pause kept `overlayVisible: true`; all three zoom button handlers and `updateMapZoomControls` were gated on `overlayVisible`, so zoom was blocked even while paused
- Fix: all four checks changed from `overlayVisible` to `isPlaying` — zoom is available whenever animation is paused or stopped, only blocked while actively playing

**Zoom disabled tooltip**
- When animation is playing, zoom buttons get CSS class `zoom-disabled` instead of the `disabled` HTML attribute (which kills pointer events needed for hover)
- `.btn-ghost.zoom-disabled`: opacity 0.4, `cursor: not-allowed`, hover transform/filter suppressed
- `.btn-ghost.zoom-disabled::after`: CSS pseudo-element tooltip — "Zoom disabled while animation is playing"; dark navy background (`#1e293b`), white text, 11 px font, positioned above the button via `bottom: calc(100% + 7px)`, shown on `:hover`
- `updateMapZoomControls` now uses `classList.toggle("zoom-disabled", ...)` for the playing state and `button.disabled` only for the no-dashboard state

## Pending: arrow routing fixes

### Problem 1 — Skip-stage forward edges (READY TO BUILD)

**Root cause**: TTB forward-edge elbow uses `midY = (exitY + entryY) / 2`. For consecutive-stage edges (N → N+1) midY falls cleanly in the inter-stage gap. For skip-stage edges (N → N+2+), midY lands at the Y center of the intermediate stage row — algebraically guaranteed to hit intermediate node boxes.

**Example**: "Ticket Created" → "Triage" skips "Auto-Categorize"; the horizontal elbow segment runs straight through the Auto-Categorize box.

**Agreed approach**: Detect skip-stage forward edges (`target.stage - source.stage > 1`). Instead of entering target from the **top** with a horizontal crossing at midY, enter from the **side** using a bezier:
- `source.x < target.x` → enter target from its **LEFT** edge (`target.x - target.width/2, target.y`)
- `source.x > target.x` → enter target from its **RIGHT** edge
- Path: cubic bezier `M source.x srcBottom C source.x srcBottom+pad, entryEdgeX±pad target.y, entryEdgeX target.y`
- No horizontal crossing at any intermediate Y level → intermediate nodes cannot be hit
- Edge case: same-column skip (`|dx| < threshold`) — exit source from the side, descend, re-enter target from same side (harder, lower priority)

**Files to change**: `processEdgeGeometry` TTB branch in `frontend/app.js`; apply to Process, Handoff Actor/Activity views

### Problem 2 — Backward edges / rework loops (PARTIALLY DESIGNED, NOT READY TO BUILD)

**Root cause**: Current backward-edge bezier exits source bottom with only 60 px outPad and enters target from the side, but control points are not far enough outside to clear intermediate nodes.

**Desired behavior (Disco-style)**: Route back-edges as curved arcs that travel around the outside of the main flow — never crossing through interior nodes.

**Agreed direction for common cases**: Route to the side closest to the source node:
- `source.x < diagramCenterX` → swing **LEFT** past `bounds.minNodeX - margin`
- `source.x >= diagramCenterX` → swing **RIGHT** past `bounds.maxNodeX + margin`
- C-shaped bezier: exit source from the near side, swing to `farX`, travel vertically, enter target from the same side

**Known limitation — opposite-sides case**: When source and target are on opposite sides of the diagram (e.g., source far left, target far right), any routing must cross the interior somewhere. This is geometrically unavoidable without a full constraint-aware layout engine. Options discussed:
- A. Route to source's side anyway — crossing is minimal (short horizontal entry into target), best-effort
- B. Full orthogonal constraint routing — major scope, out of range for now
- Decision: implement common-case source-side routing first; document opposite-sides as known limitation

**Not ready to build** — need to decide: what threshold defines "same side" vs "opposite sides", and what fallback to use for the opposite-sides case before writing code.

## Open Items (post iframe-login fix)

**Safari compatibility — iframe login not supported**
The `SameSite=None; Secure` cookie fix works in Chrome and Firefox. Safari blocks all
unpartitioned third-party cookies via ITP regardless of SameSite attribute; the iframe
login will still fail silently for Safari users. Fix requires the Storage Access API:
the iframe must call `document.requestStorageAccess()`, which prompts the user once and
then allows the session cookie through. Not addressed in this PR.

**localhost in production CORS/CSRF allowlist**
`_POET_ORIGINS` includes `http://localhost:8080` for local dev convenience. This is not
a security risk (browsers enforce origin; localhost cannot be spoofed cross-origin), but
it is unusual for a production service. Future cleanup: make localhost opt-in via an
env var (e.g. `CORS_EXTRA_ORIGINS`) so production deploys have a minimal allowlist.
