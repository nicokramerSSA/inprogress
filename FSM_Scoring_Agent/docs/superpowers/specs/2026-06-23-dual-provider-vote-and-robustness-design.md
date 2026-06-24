# Design — Dual-Provider Vote, `.env` Loading, and Critical Robustness

**Date:** 2026-06-23
**Status:** Approved design, pending spec review
**Author:** Camp Hagood / Claude (pairing)
**Scope of this spec:** build the three explicit asks (`.env`, dual-provider vote synthesis, split model UI) plus the must-fix robustness items. The rest of the gap analysis is captured as a roadmap (§9) but **not** built this round.

---

## 1. Background & problem

The FSM RFP Evaluation Agent is functionally complete for the offline demo: the full pipeline (per-requirement scoring → category/capability rollups → deterministic gating → segment fit → agentic-future → vote synthesis) works, all four frontend tabs render live data, and the keyless mock engine runs with zero API keys.

Three things are missing or broken for live use:

1. **No `.env` loading.** `providers.py` reads keys from `os.environ` only; the user must `export` them every shell session.
2. **No dual-provider synthesis.** Every LLM call is single-model. The user wants the **vote** produced by both OpenAI and Anthropic independently, then reconciled by Anthropic (Opus 4.8), so differing outputs for the same task are visible and a single model's bias is checked.
3. **A config-breaking API bug (newly found).** `providers.py._anthropic()` always sends `temperature` to the Anthropic SDK. On `claude-opus-4-8` and `claude-opus-4-7`, sampling parameters (`temperature`/`top_p`/`top_k`) were **removed** and now return HTTP 400. Because the provider layer fail-soft-swallows errors, every Opus vote silently falls back to deterministic placeholder text — and the user's chosen config (Opus 4.8 as both Anthropic vote model **and** synthesizer) would never produce real output. This must be fixed before the dual-vote feature can work at all.

Plus several operational gaps that will bite the moment real proposals are scored with a live key: synchronous request-blocking evaluations (~3–5 min), no retry/backoff, parser/file-size fragility.

### Decisions locked during brainstorming

| Question                                   | Decision                                                                                                                                                                               |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Which task(s) get dual-provider synthesis? | **Vote only.** Scoring stays single-model.                                                                                                                                             |
| Build now vs. roadmap?                     | **Asks + critical robustness.** Export/persistence/auth/etc. are roadmap.                                                                                                              |
| What does the UI show for a dual vote?     | **Both raw votes + the reconciliation, with disagreements flagged.**                                                                                                                   |
| Keys on hand today?                        | **Anthropic only.** Must degrade to single-provider gracefully and auto-upgrade to dual when an OpenAI key is added.                                                                   |
| Default dual-vote model pair?              | **OpenAI GPT-5.5 + Anthropic Opus 4.8; reconciler = Opus 4.8.** GPT-5.5 model id to be verified against OpenAI's current list when the OpenAI key is added (not exercised until then). |

### Invariants this design must preserve (from `CLAUDE.md`)

- Persona JSON drives every LLM call; behavior changes live in JSON where possible.
- Gating is deterministic and never LLM-overridable.
- Priority-weighted rollups (Must 3× / Should 2× / Could 1×) stay intact.
- API keys come from the environment only, never written to disk.
- The offline mock engine must always work with no network.
- The two scoring lenses stay independent.
- No DB, no test suite; verification is manual (offline demo + inspection).

---

## 2. Goals / non-goals

**Goals**

- `.env` loading so the user drops a key into `backend/.env` and runs.
- Fix the Opus sampling-parameter 400 centrally so scoring, vote, dual-vote, and chat all work on Opus.
- Dual-provider vote: two independent votes + Anthropic reconciliation, with graceful single-provider degradation.
- UI to choose scoring model and vote mode (single model or dual pair) independently, and to render the two-model read with disagreements.
- Critical robustness: background-job evaluation with progress + cancel, retry/backoff on transient provider errors, fail-soft ingestion (size cap + missing-parser handling), basic SSRF guard.

**Non-goals (this round)**

- Dual-provider scoring or chat (vote only).
- Export (PDF/PPTX/CSV), disk persistence, auth/rate-limiting, LLM-call caching, compare view, accessibility overhaul. All in §9 roadmap.
- Any change to the gating logic, rollup weighting, or the two-lens model.

---

## 3. §0 Prerequisite — fix the Opus sampling-parameter 400

**Why first:** the dual-vote feature is Opus-driven; until this is fixed, the feature cannot produce real output.

### 3.1 `config/models.json`

- Add `"sampling_params": false` to the model objects for `claude-opus-4-8` and `claude-opus-4-7`. (Sonnet 4.6 and Haiku 4.5 keep the default — they still accept `temperature`.)
- Add a new OpenAI model entry for **GPT-5.5** with a clearly-commented placeholder id (`"gpt-5.5"`) and a `"verify_id": true` marker. Add a `dual_vote` default pair under `task_defaults`:
  
  ```json
  "task_defaults": {
    "scoring": "claude-sonnet-4-6",
    "vote_synthesis": "claude-opus-4-8",
    "chat": "claude-haiku-4-5-20251001",
    "dual_vote": { "openai": "gpt-5.5", "anthropic": "claude-opus-4-8", "synthesizer": "claude-opus-4-8" }
  }
  ```

### 3.2 `agent/providers.py`

- In `_anthropic()`, resolve the model's `sampling_params` flag (default `true`). When `false`, **omit** `temperature` from `client.messages.create(...)`.
- When sampling params are omitted for an Opus model, send `thinking={"type": "adaptive"}` so reasoning does not leak into the JSON/prose response (per the Claude API guidance for Opus 4.8 with sampling off). Keep `max_tokens` clamped to the model's `max_output_tokens` as today.
- No signature change to `generate()` — callers (`scoring.py`, `vote.py`, `chat.py`) keep passing `temperature`; the provider decides whether to forward it. This makes the fix **central**: one change repairs every caller.

### 3.3 Verification

- With an Anthropic key set and Opus 4.8 selected, a single `generate()` call returns `ok: True` with real text (previously `ok: False, error: "BadRequestError…"`).

---

## 4. `.env` loading

### 4.1 Mechanism

- Add `python-dotenv` to `requirements.txt` (optional dependency).
- At the **top of `app.py`**, before any provider import that reads env, load `backend/.env`:
  - If `python-dotenv` is importable, use `load_dotenv(Path(__file__).parent / ".env")`.
  - If not, a ~10-line built-in fallback parser reads `KEY=VALUE` lines (ignoring blanks/`#` comments) into `os.environ` **without overwriting** already-set vars (real environment wins over file).
- `providers.py` is **unchanged** — it still reads `os.environ` at call time. The "keys never written to disk by the app" invariant holds; the user authors `.env` themselves.

### 4.2 Files

- `backend/.env.example` (committed): `ANTHROPIC_API_KEY=`, `OPENAI_API_KEY=`, `AZURE_OPENAI_API_KEY=`, `AZURE_OPENAI_ENDPOINT=`, `PORT=`.
- `backend/.env` (the user's real keys): added to `.gitignore`, never committed.
- `.gitignore`: ensure `backend/.env` (and `.env`) are ignored; create or append as needed.

---

## 5. Dual-provider vote synthesis

### 5.1 Schema — `agent/schemas.py`

Add optional, defaulted fields to `Vote` (serialize automatically via `asdict()`; existing `sample_results.json` loads unchanged — no migration):

```python
mode: str = "single"                                   # "single" | "dual"
raw_votes: List[Dict[str, Any]] = field(default_factory=list)
    # each: {provider, model, recommendation, narrative, dissent, top_risks}
disagreements: List[Dict[str, Any]] = field(default_factory=list)
    # each: {dimension, openai_position, anthropic_position, resolution}
```

### 5.2 Engine — `agent/vote.py`

- Keep `synthesize_vote()` exactly as is (single-model path, mock fallback). **No rewrite.**
- Add `synthesize_vote_dual(ev, openai_model, anthropic_model, synthesizer_model)`:
  1. Compute the deterministic parts **once** (`derive_recommendation`, `_structured_findings`, evidence, risks) — recommendation band and gating are identical across providers (gating is deterministic; never LLM-overridable).
  2. Generate narrative/dissent **independently** from each provider via the existing `_llm_narrative()` path (refactor it to accept and return per-provider results). Run the two provider calls **concurrently** (thread pool) to keep latency ≈ one call, not two.
  3. **Reconcile** with one Anthropic (`synthesizer_model`) call: system = persona prompt; user = the deterministic findings + both raw votes, asked to (a) write the final reconciled narrative/dissent in Nick's voice and (b) list material disagreements as structured JSON. Return via `extract_json`.
  4. Assemble a `Vote` with `mode="dual"`, `recommendation`/`confidence`/`top_risks`/`evidence_to_close` from the deterministic logic (unchanged), `narrative`/`dissent` from the reconciliation, `raw_votes=[openai, anthropic]`, `disagreements=[…]`.
- **Graceful degradation:** if only one provider key is present (the Anthropic-only case today), skip the missing side, set `mode="single"`, produce that provider's vote, and attach a one-line note that dual is off until the other key is added. If *neither* live key is present (mock), fall through to `synthesize_vote()` unchanged — offline demo intact.
- **Failure isolation:** if one provider call fails (after retry — §7), fall back to single-provider with a flagged note rather than failing the vote. If the reconciliation call fails, fall back to the Anthropic raw vote's narrative.

### 5.3 Wiring — `app.py`

- `_run_and_cache()` gains a `vote_mode` / dual-pair argument. When dual is requested and ≥1 live key is present, call `synthesize_vote_dual(...)`; otherwise `synthesize_vote(...)`.
- `_validate_models()` extends to validate each model in the dual pair (openai, anthropic, synthesizer) the same way it validates `scoring_model`/`vote_model`.
- Request body accepts either `vote_model` (single, back-compat) or a `vote_dual` object `{openai, anthropic, synthesizer}`.

---

## 6. Frontend — model selection + dual-vote rendering (`frontend/index.html`)

### 6.1 Model controls (header / run bar)

Replace the single selector with three controls:

- **Scoring model** — one model (default Sonnet 4.6).
- **Vote** — a toggle: *Single model* or *Dual (two-model read)*.
  - Single → one model picker (default Opus 4.8).
  - Dual → an OpenAI picker + an Anthropic picker; the **synthesizer is fixed** to the strongest available Anthropic model (Opus 4.8) and shown read-only.
- No-key models are greyed out with a tooltip ("set OPENAI_API_KEY to enable"). When dual is selected but only one provider has a key, show an inline "dual will run single-provider until you add the other key" note.

Request payload sends `scoring_model` and either `vote_model` or `vote_dual`.

### 6.2 Vendor-detail vote section

- When `mode="dual"`: a **"Two-model read"** panel — reconciled vote on top, then OpenAI and Anthropic raw votes side by side, then a short **disagreements** list (dimension · each position · how it was resolved).
- When `mode="single"`: collapses to today's single-vote view.
- While in the vote section, add a non-color status cue (icon) alongside the existing color badges for colorblind safety (small, in-scope change).

---

## 7. Critical robustness (built this round)

### 7.1 Background-job evaluation with progress + cancel

- `POST /api/evaluate` and `/api/evaluate_upload` return a `job_id` immediately and run the pipeline in a **worker thread**; an in-memory `_JOBS` registry (dict + lock, mirroring `_RESULTS`) tracks `{stage, scored, total, done, error, result, cancel_requested}`.
- New `GET /api/evaluate/status/<job_id>` returns the job's progress snapshot; on completion it includes the cached result (and the result is also written to `_RESULTS` as today).
- The existing `progress` callback in `scoring.py` (currently accepted but never wired) is connected to the job's `scored/total`.
- New `POST /api/evaluate/cancel/<job_id>` sets `cancel_requested`; the scoring loop checks it between batches and stops cleanly.
- Frontend: the run bar polls status, shows a real progress bar + stage label, and offers a cancel button. (Back-compat note: the offline standalone file never calls these endpoints — it's pre-seeded — so it is unaffected.)

### 7.2 Retry with backoff

- In `providers.py`, wrap the provider `.create()` calls in retry-with-exponential-backoff for transient errors (timeouts, 429, ≥500). Client errors (400/401/404) are **not** retried — surfaced immediately. Keep the fail-soft contract: after retries are exhausted, return the existing `{ok: False, error}` shape.

### 7.3 Fail-soft ingestion

- `ingest.py` / `app.py`: enforce a configurable `MAX_UPLOAD_MB` (default 25 MB, overridable via env) and reject oversized uploads with a clear error instead of blocking.
- Missing parser SDK (pdfplumber/pypdf/python-docx/openpyxl) returns a friendly "install X to parse this file type" error rather than raising `ImportError` mid-request.
- Basic **SSRF guard** on URL fetch: reject private/loopback/link-local IP ranges before fetching.

---

## 8. Testing & verification (manual — no test suite by project convention)

1. **§0 fix:** Anthropic key set, Opus 4.8 selected → single `generate()` returns real text; previously `ok:False`.
2. **`.env`:** put the Anthropic key in `backend/.env`, launch with no `export` → `/api/health` shows `live_models_available: true`; `.env` is gitignored.
3. **Dual degradation (today, Anthropic-only):** select Dual vote → vote runs Anthropic-only, `mode="single"`, UI shows the "add OpenAI key" note, narrative is real (not demo fallback).
4. **Dual full path** (when an OpenAI key is added, GPT-5.5 id verified): a vendor vote shows reconciled + two raw votes + disagreements.
5. **Offline mock:** with no keys, full pipeline + single mock vote still works; standalone HTML unchanged.
6. **Robustness:** start a live evaluation → progress bar advances, cancel works; oversized upload and missing-parser cases return clear errors, not stack traces.
7. **Rebuild standalone:** `python build_static.py` succeeds and bundles the updated frontend.
8. **Re-run `graphify update .`** after code changes (AST-only).

---

## 9. Roadmap (specced, NOT built this round)

Prioritized backlog, in rough order of selection-committee value:

1. **Export** — PDF / PPTX / CSV of a vendor scorecard + vote (committee handoff).
2. **Disk persistence** — evaluations survive restart (SQLite or versioned JSON).
3. **2-vendor compare view** — side-by-side capability/category diff.
4. **Evidence-source drill-down** — which proposal page/section a score came from.
5. **LLM-call caching** — memoize by (vendor, proposal hash, model) to avoid paid re-runs.
6. **Auth + rate limiting + structured request logging** — before any shared/hosted deployment.
7. **Chat enhancements** — streaming, source drill-down, optional dual-provider.
8. **Accessibility pass** — ARIA labels, live regions, sort indicators, full colorblind cues.

---

## 10. Risk & rollback notes

- All changes are additive or guarded: new `Vote` fields default to single-mode shape; `synthesize_vote()` and the mock path are untouched; the provider fix only *removes* a parameter for two specific models. Rollback is reverting the touched files; cached/sample results remain valid because the new fields are optional.
- The one external unknown is the **GPT-5.5 model id**; it is isolated to one `models.json` entry, marked for verification, and not exercised until an OpenAI key is present.
