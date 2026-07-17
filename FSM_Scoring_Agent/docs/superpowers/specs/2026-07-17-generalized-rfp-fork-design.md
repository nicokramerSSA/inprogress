# Generalized RFP Evaluation Agent — fork design

Date: 2026-07-17 (amended same day: T3 stack)
Status: approved; Phase 1 plan rewritten for T3
Author: brainstormed with Claude Code

## What this is

A ground-up rebuild of the FSM Scoring Agent's ideas for any RFP, not just the
Service Logic FSM engagement. A consultant creates a project, uploads an Excel file
of requirements + categories, scores vendor proposals against it, adjusts category
weights with sliders, and stress-tests those weights with simulation before the
selection committee ever meets.

The FSM app stays untouched. The new app lives in a new private repository under
the user's GitHub account (chagood8), built on the T3 stack from scratch. No code
is copied wholesale from the parent; what carries over is the design — data model,
scoring semantics, gating rules, prompt architecture — plus small ported artifacts
(persona structure, model registry, prompt text). Parent git history contains
Service Logic client data and must never travel into the new repo.

## Decisions made during brainstorming

- **Audience:** SSA consultants, one engagement at a time. Not multi-tenant, not
  client-facing. Multiple projects can exist in the database; selection is
  per-browser.
- **Stack (amended):** T3 — Next.js (App Router) + TypeScript + tRPC + Prisma on
  SQLite + Tailwind + Auth.js, tested with Vitest. Deployed as a long-running Node
  server on Render (`next start`), NOT serverless: evaluations are minutes-long
  background jobs that run in-process. This supersedes the original "keep
  Flask + React-CDN" decision; the user chose the rewrite knowingly, because the
  Phase 2 weight studio is exactly the UI a real toolchain is for.
- **Excel intake:** phased. Phase 1 ships a fixed published template with
  deterministic parsing (exceljs). Phase 3 adds a column-mapping wizard for
  arbitrary spreadsheets.
- **Scoring model:** slim core, one lens. Requirements roll up to categories from
  the uploaded Excel. The FSM app's second capability lens, OpCo segment fit, and
  the vendor research dossier are cut. Vendor research becomes optional free text
  per vendor.
- **Simulation:** all three modes. Live re-rank of real evaluations, synthetic
  vendor archetypes before proposals arrive, and sensitivity analysis.
- **Persistence:** SQLite via Prisma. One file on Render's disk, survives
  restarts. No curated-seed machinery, ever.
- **Kept from the FSM design:** multi-analyst evaluator persona and vote,
  deterministic MoSCoW gating (configurable per project), retrieval-grounded chat,
  and (Phase 3) a shareable static project snapshot.
- **Matrix-aligned scoring is dropped from Phase 1.** A generalized "vendor
  response matrix" upload (vendors answering in the buyer's own spreadsheet,
  mapped to requirement IDs for row-grounded scoring) is a Phase 3 candidate.
- **Active project is client state.** Every tRPC call carries a `projectId`; the
  "active project" is whatever a given browser has selected. No global mutable
  server state, so two consultants can work different projects concurrently.
- **Rejected paths:** Approach A (config-swap of the parent's JSON files — fights
  every requested feature); building Phase 1 on Flask first and migrating to T3
  after (the app would be written twice).

## Architecture

### The core split: evidence vs. judgment

Per-requirement scores are the expensive, immutable evidence layer: one LLM
judgment per requirement per evaluation, written once. Everything downstream of
weights is `rollup(scores, categories, weights, priorityMultipliers, gatingConfig)`
— a pure TypeScript function returning category scores, headline number, gating
verdict, and ranking. No I/O, no LLM. The same function runs on the server (results
endpoint) and in the browser (Phase 2 sliders) — one implementation, so the
Python/JS drift risk from the original design no longer exists.

### Data model (Prisma over SQLite)

- `Project` — name, client, status, contextBrief, gatingConfig (JSON string),
  priorityMultipliers (JSON string, default Must 3 / Should 2 / Could 1), createdAt
- `Category` — per project: name, description, defaultWeight, sortOrder
- `Requirement` — per project: extId, text, categoryId, priority
  (Must/Should/Could/Wont), sectionLabel, notes; unique (projectId, extId)
- `WeightProfile` — per project, named weight sets (JSON: categoryId → weight);
  one active; the Excel's default weights become the first profile
- `Vendor` — per project: name, dossierText; unique (projectId, name)
- `Evaluation` — project, vendor, status (running/done/failed/cancelled),
  scoringModel, voteModel, vote (JSON), engineWarning, isDemo, proposalText
- `RequirementScore` — one row per requirement per evaluation: met, quality,
  responseCode, confidence, rationale, evidenceGap, scoredLive; PK
  (evaluationId, requirementId). Written per batch as scoring runs — that is the
  crash-resumability mechanism.
- `Scenario` — saved simulation states (weights + archetypes + notes), Phase 2

The `contextBrief` is free text the consultant writes at project setup: industry,
client situation, what matters. It replaces the parent's HVAC domain knowledge as
the persona's project flavoring and is injected into every LLM call.

### Engine (TypeScript port of the parent's design)

- **Providers:** a thin LLM abstraction over the Anthropic and OpenAI TS SDKs plus
  a keyless deterministic mock. API keys from env at call time, never disk;
  missing key = clear error string, never a crash. The parent's `models.json`
  registry (provider/model IDs, task defaults) is carried over as data.
- **Scoring:** batched ~12 requirements per LLM call, retrieval-grounded from the
  proposal text (term-overlap index, ported logic), with an `onBatch` persistence
  callback and mock fallback per batch. Response codes kept: OOB, CONFIG,
  EXTENSION, CUSTOM, PARTNER, ROADMAP, GAP.
- **Gating:** deterministic and LLM-untouchable, per-project config with defaults:
  unmet Must → disqualify; GAP and ROADMAP gate; CUSTOM does not (toggle).
- **Vote:** deterministic band from the weighted total (gating verdict wins),
  LLM-written narrative/dissent/risks that may not change the recommendation.
- **Chat:** retrieval-grounded Q&A per project over requirements, proposals,
  evaluations, and the context brief.
- **Persona:** the parent persona's structure (decision style, red flags, voice,
  evidence doctrine) rewritten domain-neutral, stored as JSON config in the new
  repo, injected with the contextBrief on every call.

### Long-running evaluations

An in-process job registry (Map of jobId → status/progress/cancel flag) with the
evaluation loop running as an async task inside the Node server. Fine for a
single-instance internal tool on Render. If the app ever scales past one instance,
that is the moment to add a real queue — explicitly out of scope now.

## Excel intake

### Phase 1: published template

The app serves a generated `rfp_requirements_template.xlsx` (exceljs) with two
sheets plus instructions:

- **Categories:** Category name · Description · Weight. Weights must sum to 100
  and seed the first weight profile.
- **Requirements:** ID (optional, auto-generated if blank) · Requirement text
  (required) · Category (must match a Categories row) · Priority
  (Must/Should/Could/Won't) · Section/Group (optional) · Notes (optional).

Upload flow: parse → validate → preview (counts per category and priority, every
problem listed: unknown category, missing text, weights not summing, duplicate
IDs) → consultant confirms → rows written in one transaction. Nothing commits
before confirmation. Re-uploading to a project that already has evaluations warns
loudly and offers exactly two options: replace everything (evaluations deleted) or
abort. No partial merge in Phase 1.

MoSCoW is the only priority scheme modeled natively; other schemes get translated
at intake. Won't rows are stored for completeness but excluded from scoring,
rollups, and gating. Upload robustness from day one: size limit, zero-byte
(OneDrive placeholder) detection with a plain-language error.

### Phase 3: mapping wizard

Accept any .xlsx/.csv; LLM-suggested column mappings the consultant confirms,
producing the same normalized rows through the same validation pipeline.

## Weight studio and simulation (Phase 2)

One screen, three modes, all calling the same shared `rollup()`:

- **Sliders** — one per category, locked-total proportional rebalancing by
  default, free mode + normalize button; draft until saved as a named profile;
  priority multipliers exposed as knobs on the same screen.
- **Live re-rank** — slider movement recomputes every vendor's scores and rank
  instantly client-side; gating verdicts never move and the UI says so.
- **Synthetic archetypes** — rules-based hypothetical vendors (strong-product-
  weak-services, cheap generalist, premium specialist…) so weights can be
  stress-tested before proposals arrive. If the cheap generalist tops the ranking
  and that feels wrong, the weights are wrong — that is the whole test.
- **Sensitivity** — flip distance per category (how far a weight must move to
  change #1) and a tornado view of each category's influence on the winner's
  margin. Brute-force sweeps of `rollup()`.
- **Scenarios** — saved weight profile + archetype set + notes, so a consultant
  can bring "the three weightings the committee debated" into a meeting.

## Build phasing

**Phase 1 — foundation.** `create-t3-app` scaffold in the new private repo;
Prisma schema; shared pure `rollup()` with a hand-verified test fixture; neutral
persona + contextBrief injection; project/vendor CRUD; template download; intake
parse→validate→preview→confirm; TS provider layer with mock engine; batched
scoring with per-batch persistence and resume; deterministic vote bands + LLM
narrative; per-project chat; Auth.js credentials login; project screens
(picker/setup/intake/evaluate/results/chat). Phase 1 alone is the generalized
product: upload any RFP, score vendors against it, keyless end to end on the mock
engine.

**Phase 2 — weight studio.** Sliders with locked-total rebalancing; named weight
profiles; priority-multiplier knobs; live re-rank; synthetic archetypes;
flip-distance and tornado sensitivity; saved scenarios.

**Phase 3 — reach and polish.** Column-mapping wizard; shareable static project
snapshot (a self-contained export of one project's results and sliders);
requirement re-upload/versioning flow; generalized vendor-response-matrix upload
for row-grounded scoring (candidate, scope when reached).

## Out of scope

Multi-tenancy and per-user data isolation; the second scoring lens; segment fit;
non-MoSCoW priority schemes as native models; Postgres; job queues / multi-instance
deployment; Vercel serverless deployment (the app needs a long-running server).

## Risks

- **Document parsing in the JS ecosystem.** The parent leaned on pypdf /
  python-docx / openpyxl, which are more battle-tested than pdf-parse / mammoth /
  exceljs. Intake and proposal ingest need testing against ugly real-world files
  early; Phase 1 scopes proposal ingest to pasted text + .txt/.md/.xlsx uploads,
  with PDF/DOCX added behind the same interface once exercised.
- **Engine rewrite risk.** The scoring prompts and mock heuristics are ports, not
  copies — behavior can drift from the parent. Mitigation: the rollup fixture and
  scoring tests pin the deterministic parts; prompt text is carried over verbatim
  where it was working.
- **Weight-profile semantics vs. stored votes.** A vote narrative generated under
  one weight profile references numbers that sliders can change. The UI must
  label the vote with the profile it was generated under, and offer "re-run vote"
  when the active profile differs.
