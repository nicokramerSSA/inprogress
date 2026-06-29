# FSM RFP Evaluation Agent — What's New

A summary of the work I landed on `main`, for a teammate picking it up. Five features are
merged (PRs #36, #40/#37, #38, #39, #41) plus a deploy fix (#42), and the app is **live on
Render** at https://fsm-rfp-evaluation-agent.onrender.com — and still runs end‑to‑end
locally.

**What the app is:** an advisory AI agent that scores vendor responses to the Service
Logic FSM platform RFP (all 422 requirements), reasons in Nick Kramer's "digital‑twin"
persona, and casts an independent vote — with two scoring lenses, MoSCoW/architectural
gating, OpCo‑segment fit, an "agentic‑future" read, head‑to‑head compare, and a
retrieval‑grounded chat assistant. Python/Flask backend + single‑file React (CDN) front
end. No database, no build toolchain, no test suite — all knowledge is editable JSON and
verification is manual.

---

## The five features

| # | Feature | PR | One‑liner |
|---|---------|----|-----------|
| 1 | Dual‑provider vote + live‑model robustness | #36 | Makes it usable with real API keys and hardened for real proposals |
| 2 | 2‑vendor compare view | #40 (was #37) | A "Compare" tab: two vendors side by side, deterministic |
| 3 | Disk persistence | #38 | Evaluations survive a server restart |
| 4 | Evidence‑source drill‑down | #39 | Every score links back to the vendor's own words |
| 5 | Parallel evaluation | #41 | Concurrent scoring (~6× fewer waves per vendor) + run several vendors at once |

Plus a deploy fix (#42) and the live Render deployment — see **Deployment** below.

---

### 1. Dual‑provider vote + live‑model robustness (PR #36)

The foundation that makes the agent usable with live models instead of only the offline
demo engine.

- **Live‑model correctness.** Fixes the Opus 4.7/4.8 sampling‑param 400 (those models
  reject `temperature`; the provider now omits it and uses adaptive thinking). Adds
  `.env` loading at startup (keys still never written to disk).
- **Dual‑provider vote (the headline).** Runs an OpenAI vote and an Anthropic vote in
  parallel, then reconciles them and surfaces where they disagreed. The recommendation,
  gating, and risks stay deterministic — the models only write narrative/dissent.
  Degrades gracefully: both keys → dual; one key → single with a note; no keys → offline
  mock.
- **Robustness.** Retry/backoff on transient provider errors; fail‑soft ingestion (upload
  size cap, an SSRF guard that blocks private/loopback/metadata addresses); background‑job
  evaluation with status polling and a working Cancel.
- **Where:** `backend/agent/providers.py`, `vote.py`, `ingest.py`, `app.py`,
  `frontend/index.html` (split Scoring vs Vote model selection + single/dual toggle).

### 2. 2‑vendor compare view (PR #40, replaces #37)

The committee's core question is "Vendor A vs Vendor B." This puts two complete
evaluations side by side.

- A new **Compare** tab with vendor pickers and a **computed one‑line takeaway**
  ("X leads — higher on both lenses … Y is disqualified"). Fully **deterministic and
  client‑side** — zero API cost, instant, auditable.
- Side‑by‑side rollups with **colorblind‑safe delta chips** (arrow + sign, not color):
  both headline lenses, gate, §30 capabilities, SSA categories, OpCo segment fit, agentic
  future, and the vote.
- A computed **requirement‑divergence summary** plus an expandable, filterable
  **422‑row diff table**.
- **Where:** `frontend/index.html` (one new `Compare` component; no backend change).

### 3. Disk persistence (PR #38)

Before this, every evaluation lived only in memory and died on restart — losing an
expensive live run to a reboot. Now they're durable.

- New module `backend/store.py`: **versioned JSON, one file per vendor**, durable‑latest
  (a re‑eval overwrites), **atomic writes**, corrupt files skipped instead of crashing
  boot.
- On boot the bundled demo seed is **overlaid by the store** (your real runs win); on
  completion the result is saved **outside** the in‑memory lock. A store failure never
  blocks boot or fails an evaluation. Keys never reach disk.
- Consistent with the project's "no DB / editable JSON" ethos. Reset = delete
  `backend/data/store/` (it's gitignored).
- **Where:** `backend/store.py`, `backend/app.py`, `.gitignore`. No UI change.

### 4. Evidence‑source drill‑down (PR #39)

The scores now show their work. Each requirement links back to the proposal text it came
from.

- Per requirement: a **verbatim quote**, the **source** document, and a **locator**
  (PDF page / XLSX sheet / DOCX section), shown as an expandable "evidence" disclosure on
  the requirement table.
- **Honest by construction:** if a quote can't be located it says `(unlocated)` — it
  never fabricates a page. The offline mock emits a clearly‑`[demo]` quote so the feature
  is visible without keys.
- **Provably non‑disruptive:** ingestion embeds location markers that are stripped back
  out before scoring, so totals/gating are byte‑identical to before (a built‑in
  regression check).
- **Where:** `backend/agent/ingest.py`, `scoring.py`, `schemas.py`,
  `frontend/index.html`; demo seed `data/sample_results.json` regenerated (1961 rows now
  carry evidence) and the standalone rebuilt.

### 5. Parallel evaluation — concurrent scoring + multi‑vendor batch (PR #41)

Scoring one vendor was strictly serial: 422 requirements in 36 back‑to‑back LLM calls,
roughly 6–15 minutes a vendor, almost all of it idle on the network. And there was no way
to run several vendors at once. This fixes both.

- **One global concurrency cap.** A single `BoundedSemaphore` in `providers.py`
  (env `RESULTS_MAX_CONCURRENCY`, default 6) wraps every real LLM call — scoring, vote, and
  chat share it. It's the one knob that bounds how hard the providers are hit (and therefore
  cost and rate‑limit pressure), with jittered retry/backoff on 429s. The offline mock never
  touches it.
- **Concurrent scoring (the speed win).** `_score_requirements` now fans its 36 batches
  through a thread pool; the semaphore — not the pool — bounds total in‑flight calls, so the
  cap holds across vendors too. A vendor drops from ~36 serial round‑trips to about
  ⌈36 ⁄ cap⌉ waves. Output is rebuilt in the original requirement order, so results are
  identical regardless of completion order (the regression anchor).
- **Multi‑vendor batch runs.** A new `POST /api/evaluate_batch` fans N vendors to the
  existing per‑job machinery (one job per vendor). A new **Batch evaluate** tab: pick
  vendors from **deterministic dropdowns** (the five RFP vendors, no repeats, one card
  each), a **pre‑flight call‑count confirm** on paid models (skipped for the mock), and a
  **live batch board** showing each vendor's progress with cancel and a link to its result.
- **Where:** `backend/agent/providers.py`, `scoring.py`, `backend/app.py`,
  `frontend/index.html`; `RESULTS_MAX_CONCURRENCY` documented in `README.md`/`CLAUDE.md`;
  standalone rebuilt.

---

## Deployment (live on Render)

The app is deployed as a Render web service and is **live at
https://fsm-rfp-evaluation-agent.onrender.com** with live Anthropic models enabled.

- **Created via the Render CLI:** web service, Python runtime, root directory
  `FSM_Scoring_Agent/backend`, build `pip install -r requirements.txt`, start
  `python3 app.py`, health check `/api/health`, auto‑deploy on `main`. `ANTHROPIC_API_KEY`
  is a Render secret env var — never committed to the repo.
- **Deploy fix (PR #42):** `app.run` bound `127.0.0.1`, which Render's router can't reach;
  it now binds `0.0.0.0` (still served at 127.0.0.1 locally, still honors `$PORT`).
- **Caveat — ephemeral disk.** Uploaded proposals (`data/uploads/`) and persisted runs
  (`data/store/`) live on the container's disk and are **wiped on each redeploy/restart**.
  The app re‑seeds the five demo vendors from bundled JSON on boot, so the demo is stable;
  durable real runs in the deployed app would need a Render Disk (paid add‑on).
- **Dashboard:** https://dashboard.render.com/web/srv-d8u43fegvqtc739c85kg

## Smaller fixes

- **Compare‑tab jitter fixed.** Switching to the (tall) Compare tab could oscillate the
  vertical scrollbar on/off, rewrapping the layout and visibly shaking the page. Reserved
  the scrollbar gutter (`html{scrollbar-gutter:stable;overflow-y:scroll}`) so the width
  never changes.

---

## How to run

```bash
cd FSM_Scoring_Agent/backend
pip install -r requirements.txt        # flask required; LLM SDKs / file parsers optional
python3 app.py                         # → http://127.0.0.1:8000  (runs on offline mock, no keys)
```

For live models, put keys in `backend/.env` (gitignored) before launching and pick the
model in the top‑right selector:

```
ANTHROPIC_API_KEY=sk-...               # Claude Opus / Sonnet / Haiku
OPENAI_API_KEY=sk-...                  # GPT‑4o / mini (enables the dual‑provider vote)
```

Optional: `RESULTS_MAX_CONCURRENCY` (default 6) caps how many LLM calls run at once across
the whole app — raise it if your provider rate limit has headroom, lower it if you see 429s.
The **Batch evaluate** tab runs several vendors in parallel under that cap. Or skip local
setup entirely and use the live deployment linked above.

**Offline demo (no Python, no keys):** open `FSM_Evaluation_Agent_Standalone.html` in a
browser — five vendors pre‑evaluated, including the new Compare tab and evidence
drill‑down. Live re‑evaluation and chat need the server.

> Note: this environment has no `python` alias — use `python3`.

---

## Where to read more

- **Design docs & plans** (one spec + one plan per feature, with the reasoning):
  `FSM_Scoring_Agent/docs/superpowers/specs/` and `…/plans/`.
- **Architecture write‑up:** `FSM_Scoring_Agent/docs/DESIGN.md`.
- **Working agreement / conventions:** `FSM_Scoring_Agent/CLAUDE.md`.

## Status / caveats

- **Vendor proposals are due 2026‑07‑02.** Until then the app runs on synthetic sample
  proposals, clearly labelled "demo"; the evidence quotes in the seed are `[demo]` mock
  output. The store overlays the demo the moment you run a real evaluation.
- No automated test suite (project convention) — each feature was verified with focused
  `python3` harnesses + manual server/headless checks, and each branch passed an
  independent final code review before merge.
- **Deployed app uses an ephemeral disk** — uploaded proposals and persisted runs are
  wiped on each redeploy/restart (the five demo vendors always re‑seed). Attach a Render
  Disk for durable runs in the deployed app.
- One known follow‑on from the parallel‑evaluation review: `/api/evaluate_batch` extracts
  every vendor's files/URLs synchronously before responding (mirrors the single‑vendor
  endpoint); for large batches that work could move into the per‑vendor job thread.
- Still on the backlog (from the original gap analysis): export (PDF/PPTX/CSV),
  LLM‑call caching, auth + rate limiting + request logging, chat enhancements
  (streaming, source drill‑down), and an accessibility pass.
