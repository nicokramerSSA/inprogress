# Generalized RFP Evaluation Agent — fork design

Date: 2026-07-17
Status: approved in brainstorming; awaiting written-spec review
Author: brainstormed with Claude Code

## What this is

A fork of the FSM Scoring Agent that works for any RFP, not just the Service Logic
FSM engagement. A consultant uploads an Excel file of requirements and categories,
scores vendor proposals against it, adjusts category weights with sliders, and
stress-tests those weights with simulation before the selection committee ever meets.

The FSM app stays untouched. This is a fresh repository seeded from a cleaned
copy of the code, with no git history carried over: the parent repo's history
contains Service Logic client data (requirements, vendor research, curated
results) and must not travel into the fork. The fork lives in a new private
repository under the user's GitHub account (chagood8).

## Decisions made during brainstorming

- **Audience:** SSA consultants, one engagement at a time. Not multi-tenant, not
  client-facing. Multiple projects can exist in the database; one is active at a time.
- **Excel intake:** phased. Phase 1 ships a fixed published template with
  deterministic parsing. Phase 3 adds a column-mapping wizard for arbitrary
  spreadsheets.
- **Scoring model:** slim core, one lens. Requirements roll up to categories from
  the uploaded Excel. The FSM app's second capability lens, OpCo segment fit, and
  the vendor research dossier are cut. Vendor research becomes optional free text
  per vendor.
- **Simulation:** all three modes. Live re-rank of real evaluations, synthetic
  vendor archetypes before proposals arrive, and sensitivity analysis.
- **Persistence:** SQLite. One file on Render's disk, WAL mode, stdlib only.
  This kills the curated-seed machinery (`_merge_results`, `SEED_DEMO_RESULTS`)
  and the whole prod-seeding workaround.
- **Kept from the FSM engine:** multi-analyst panel and vote, deterministic MoSCoW
  gating (now configurable per project), retrieval-grounded chat, standalone HTML
  export.
- **Architecture:** Approach B, "project-scoped engine." Rejected: Approach A
  (config-swap of the JSON files — fights every requested feature) and Approach C
  (full platform rewrite — pays platform costs without platform users).
- **Active project is client state.** Every API call carries a `project_id`; the
  "active project" is whatever a given browser has selected. No global mutable
  server state, so two consultants can work different projects concurrently.
- **Matrix-aligned scoring is dropped from Phase 1.** `matrix_llm.py` and the
  FSM-specific matrix joins do not carry over. A generalized "vendor response
  matrix" upload (vendors answering in the buyer's own spreadsheet, mapped to
  requirement IDs for row-grounded scoring) is a Phase 3 candidate.
- **Frontend splits in Phase 1.** index.html breaks into a few
  `<script type="text/babel" src=...>` files (app shell, project setup,
  evaluation views, weight studio). Still React via CDN, still no build
  toolchain; `build_static.py` inlines them for the standalone export.

## Architecture

### Stack

Flask + React-via-CDN, no build toolchain, same as the parent app. `providers.py`
(LLM abstraction), `auth.py`, and `build_static.py` carry over with minimal changes.
The offline mock engine remains first-class: everything must work with no API keys.

### The core refactor: ProjectContext and pure rollups

Two changes make every requested feature natural instead of bolted on:

1. **`knowledge.py`'s singleton becomes `ProjectContext`.** Today the KB loads six
   JSON files once at boot and the whole engine assumes exactly one RFP exists.
   In the fork, a `ProjectContext` is loaded per request from the active project's
   rows in SQLite. Scoring, vote, gating, and chat keep their current shape but
   read from the context.

2. **Rollups leave the scoring pipeline.** Per-requirement scores are the
   expensive, immutable evidence layer: one LLM judgment per requirement per
   evaluation, written once. Everything downstream of weights becomes
   `rollup(scores, weight_profile, gating_config)` — a pure function returning
   category scores, headline number, gating verdict, and ranking. No LLM calls,
   no I/O. The weight studio calls it on every slider tick; sensitivity analysis
   brute-force sweeps it. The same math is ported to JS for client-side sliders
   and the standalone export.

### SQLite schema

- `projects` — id, name, client, status, context_brief, gating_config (JSON),
  priority_multipliers (JSON, default Must 3 / Should 2 / Could 1), created_at
- `categories` — id, project_id, name, description, default_weight, sort_order
- `requirements` — id, project_id, ext_id, text, category_id, priority
  (Must/Should/Could/Wont), section_label, notes
- `weight_profiles` — id, project_id, name, weights (JSON: category_id → weight),
  is_active, created_at. The Excel's default weights become the first profile.
- `vendors` — id, project_id, name, dossier_text
- `evaluations` — id, project_id, vendor_id, status, scoring_model, vote_model,
  vote (JSON), created_at
- `requirement_scores` — evaluation_id, requirement_id, met, quality, response_code,
  confidence, rationale, evidence_gap. Written per batch as scoring runs, which
  gives crash resumability for free.
- `scenarios` — id, project_id, name, weight_profile snapshot (JSON), archetypes
  (JSON), notes

The `context_brief` is a free-text field the consultant writes at project setup:
industry, client situation, what matters. It replaces the HVAC domain knowledge
as the persona's project flavoring and is injected into every LLM call.

### What gets deleted from the parent

`capabilities.json` (second lens), `segments.json`, `vendor_research.json` as
boot-time knowledge, `sample.py`'s five FSM vendors, segment-fit and
agentic-future stages in `scoring.py`, their sections in the vote prompt,
`matrix_llm.py` and the FSM matrix joins in `ingest.py`, and the curated-seed
machinery in `app.py`.

## Excel intake

### Phase 1: published template

The app serves a downloadable `rfp_requirements_template.xlsx` with two sheets:

- **Categories:** Category name · Description · Weight. Weights must sum to 100
  and seed the first weight profile.
- **Requirements:** ID (optional, auto-generated if blank) · Requirement text
  (required) · Category (must match a Categories row) · Priority
  (Must/Should/Could/Won't) · Section/Group (optional) · Notes (optional).

Upload flow: parse with openpyxl → validate → preview screen (counts per category
and priority, every problem listed: unknown category, missing text, weights not
summing, duplicate IDs) → consultant confirms → rows written to SQLite. Nothing
commits before confirmation.

Re-uploading requirements to a project that already has evaluations warns loudly
and offers exactly two options: replace everything (evaluations are deleted) or
abort. No partial merge in Phase 1.

MoSCoW is the only priority scheme modeled natively. Other schemes (P1–P4,
High/Med/Low) get translated at intake. Won't rows are accepted and stored for
completeness but excluded from scoring, rollups, and gating.

### Phase 3: mapping wizard

Accept any .xlsx/.csv. Show detected columns with LLM-suggested mappings; the
consultant confirms each mapping and any value translations ("P1" → Must). The
wizard produces the same normalized rows and reuses Phase 1's entire validation
and preview pipeline. It is a front-end to the same intake, not a second intake.

## Weight studio and simulation

One screen, three modes, all calling the same `rollup()` (JS port client-side).

### Sliders

One slider per category showing the active profile. Locked-total mode is the
default: moving one slider proportionally rebalances the rest so weights always
sum to 100. Free mode plus a normalize button for people who want to type numbers.
Changes are draft until saved as a named weight profile. Profiles are switchable
and comparable side by side. Priority multipliers (Must/Should/Could) are exposed
as editable knobs on the same screen — they are weights too.

### Live re-rank

When evaluations exist, slider movement recomputes every vendor's category
scores, headline number, and rank instantly, client-side. A rank strip shows
position changes. Gating verdicts do not move: disqualification is deterministic
and weight-independent, and the UI says so explicitly.

### Synthetic archetypes

Before any proposal arrives, the app generates test vendors as plausible score
vectors across the project's categories: strong-product-weak-services, cheap
generalist, premium specialist, and similar. Generation is rules-based (no LLM
required; optional LLM flavoring for names and descriptions). The consultant
drags sliders and watches which archetype wins. If the cheap generalist tops the
ranking and that feels wrong, the weights are wrong. That is the entire test.

### Sensitivity analysis

Two views, both brute-force sweeps of `rollup()`:

1. **Flip distance** — for each category, how many points its weight must move
   before the #1 vendor changes. Flags fragile rankings.
2. **Tornado view** — each category's influence on the current winner's margin.

### Scenarios

A saved scenario captures a weight profile, an archetype set, and notes, so a
consultant can bring "the three weightings the committee debated" into a meeting.

## Engine generalization

- **Persona:** `persona.json` keeps its structure (decision style, red flags,
  voice, evidence doctrine) and loses every HVAC/Service Logic reference. It
  becomes a domain-neutral evidence-first procurement evaluator. The project's
  context_brief is injected alongside it on every call. The multi-analyst panel
  and debate mechanics carry over unchanged.
- **Gating:** stays deterministic and LLM-untouchable. Becomes per-project config
  with defaults: which priorities gate (default: unmet Must → disqualify), which
  response codes count as met (the CUSTOM-meets-a-Must rule becomes a toggle),
  and DQ vs. Reject behavior. Shown on every verdict.
- **Scoring and vote:** `scoring.py` and `vote.py` keep the pipeline shape
  (batched requirement scoring → rollups → gating → panel vote) but read from
  `ProjectContext` and write to SQLite per batch.
- **Chat:** retrieval index rebuilds per project over requirements, proposals,
  evaluations, and the context brief. Same term-overlap retrieval.
- **Standalone export:** `build_static.py` becomes "snapshot this project" — the
  active project's requirements, evaluations, weight profiles, and scenarios
  embedded in one HTML file with the sliders still live (the JS rollup port makes
  this free).
- **Robustness riders:** upload size limits, OneDrive-placeholder detection
  (zero-byte or cloud-stub files get a clear error instead of silence), and
  batch-level evaluation resumability.

## Build phasing

**Phase 1 — foundation.** Seed the new private repo from a cleaned copy; strip
FSM knowledge; split the frontend into a few script files; SQLite layer and
schema; ProjectContext with per-request `project_id`; project CRUD; template
download and upload→validate→preview→confirm; extract pure `rollup()`;
per-project gating config; neutral persona + context brief; scoring/vote/chat
wired to SQLite with batch resumability. Phase 1 alone is the generalized
product: upload any RFP, score vendors against it.

**Phase 2 — weight studio.** Sliders with locked-total rebalancing; named weight
profiles; priority-multiplier knobs; client-side JS rollup; live re-rank;
synthetic archetypes; flip-distance and tornado sensitivity; saved scenarios.

**Phase 3 — reach and polish.** Column-mapping wizard; standalone HTML project
snapshot; upload robustness; requirement re-upload/versioning flow for projects
with existing evaluations; generalized vendor-response-matrix upload for
row-grounded scoring (candidate, scope when reached).

Each phase ends in a working app.

## Out of scope

Multi-tenancy and per-user data isolation; the second scoring lens; segment fit;
non-MoSCoW priority schemes as native models; any frontend build toolchain;
Postgres.

## Risks

- **The 2,078-line frontend.** index.html already strains the single-file
  approach, and the weight studio adds a whole new screen. Decision made: split
  into a few `<script type="text/babel" src=...>` files in Phase 1, before new
  screens land. No build toolchain.
- **JS/Python rollup drift.** Two implementations of the same math will diverge
  unless pinned. Mitigation: a shared JSON fixture of scores + weights + expected
  outputs, asserted by both sides. This is the one place the no-tests convention
  should bend.
- **Weight-profile semantics vs. stored votes.** A vote narrative generated under
  one weight profile references numbers that sliders can change. The UI must
  label the vote with the profile it was generated under, and offer "re-run vote"
  when the active profile differs.
