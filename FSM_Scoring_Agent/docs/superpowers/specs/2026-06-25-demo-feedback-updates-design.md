# FSM Evaluation Agent — Demo-Feedback Updates (Design Spec)

Date: 2026-06-25
Source: internal demo on 2026-06-24 (`docs/FSM RFP Evaluation Agent Internal Demo_transcript.txt`)
Status: approved design, pre-implementation

## Why

The internal demo surfaced four concrete asks from the selection team (Jeff, Nick, Fred):

1. Make deal-breakers and missing pieces **front and center**, and add a **response-completeness**
   read distinct from disqualification (Jeff, Nick).
2. A clear **winner / shortlist** read so the answer isn't buried under "cool functionality" (Nick, Fred).
3. A way to **ingest all the committee's scores** and see them next to the agent's view, ending in
   a shortlist (Nick, Jeff).
4. Keep it **simple and clearly advisory** — "one more voice and a sanity check," not SSA's verdict
   (Fred, Nick, Jeff).

This spec covers all four. The vendor demos are the week of the 13th, so all four ship now.

## Out of scope (captured, not built here)

- **Anonymous vendor upload** (Jeff's SharePoint concern). This is an intake/process decision for
  Jeff and Nick, not an app change. Open process item, not implemented.
- **Raw-document section parsing** for completeness (a true "did they submit a section" check on the
  uploaded file). Completeness here is derived from scores; document parsing is a possible follow-up.
- **In-app committee score entry.** Upload only for now; an entry form is a follow-up.

## Architecture context

Python 3.12 / Flask backend + React-via-CDN frontend (`frontend/index.html`, one `<script type="text/babel">`
block). No database — results cached in-memory in `app.py`'s `_RESULTS`, seeded from `data/sample_results.json`
on boot. No build toolchain. Tabs are declared in the frontend tab array (`dashboard, detail, compare, batch,
method, chat`). Features 1, 2, and 4 derive entirely from data the app already serves (`/api/results`,
each result carrying `requirement_scores`, `gating`, `vote`, `categories`). Feature 3 adds one new backend
module and a small set of endpoints plus a new top-level tab.

The offline standalone build (`build_static.py` → `FSM_Evaluation_Agent_Standalone.html`) must keep working:
Features 1/2/4 work offline (pure derivation); committee upload soft-disables offline with a message, the
same way live evaluation already does.

---

## Feature 1 — Response completeness + red flags

### Coverage derivation (from existing scores; no new parsing)
Per vendor, over `requirement_scores` excluding `met == "N/A"`. The split is binary (no middle
bucket), keyed on whether the proposal said anything usable:
- **not addressed** (silent): `met == "No"` AND `evidence` is empty. The vendor gave no usable response.
- **addressed**: everything else — `met in {"Yes","Partial"}`, OR `met == "No"` with non-empty
  `evidence` (they responded but it fails / is inadequate, which is different from silence).
- `coverage_pct = addressed / (total - n_na) * 100`, rounded.
- Per-domain not-addressed counts → the "areas left unaddressed" list (top domains by gap count).
- `missing_musts` = not-addressed requirements whose `priority == "Must"`.

Constant: `LOW_COVERAGE_PCT = 85` (below this is flagged). Single source of truth in one helper.

### Red-flags banner (Dashboard, top)
A prominent section above the ranking. For each vendor with any red flag, one compact row:
- **Disqualified**: `DISQUALIFIED — N unmet Must requirement(s)` + the first 2–3 unmet Musts.
- **Low coverage**: `Addressed X% of requirements — left unaddressed: <domain a>, <domain b>`.
- Vendors with no red flags are summarized in one line ("3 vendors clear the gate") rather than listed.
Visual weight: this reads before the ranking table. Disqualifications use the existing `.b-Disqualified`
red styling.

### Completeness panel (Vendor detail)
A "Response completeness" block separate from the gate: coverage % (with a simple bar), counts
(addressed / partial / not addressed), and the top unaddressed areas by domain. States plainly when a
vendor scored well but left material gaps.

### Edge cases
- All addressed → coverage 100%, panel says "Full coverage." No red-flag row.
- No `requirement_scores` (shouldn't happen for seeded data) → panel shows "No scored requirements."

---

## Feature 2 — Advisory read (winner / shortlist), agent view

A top-of-Dashboard panel, above the red-flags section, in plain language:
- Headline: the agent's recommended **winner** (highest-scoring vendor that passes the gate).
- **Shortlist**: passing vendors in the Shortlist/Recommend bands, ranked.
- **Disqualified**: vendors out on the Must gate, with one-line reasons.
- A one-sentence advisory framing line (see Feature 4).

Composed from `/api/results` (existing `vote`, `weighted_total`, `gating`). Deterministic; no new model
call. If every vendor is disqualified, the headline says so honestly rather than naming a "winner."

---

## Feature 3 — Committee scorecard ingestion + side-by-side

### Backend: `backend/agent/committee.py`
- `parse_committee_file(data: bytes, filename: str) -> list[dict]`
  - CSV always (stdlib `csv`). `.xlsx` only if `openpyxl` is importable; otherwise return a clear error
    string instructing the user to upload CSV (soft-fail, never crash — consistent with provider/ingest
    conventions).
  - Tolerant header matching (case-insensitive, trims spaces/underscores). Required: `evaluator`,
    `vendor`, `score`. Optional: `verdict`, plus any of the six SSA category names as numeric columns.
  - One row per (evaluator, vendor). Coerce `score` to float 0–100; skip/collect malformed rows with a
    per-row warning rather than failing the whole file.
  - Returns normalized rows: `{evaluator, vendor, score, verdict?, categories?{...}}`.
- `aggregate_committee(rows) -> dict`
  - Per vendor: `mean_score`, `min`, `max`, `stddev`, `n_evaluators`, `verdict_counts` (mode + spread),
    optional per-category means. Plus a committee ranking by `mean_score`.
  - Returns `{vendors: [...], n_evaluators_total, warnings: [...]}`.

### Backend: `app.py` endpoints + in-memory store
- `_COMMITTEE = {}` module-level (mirrors `_RESULTS`; no DB).
- `POST /api/committee` (multipart `file`) → parse + aggregate, store, return aggregate + warnings.
- `GET /api/committee` → current aggregate (or empty shape).
- `DELETE /api/committee` → clear (lets the user re-upload cleanly).
- `GET /api/committee/template` → a sample CSV template (served from `backend/data/committee_template.csv`).

### Frontend: new top-level tab "Committee scores"
Added to the tab array as its own tab (per decision). Contents:
- Upload control (CSV/Excel) with a "download template" link; shows parse warnings inline.
- **Committee consensus** table: vendor | mean score (n=#) | score spread (min–max) | modal verdict +
  distribution, ranked by mean.
- **Side-by-side** table: vendor | committee mean | committee verdict | agent score | agent verdict |
  agent gate (PASS/DISQUALIFIED). Sorted by committee mean. **No blended number** — the two views sit
  beside each other and the human shortlist stands on the committee column.
  - Vendor name join: case-insensitive, trimmed match between committee `vendor` and the agent's
    vendor names. Committee vendors with no agent match still appear (agent columns blank); agent
    vendors absent from the upload show committee columns blank.
- Offline standalone: upload disabled with a message ("Run the server to ingest committee scores");
  the rest of the app is unaffected.

### Committee CSV template (shipped)
Columns: `evaluator,vendor,score,verdict` (+ optional category columns). A few example rows across the
five vendors so the format is obvious.

---

## Feature 4 — Advisory framing + simplicity

- A single, reusable framing line used on the Advisory read and the Committee tab:
  *"The agent's advisory view — one input to your decision, not the decision. Built to be challenged."*
- Dashboard subtitle/headers reworded so a non-technical reader gets the bottom line first.
- Keep the first screen uncluttered: advisory read → red flags → ranking → heatmap. Secondary detail
  stays one click away (vendor detail, compare, chat).
- No tone/personality changes to model output here (the persona/house-style work is separate).

---

## Data flow summary

- Features 1, 2, 4: `/api/results` → frontend derivation helpers (`deriveCompleteness`, `deriveRedFlags`,
  `deriveAdvisoryRead`) → Dashboard/VendorDetail UI. No backend change.
- Feature 3: upload → `/api/committee` → `committee.py` parse+aggregate → `_COMMITTEE` → Committee tab,
  joined with `/api/results` for the side-by-side.

## Files touched

- `backend/agent/committee.py` — new (parse + aggregate).
- `backend/app.py` — committee endpoints + `_COMMITTEE` store + template route.
- `backend/data/committee_template.csv` — new (downloadable template).
- `frontend/index.html` — tab array (+committee), Advisory read panel, Red-flags banner, Completeness
  panel in VendorDetail, Committee tab component, framing copy, derivation helpers.
- `FSM_Evaluation_Agent_Standalone.html` — rebuilt via `build_static.py` at the end.

## Testing / verification (no test framework — manual + small scripts)

- `committee.py`: a small standalone script parses the template CSV + a malformed-row CSV and prints the
  aggregate; assert mean/count/verdict distribution and that bad rows become warnings, not crashes.
- Completeness: run derivation over `sample_results.json`; confirm the two disqualified vendors surface
  unaddressed areas and the passing vendors show high coverage; spot-check counts.
- Manual: server up → Dashboard shows advisory read + red flags; vendor detail shows completeness;
  Committee tab ingests the template and renders consensus + side-by-side; offline standalone opens,
  committee upload shows the offline message, nothing crashes.
- Rebuild the standalone and confirm the new tab/panels are bundled.

## Build order

1. Frontend derivations + Advisory read + Red-flags banner + Completeness panel (Features 1, 2).
2. Framing/simplicity copy pass (Feature 4).
3. `committee.py` + endpoints + template + Committee tab (Feature 3).
4. Rebuild standalone + full manual verification.
