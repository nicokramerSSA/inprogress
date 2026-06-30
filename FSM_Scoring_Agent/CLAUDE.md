# CLAUDE.md — FSM RFP Evaluation Agent

Guidance for Claude Code when working in this directory. For the full logic & design
write-up, read `docs/DESIGN.md`; for run instructions read `README.md`.

## What this is

An AI agent that scores vendor responses to the **Service Logic FSM platform RFP** and
casts an independent, **advisory** vote in vendor selection. It reasons in the voice of
Nick Kramer (SSA & Company) — a "digital twin" persona encoded as JSON, not hard-coded logic — augmented with HVAC/mechanical field-service domain knowledge. The agent is **advisory**: it augments the human selection committee, shows its work, and is meant to be challenged.

What it produces per vendor:

- A score for all **422 RFP requirements** (Met? · Quality 1–5 · response code ·
  confidence · rationale · evidence gap).
- **Two scoring lenses:** SSA scorecard categories (headline 0–100) and RFP §30
  business-capability weighting (0–100).
- **MoSCoW + architectural gating** — any unmet *Must* disqualifies (RFP §8).
- **OpCo-segment fit** across six OpCo archetypes (size / maturity / product mix / talent).
- **"Agentic future" read** — openness / data-control weighted over shipped AI features.
- A **vote** — Recommend / Shortlist / Reject / Disqualified — with narrative, steel-manned
  dissent, top risks, and evidence to close in the Charlotte demos.
- Head-to-head ranking and a retrieval-grounded **chat assistant**.

## Stack & layout

Python 3.12 / Flask backend + React-via-CDN frontend. **No database** (results cached
in-memory, seeded from JSON on boot), **no build toolchain** (no npm/TypeScript), **no
test suite**. All knowledge is editable JSON.

```
backend/
  app.py              Flask server: API routes, file/URL upload, model-selection validation,
                      serves the React frontend, seeds results from data/ on boot
  build_static.py     Bundles the whole app into ../FSM_Evaluation_Agent_Standalone.html
  requirements.txt    flask required; LLM SDKs + file parsers optional
  agent/              Core engine
    schemas.py        Typed dataclasses (RequirementScore, CategoryScore, CapabilityScore,
                      SegmentFit, GatingResult, AgenticFuture, Vote, VendorEvaluation) + to_dict()
    knowledge.py      Singleton loader for the JSON knowledge base; persona/scoring prompt builders
    providers.py      LLM abstraction (Anthropic / OpenAI / Azure / offline "mock"); reads
                      API keys from env at call time, never stores them; soft-fails on missing keys
    ingest.py         Parse proposals (PDF/DOCX/XLSX/TXT/MD) + fetch URLs + term-overlap retrieval index
    scoring.py        The engine: per-requirement scoring (batched ~12/LLM call) → category &
                      capability rollups → deterministic gating → segment fit → agentic-future read
    vote.py           Synthesizes the final recommendation, narrative, dissent, and top risks
    chat.py           Retrieval-grounded Q&A over knowledge base + completed evaluations
    sample.py         Synthetic vendor proposals for the offline demo (until real proposals arrive)
  config/             The agent's editable "character" — tune without touching code
    persona.json      Nick Kramer digital twin: decision style, priorities, red flags, voice
    scorecard.json    SSA categories, quality scale, response codes, MoSCoW, gating rules, confidence
    capabilities.json RFP §30 business capabilities (W2C/TPA/PJE/ACQ/EVG/RLC/CXR/SCL) + weights
    segments.json     Six OpCo archetypes + capability emphasis multipliers
    vendor_research.json  External research dossier per vendor (stability, HVAC fit, agentic AI, risks)
    models.json       Provider/model registry + task defaults (scoring→Sonnet, vote→Opus, chat→Haiku)
  data/
    requirements.json 422 authentic RFP requirements (RID, domain, epic, priority, capability code)
    sample_results.json  Pre-computed evaluations for the five vendors (offline demo / boot seed)
frontend/
  index.html          React 18 SPA via CDN (React + Babel), bootstrapped from window.__BOOT__
  ssa_logo_*_b64.txt  Base64 SSA logos
docs/DESIGN.md        Full design & logic documentation (9 sections)
outputs/              Generated artifacts (charts, decks)
FSM_Evaluation_Agent_Standalone.html   Pre-built offline single-file demo (double-click to run)
```

## Running it

**Offline demo (no Python, no keys):** open `FSM_Evaluation_Agent_Standalone.html` in a
browser. Five vendors pre-evaluated on synthetic proposals; live re-evaluation and chat
need the server.

**Full app (server + live models):**

```bash
cd backend
pip install -r requirements.txt    # flask required; LLM SDKs / file parsers optional
python app.py                      # → http://127.0.0.1:8000  (runs on offline "mock" engine, no keys)
```

For live models, set keys before launching and pick the model in the top-right selector:

```bash
export ANTHROPIC_API_KEY=sk-...    # Claude Opus / Sonnet / Haiku
export OPENAI_API_KEY=sk-...       # GPT-4o / GPT-4o mini
# Azure: AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT
```

Models without a present key are greyed out. `PORT` overrides the default 8000.

`RESULTS_MAX_CONCURRENCY` (default 6) caps how many LLM calls run at once across the
whole app (scoring batches + vendors share it); raise it if your provider rate limit
has headroom, lower it if you see 429s.

**Rebuild the standalone file after changes:** `cd backend && python build_static.py`
(writes `../FSM_Evaluation_Agent_Standalone.html`).

**API endpoints:** `GET /api/health · /api/models · /api/knowledge · /api/vendors ·
/api/results`; `POST /api/evaluate {vendor, use_sample|proposal_text|file_paths|urls,
scoring_model, vote_model}`; `POST /api/evaluate_upload` (multipart: `vendor, files[],
urls, scoring_model, vote_model`); `POST /api/chat {question, model_id, history}`.

## Conventions — respect these when editing

- **Persona drives every LLM call.** The `persona.json` system prompt is injected on
  every scoring/vote/chat call. Behavior changes should be expressed in the JSON knowledge
  base where possible, not in hard-coded prompt strings.
- **Gating is deterministic and never LLM-overridable.** MoSCoW and architectural gates
  are computed from the scores themselves so disqualifications stay auditable.
- **Priority-weighted rollups.** Category/capability scores weight by decision leverage:
  Must 3× · Should 2× · Could 1×. Keep this formula intact.
- **API keys come from the environment only, never written to disk.** `providers.py`
  reads them at call time and soft-fails (clear error string) when absent — the server
  must never crash on a missing key/SDK.
- **The offline "mock" engine must always work.** The full pipeline has a keyless
  rules-based fallback so the demo runs with no network. Don't break it.
- **Two scoring lenses stay independent.** SSA scorecard categories vs. RFP §30
  capabilities are separate views of the same requirement scores.
- **Auth gates the hosted app, not the data model.** `auth.py` owns the hashed-password
  user store (`USERS_FILE`) and a `require_auth` decorator on every `/api/*` route except
  health/login/logout/session. Sessions are Flask signed cookies keyed by `SESSION_SECRET`.
  Passwords are PBKDF2 hashes (werkzeug) — never plaintext, never returned by an endpoint.
  STATIC standalone builds bypass auth. The shared result store is unchanged — no per-user
  data partitioning.
- **No DB / no tests.** Results are cached in-memory and re-evaluating a vendor replaces
  its cached result. Verification is manual (offline demo + inspection).

## Status

Vendor proposals are due **July 2, 2026**. Until then the app runs on synthetic sample
proposals, grounded in the external-research dossier and clearly labelled "demo." See
`docs/DESIGN.md` §9 for full caveats.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:

- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
