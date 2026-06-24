# Parallel Evaluation — Concurrent Scoring + Multi-Vendor Batch — Design

**Date:** 2026-06-24
**Roadmap origin:** raised directly — "the current state is extremely slow"
(why does scoring all requirements take so long?) and "there is no ability
for a user to upload all documents from all vendors and run each vendor in
parallel." Both are the same underlying problem: the evaluation pipeline is
serial at every level.
**Status:** Approved, ready for implementation plan

---

## 1. Problem

Scoring one vendor is strictly sequential. In `scoring.py`, the 422
requirements are split into batches of 12 — **36 batches** — and run in a
plain `for` loop. Each iteration is one blocking LLM call
(`client.generate`, `max_tokens=8192`, JSON). Batch *N+1* does not start
until batch *N*'s network round-trip returns. So a vendor's wall-clock is
roughly **36 round-trips back-to-back** plus the vote call(s) — on a frontier
model at ~10–25 s per call, that is **6–15 minutes per vendor, almost all of
it idle waiting on the network**. The local retrieval and indexing are cheap;
the cost is the serial waits.

That is the same reason there is no multi-vendor run. Each `evaluate_upload`
spawns exactly one background thread for one vendor (`app.py`). There is no
"run all vendors," no aggregate progress, no concurrency budget. Evaluating
five vendors means firing five uploads by hand and watching them crawl one
batch at a time.

The calls are I/O-bound and independent, so they can overlap. The only real
constraint is the provider rate limit (HTTP 429) and the cost of firing many
paid calls at once. This design makes a single vendor fast by running its
batches concurrently under a global ceiling, and adds a bulk multi-vendor
experience that reuses that same ceiling.

## 2. Goals / non-goals

**Goals**

- A single vendor's 36 batches run **concurrently**, bounded by one global,
  env-tunable ceiling — cutting wall-clock from ~36 serial round-trips to
  roughly `ceil(36 / cap)` waves.
- **One global cap across the whole app** (`RESULTS_MAX_CONCURRENCY`,
  default 6): a single `BoundedSemaphore` that every *real* LLM call —
  scoring, vote, chat — acquires. The semaphore is the single source of
  truth for how hard the providers are hit.
- **Automatic retry + backoff on rate limits** (429): a transient
  rate-limit slows a call down (exponential backoff + jitter) instead of
  failing a requirement.
- A **bulk multi-vendor run**: a Batch evaluate surface with repeatable
  vendor rows (vendor + files/URLs), one "Run all" that fans out **one job
  per vendor**, all bounded by the same global cap.
- A **live batch board**: every launched vendor with its own progress bar
  (queued / scoring N⁄422 / voting / done / error), each clickable to its
  result as it finishes — rendered from the existing per-job status polling.
- A **pre-flight confirm** on paid models showing call counts (not dollars),
  skipped automatically for the offline mock.
- The mock engine, single-vendor flow, disk persistence, and evidence
  drill-down all keep working unchanged.

**Non-goals (this round)**

- **No asyncio rewrite.** The calls are I/O-bound; threads plus a semaphore
  deliver the concurrency without a second concurrency model in a sync Flask
  app.
- **No server-side batch registry.** The batch board's list of launched
  job_ids lives in the client session. Jobs themselves are durable (per-job
  registry + disk persistence), so navigating away still finishes the runs
  and lands them in the Dashboard — only the live board is lost.
- **No per-provider caps.** One global cap is simpler and bounds cost; the
  retry/backoff absorbs a provider that is momentarily tighter than the cap
  assumes. Per-provider tuning is a future item.
- **No dollar-cost estimate.** Pricing math is fragile and goes stale; the
  pre-flight shows honest call counts instead.
- **No change to the single-vendor evaluate flow.** Batch is additive; the
  server reuses the same job machinery so scoring logic is not duplicated.
- No run history, no new persistence shape — those are owned elsewhere.

## 3. Decision record

- **Approach 1: global semaphore in the provider layer + thread-pool
  fan-out** (chosen over an asyncio rewrite and over a single shared
  executor-as-limiter). A `BoundedSemaphore(cap)` in `providers.py` wraps
  every real API call, so the cap is honoured no matter who calls — scoring,
  vote, or chat. A `ThreadPoolExecutor` in `_score_requirements` provides the
  parallelism. This is the smallest, most auditable change: one knob, no new
  framework, faithful to "one global cap across the whole app."
  - *Rejected — asyncio:* Flask is synchronous; async clients mean an event
    loop per request thread and a full `providers.py` rewrite, for no real
    benefit at 5–6 vendors.
  - *Rejected — shared executor as the only limiter:* vote/chat calls bypass
    the executor and would be unbounded (the global cap leaks), and a pooled
    task waiting on the same pool can deadlock.
- **The semaphore guards real calls only.** The mock provider is CPU-only
  and instant; acquiring the gate would needlessly serialize it. Mock skips
  the gate.
- **Worst-case parked threads = concurrent-vendors × cap** (~36 at committee
  scale). Acceptable: parked threads are cheap, and the *semaphore*, not the
  thread count, governs API load and cost.
- **One job per vendor, reusing existing machinery.** The batch endpoint
  launches the same `_new_job`/`_run_job`/`_run_and_cache` path per vendor.
  Cross-vendor concurrency is handled entirely by the shared semaphore, so no
  new orchestration code is needed.
- **Batch board state is client-side.** Durability already exists at the job
  and disk layers; a server-side batch registry would add storage for a
  recovery path nobody requested (YAGNI).

## 4. Architecture

```
Layer A (speed) — providers.py + scoring.py
  providers.py:  _LLM_GATE = BoundedSemaphore(cap)   # the single global ceiling
                 client.generate(real model): acquire gate -> call (retry/backoff on 429) -> release
                 client.generate(mock):        no gate (instant, CPU)
  scoring.py:    _score_requirements: ThreadPoolExecutor(max_workers=cap)
                    submit all 36 batches -> as each completes, count + emit progress
                    gather rows by rid -> emit in original reqs order
                 (mock path returns before the loop, unchanged)

Layer B (scale) — app.py + frontend
  app.py:        POST /api/evaluate_batch (multipart, indexed vendor_i/files_i[]/urls_i + shared models)
                    -> save files per vendor, extract_sources, launch one job per vendor
                    -> 202 {batch_id, jobs:[{vendor, job_id}]}
  frontend:      Batch evaluate tab (repeatable rows) -> preflight confirm (call counts; skip for mock)
                    -> POST evaluate_batch -> batch board polling /api/evaluate/status/<jid> per vendor
```

The semaphore is acquired by every vendor's batches alike, so total in-flight
across the whole run stays ≤ cap with no cross-vendor coordination.

## 5. Component changes

### 5.1 `backend/agent/providers.py` (the global cap + retry)

- Module-level `_MAX_CONCURRENCY = int(os.environ.get("RESULTS_MAX_CONCURRENCY", "6"))`
  and `_LLM_GATE = threading.BoundedSemaphore(_MAX_CONCURRENCY)`.
- In `client.generate`, wrap the **real** provider network call in
  `with _LLM_GATE:`. The mock branch does not acquire the gate.
- **Retry + backoff:** on a rate-limit failure (HTTP 429 or a provider
  rate-limit error), retry up to 4 attempts with exponential backoff
  `0.5, 1, 2, 4 s` plus jitter, still inside the held gate slot. After the
  last attempt, return the existing `{ok: False, error: …}` soft-fail (the
  per-row deterministic fallback then fills the holes). Non-rate-limit errors
  are not retried — they soft-fail immediately as today.
- The gate and retry are internal to `generate`; call signatures are
  unchanged, so scoring/vote/chat get the cap for free.

### 5.2 `backend/agent/scoring.py` (concurrent batches)

- `_score_requirements` (live path only): build the same 36 batches, but
  submit each to a `ThreadPoolExecutor(max_workers=_MAX_CONCURRENCY)` instead
  of looping. Each worker builds its batch context (retrieval is local/cheap)
  and calls `client.generate` exactly as today.
- **Progress:** count *completed* batches as futures resolve
  (`as_completed`); emit `Scored {min(done*BATCH, total)}/{total} requirements…`
  with the existing `0.05 + 0.62 * (done_reqs/total)` fraction so the bar and
  the `app.py` regex (`\d+/\d+`) are unchanged.
- **Ordering invariant:** collect each batch's parsed rows into a
  `rid -> row` map as workers finish, then build the `out` list by iterating
  the original `reqs` in order (calling `_row_to_score`, or the deterministic
  `_mock_score_requirement` fallback for any rid the model skipped). Output is
  identical regardless of completion order.
- **Per-batch error isolation:** wrap each batch worker so an exception
  (network, parse) yields no rows for that batch; those ≤12 requirements fall
  back to the deterministic engine, exactly as the current `by_rid = {}` path.
- **Cancellation:** check `should_cancel()` before submitting each batch and
  again as futures complete; once set, stop submitting, let in-flight calls
  finish (results discarded), and raise `EvaluationCancelled`.
- The mock path (`is_mock(model_id)`) still returns before any of this — mock
  is instant and stays sequential.

### 5.3 `backend/app.py` (the batch endpoint)

- New `POST /api/evaluate_batch` (multipart). Fields: shared
  `scoring_model`, `vote_model`, optional `vote_dual`, `requirement_sample`;
  per-vendor indexed fields `vendor_0`, `files_0` (repeatable), `urls_0`,
  then `vendor_1`, … The count is discovered by scanning for `vendor_i`
  until absent.
- For each vendor row: validate it has a name and at least one file or URL
  (reject that row with a message; valid rows still run); save files under
  `data/uploads/<vendor>/` (reusing the existing per-vendor save + extension
  allowlist); `extract_sources`; `_new_job`; attach ingest metadata; launch
  `threading.Thread(target=_run_job, …, daemon=True)` — the same per-vendor
  path the single endpoint uses.
- Validate models once for the whole batch (`_validate_models`).
- Return `202 {batch_id, jobs: [{vendor, job_id}], rejected: [...]}`.
  `batch_id` is a `uuid4().hex[:12]` correlation id (not persisted).
- No new scoring or job logic — only request parsing and the fan-out loop.

### 5.4 `frontend/index.html` (Batch tab, preflight, board)

- New nav entry `["batch", "Batch evaluate"]`. Single-vendor evaluate flow
  untouched.
- **Repeatable vendor rows:** state `rows = [{vendor, files: File[], urls}]`;
  an "Add vendor" button appends a row; each row removable. Shared
  scoring/vote model selectors (and dual toggle) above the rows.
- **Preflight confirm:** on "Run all", if the scoring model is not `mock`,
  show a dialog with the call-count estimate:
  `scoring_calls_per_vendor = ceil(reqCount / 12)` (reqCount = 422 or the
  sample size), `vote_calls_per_vendor = 3 if dual else 1`,
  total `= vendors * (scoring + vote)`. Render e.g. "5 vendors × ~36 = ~180
  scoring calls (Sonnet) + 5 vote calls (Opus)." Mock skips the dialog.
- On confirm: build `FormData` with indexed fields, POST to
  `/api/evaluate_batch`, receive `jobs[]`.
- **Batch board:** for each `{vendor, job_id}`, poll
  `/api/evaluate/status/<jid>` (the existing endpoint) and render a row:
  vendor name, progress bar from `stage` + `scored/total`, a "view" link to
  Vendor detail when `done`, an error state on failure, and a per-row
  cancel via `/api/evaluate/cancel/<jid>`. A header line shows "N of M done."
- ASCII-only JS string delimiters (in-browser Babel). Quote/vendor text
  rendered as React children (escaped); no `dangerouslySetInnerHTML`.

### 5.5 Build + docs

- Rebuild `FSM_Evaluation_Agent_Standalone.html` via `python3 build_static.py`.
- Document `RESULTS_MAX_CONCURRENCY` (default 6) in `README.md` and
  `CLAUDE.md`.

## 6. Data flow — a batch run end to end

1. User fills the Batch tab: rows `[{vendor, files, urls}]` + shared models.
2. "Run all" → client computes the pre-flight estimate (pure arithmetic). If
   model is `mock`, skip the dialog and fire; else show counts and wait for
   confirm.
3. POST multipart to `/api/evaluate_batch`. Server validates models, saves
   each vendor's files, runs `extract_sources`, spawns one job per vendor →
   `202 {batch_id, jobs:[…]}`.
4. Each job runs the Layer-A concurrent `evaluate_vendor`; the global
   semaphore caps total in-flight across all vendors.
5. Client polls each `job_id` and renders the batch board; each "done" links
   to Vendor detail. Results persist to disk per vendor as they complete
   (existing `store.save`).

## 7. Error handling & edge cases

- **429 / rate limit** → provider retries with exponential backoff + jitter;
  only after exhausting retries does it soft-fail, and the per-row
  deterministic fallback fills any holes so rollups never have gaps.
- **One batch throws** → that batch's ≤12 requirements fall back to mock
  scoring, isolated; other batches unaffected.
- **One vendor fails in a batch** → its board row shows "error"; other
  vendors continue. Never all-or-nothing.
- **Cancellation** → existing per-job cancel; `_score_requirements` checks
  `should_cancel` between completions, stops submitting, raises
  `EvaluationCancelled`; in-flight calls finish but results are discarded.
- **A row with no file and no URL** → rejected before any job starts (listed
  in `rejected`); valid rows still run.
- **Duplicate vendor names in one batch** → last-write-wins in
  `_RESULTS`/store (same as re-evaluating). Noted, not prevented.
- **Result ordering under concurrency** → rows gathered by `rid` and emitted
  in original `reqs` order; output identical regardless of completion order.
- **Thread count** → worst case `concurrent-vendors × cap`; bounded at
  committee scale and harmless. The semaphore governs API load, not the
  thread count.

## 8. Testing / verification

No automated suite (project convention — verification is manual, with small
`python3` assertion harnesses for the pure logic). Verify:

1. **Cap respected:** a fake `generate` that records concurrent entries →
   run `_score_requirements`; assert peak concurrency ≤ cap.
2. **Order invariant:** a fake client returning rows out of completion order
   → assert output matches `reqs` order and every rid is scored.
3. **Backoff:** a fake provider that raises 429 twice then succeeds → assert
   the call ultimately succeeds and was retried; a non-429 error is not
   retried.
4. **Preflight math:** assert the call-count formula for full (36) and
   sampled runs, single vs dual vote.
5. **Manual — mock batch:** run a 3-vendor mock batch → board shows all
   three, results land in the Dashboard.
6. **Manual — live batch (keys present):** a small live batch → wall-clock
   drops materially vs. sequential and no 429 storm; one vendor cancelled
   mid-run stops cleanly while others finish.
7. **Standalone:** rebuild; headless check confirms Babel compiles (no blank
   page) and the Batch tab renders.

## 9. Risk & rollback

Layer A is contained to `providers.py` (semaphore + retry) and `scoring.py`
(concurrent `_score_requirements`); the mock path, output shape, gating, and
rollups are unchanged (the ordering invariant is the regression anchor).
Layer B is additive: a new endpoint and a new tab, both reusing existing job
machinery — the single-vendor flow, persistence, and evidence drill-down are
untouched. Rollback for A = restore the sequential loop and drop the
semaphore/retry; rollback for B = revert the endpoint and the tab. The two
layers are independently revertible. Sequencing note for the plan: Layer A's
semaphore must exist before Layer B fires parallel vendors, so build A first.
