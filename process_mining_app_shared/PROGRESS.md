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
