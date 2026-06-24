# Parallel Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a single vendor's 422-requirement scoring run concurrently under one global cap, and add a bulk "upload many vendors, run them in parallel" experience with a live batch board.

**Architecture:** A module-level `BoundedSemaphore` in `providers.py` wraps every *real* LLM call — it is the single global ceiling for scoring, vote, and chat. `_score_requirements` fans its 36 batches through a `ThreadPoolExecutor` (the semaphore throttles how many hit the API at once). A new `/api/evaluate_batch` endpoint fans N vendors out to the existing per-job thread machinery — one job per vendor — and the frontend gains a **Batch evaluate** tab (repeatable vendor rows → pre-flight confirm → batch board that polls each job's existing status endpoint).

**Tech Stack:** Python 3.12 / Flask, `concurrent.futures.ThreadPoolExecutor`, `threading.BoundedSemaphore`, React 18 via CDN (in-browser Babel), no DB, no pytest (verification = standalone `python3` assertion harnesses + manual).

## Global Constraints

- **python3 only** — there is no `python` alias. Run everything with `python3`.
- **One global cap, one knob:** `RESULTS_MAX_CONCURRENCY` (env var, **default 6**). A single `threading.BoundedSemaphore` is the only ceiling; do not add per-provider caps.
- **The semaphore guards REAL calls only.** The `mock` provider is CPU-only and instant — it must NOT acquire the gate (acquiring it would needlessly serialize the offline demo).
- **The offline `mock` engine must always work** with zero API keys; the mock path in `_score_requirements` returns before any executor/semaphore code.
- **API keys come from the environment only, never written to disk.** Do not print, log, or commit keys. `backend/.env` is gitignored.
- **Ordering invariant:** `_score_requirements` output must be in the original `reqs` order and every `rid` must be scored, regardless of batch completion order. This is the regression anchor for concurrency.
- **Progress contract unchanged:** progress messages must still contain `"<scored>/<total>"` (the `app.py` `_job_progress` regex `(\d+)\s*/\s*(\d+)` parses them) and the fraction stays `0.05 + 0.62 * (scored/total)`.
- **In-browser Babel:** ASCII-only JS string delimiters in `frontend/index.html` (a curly quote used as a delimiter blanks the page). Render user/vendor text as React children (escaped) — never `dangerouslySetInnerHTML`.
- **No new persistence shape, no server-side batch registry, no asyncio, no dollar-cost math.** The single-vendor evaluate flow stays untouched.
- **Git root** is `/home/chagood/workspace/projects/RFP Agent` (the PARENT of `FSM_Scoring_Agent`). Commit paths are prefixed `FSM_Scoring_Agent/…`.
- **Commit message footer** (every commit), exactly:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx
  ```
- **Test harnesses are throwaway:** write each `python3` assertion harness, run it, confirm output, then delete it. Do NOT commit harness files (the project has no test suite by convention).
- **Build sequencing:** Task 1 (the semaphore) must land before Task 3/4 fire parallel vendors. Implement tasks in numeric order.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `backend/agent/providers.py` | The global concurrency gate (`BoundedSemaphore`) + extended retry/backoff, wrapping every real `generate` call. | 1 |
| `backend/agent/scoring.py` | `_score_requirements` runs its batches concurrently via a `ThreadPoolExecutor`, preserving order, progress, cancellation, and per-batch fail-soft. | 2 |
| `backend/app.py` | New `POST /api/evaluate_batch` endpoint: parse indexed multipart, save per vendor, fan out one existing-style job per vendor. | 3 |
| `frontend/index.html` | New **Batch evaluate** tab: repeatable vendor rows, pre-flight call-count confirm, live batch board polling per-job status. | 4 |
| `FSM_Evaluation_Agent_Standalone.html` | Rebuilt offline bundle. | 5 |
| `README.md`, `CLAUDE.md` | Document `RESULTS_MAX_CONCURRENCY`. | 5 |

---

## Task 1: Global concurrency gate + extended retry in `providers.py`

**Files:**
- Modify: `backend/agent/providers.py` (add module constants near `MOCK_MODEL_ID` at line 26; wrap the retry loop in `LLMClient.generate`, lines 110-140; add jitter/4th attempt to the existing backoff)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `providers.MAX_CONCURRENCY: int` — the resolved cap (read from `RESULTS_MAX_CONCURRENCY`, default 6).
  - `providers._LLM_GATE: threading.BoundedSemaphore` — the global gate (acquired internally by `generate` for real models only).
  - `LLMClient.generate(...)` keeps its exact signature and return shape `{"text","provider","model","ok","error"}`.

- [ ] **Step 1: Write the failing test** (throwaway harness `backend/_t1.py`)

```python
# backend/_t1.py — gate cap + mock-bypass + env knob
import os, threading, time
os.environ["RESULTS_MAX_CONCURRENCY"] = "3"
import importlib, agent.providers as P
importlib.reload(P)

# (a) env knob resolved
assert P.MAX_CONCURRENCY == 3, P.MAX_CONCURRENCY

# (b) the gate caps concurrent holders at MAX_CONCURRENCY
peak = 0; cur = 0; lock = threading.Lock()
def hold():
    global peak, cur
    with P._LLM_GATE:
        with lock:
            cur += 1; peak = max(peak, cur)
        time.sleep(0.05)
        with lock:
            cur -= 1
ts = [threading.Thread(target=hold) for _ in range(12)]
[t.start() for t in ts]; [t.join() for t in ts]
assert peak <= 3, f"peak {peak} exceeded cap 3"

# (c) mock never touches the network or the gate (returns the marker)
r = P.client.generate("sys", "user", "mock")
assert r["ok"] is False and "mock model handled by engine" in r["error"], r
print("PASS t1: cap", P.MAX_CONCURRENCY, "peak", peak)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python3 _t1.py`
Expected: `AttributeError: module 'agent.providers' has no attribute 'MAX_CONCURRENCY'` (the constant doesn't exist yet).

- [ ] **Step 3: Add the gate constants** — in `backend/agent/providers.py`, after `import time` add `import threading` to the imports (line 21 area), and after the `MOCK_MODEL_ID = "mock"` line (line 26) add:

```python
# Global concurrency ceiling for REAL LLM calls (scoring, vote, chat all share it).
# One knob bounds how hard we hit every provider at once, which also bounds cost.
# The mock engine never acquires this gate (it makes no network call).
MAX_CONCURRENCY = max(1, int(os.environ.get("RESULTS_MAX_CONCURRENCY", "6")))
_LLM_GATE = threading.BoundedSemaphore(MAX_CONCURRENCY)
```

- [ ] **Step 4: Wrap the retry loop in the gate + add jitter and a 4th attempt** — replace the body of `generate` from the `provider, model = resolve_model(model_id)` line through the final `return {...}` (lines 123-140) with:

```python
        provider, model = resolve_model(model_id)
        sdk = provider["sdk"]
        last = RuntimeError("generate: no attempt completed")  # defensive: never report NoneType
        # Hold one global slot across all retries of this single call, so a call that is
        # backing off on a 429 keeps applying back-pressure instead of letting another
        # call rush the same rate limit. The mock path returned above, so the gate wraps
        # real API calls only.
        with _LLM_GATE:
            for attempt in range(4):  # 1 try + 3 retries
                try:
                    if sdk == "anthropic":
                        return self._anthropic(provider, model, system, user, expect_json, max_tokens, temperature)
                    if sdk in ("openai", "openai_azure"):
                        return self._openai(provider, model, system, user, expect_json, max_tokens, temperature, azure=(sdk == "openai_azure"))
                    return {"text": "", "provider": provider["id"], "model": model_id,
                            "ok": False, "error": f"Unsupported sdk {sdk!r}"}
                except Exception as e:  # fail soft — never take the server down over an API error
                    last = e
                    if not _is_transient(e) or attempt == 3:
                        break
                    # Exponential backoff with jitter: ~0.5, 1, 2s plus 0-0.4s jitter.
                    time.sleep(0.5 * (2 ** attempt) + (hash((attempt, id(e))) % 400) / 1000.0)
        return {"text": "", "provider": provider["id"], "model": model.get("id", model_id),
                "ok": False, "error": f"{type(last).__name__}: {last}"}
```

Note: the `is_mock(model_id)` early-return block above (lines 117-121) is unchanged, so the mock never reaches the gate.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && python3 _t1.py`
Expected: `PASS t1: cap 3 peak 3` (peak may be 1-3; the assertion is `<= 3`).

- [ ] **Step 6: Verify the retry still works** (throwaway harness `backend/_t1b.py`)

```python
# backend/_t1b.py — retry retries transient errors, gives up on non-transient
import agent.providers as P
calls = {"n": 0}
class Rate(Exception):
    status_code = 429
def fake_ok(*a, **k):
    calls["n"] += 1
    if calls["n"] < 3:
        raise Rate()
    return {"text": "ok", "provider": "anthropic", "model": "m", "ok": True, "error": None}
# point resolve_model at a fake anthropic model, and _anthropic at our fake
P.resolve_model = lambda mid: ({"id": "anthropic", "sdk": "anthropic"}, {"id": "m"})
P.client._anthropic = fake_ok
r = P.client.generate("s", "u", "m")
assert r["ok"] and calls["n"] == 3, (r, calls)
# non-transient: raised once, not retried
calls["n"] = 0
def fake_bad(*a, **k):
    calls["n"] += 1
    raise ValueError("nope")
P.client._anthropic = fake_bad
r = P.client.generate("s", "u", "m")
assert r["ok"] is False and calls["n"] == 1, (r, calls)
print("PASS t1b: transient retried 3x, non-transient tried once")
```

Run: `cd backend && python3 _t1b.py`
Expected: `PASS t1b: transient retried 3x, non-transient tried once`

- [ ] **Step 7: Delete the harnesses and commit**

```bash
rm -f backend/_t1.py backend/_t1b.py
git add FSM_Scoring_Agent/backend/agent/providers.py
git commit -m "feat(providers): global concurrency gate + jittered retry

Add a module-level BoundedSemaphore(RESULTS_MAX_CONCURRENCY, default 6) that
every real LLM call acquires, so scoring/vote/chat share one global ceiling on
in-flight requests (bounds rate-limit pressure and cost). The mock engine never
acquires it. Extend the existing transient-error retry to 1+3 attempts with
exponential backoff plus jitter, held inside the gate slot.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Task 2: Concurrent batch scoring in `scoring.py`

**Files:**
- Modify: `backend/agent/scoring.py` (imports near line 36; rewrite `_score_requirements`, lines 159-203)

**Interfaces:**
- Consumes: `providers.MAX_CONCURRENCY` (Task 1); `providers.client.generate`; existing `build_retrieval_index`, `relevant_passages`, `_batch_keywords`, `_batch_prompt`, `_row_to_score(r, row, segments)`, `_mock_score_requirement(r, proposal_text, strengths, proposal_low, segments)`, `extract_json`, `EvaluationCancelled`.
- Produces: `_score_requirements(vendor, product, proposal_text, reqs, model_id, emit, should_cancel=None, segments=None) -> List[RequirementScore]` — same signature and return order as before, now computed concurrently for live models.

- [ ] **Step 1: Write the failing test** (throwaway harness `backend/_t2.py`)

```python
# backend/_t2.py — order invariant + concurrency cap for _score_requirements
import os
os.environ["RESULTS_MAX_CONCURRENCY"] = "4"
import threading, time, importlib
import agent.providers as P; importlib.reload(P)
import agent.scoring as S; importlib.reload(S)

# 30 fake requirements (rids r0..r29), so 3 batches of 12/12/6.
reqs = [{"rid": f"r{i}", "domain": "D", "capability": "W2C", "priority": "Should",
         "requirement": f"requirement number {i} about scheduling dispatch mobile",
         "rfp_notes": ""} for i in range(30)]

peak = 0; cur = 0; lock = threading.Lock()
def fake_generate(system, user, model_id, expect_json=False, max_tokens=4096, temperature=0.2):
    global peak, cur
    with lock:
        cur += 1; peak = max(peak, cur)
    time.sleep(0.03)
    # Return rows for whatever rids are in this batch prompt, in REVERSE to stress ordering.
    import re, json
    rids = re.findall(r'"rid":\s*"(r\d+)"', user)
    rows = [{"rid": rid, "met": "Yes", "quality": 4, "vendor_code": "OOB",
             "confidence": "High", "rationale": "ok", "evidence_gap": "", "evidence_quote": ""}
            for rid in reversed(rids)]
    with lock:
        cur -= 1
    return {"ok": True, "text": json.dumps(rows), "provider": "x", "model": model_id, "error": None}

S.client.generate = fake_generate
msgs = []
out = S._score_requirements("V", "P", "some proposal text about scheduling and dispatch",
                            reqs, "claude-sonnet-4-6", lambda m, f: msgs.append(m))
# order invariant: output rids match input order exactly
assert [s.rid for s in out] == [r["rid"] for r in reqs], [s.rid for s in out]
# every rid scored
assert len(out) == 30
# concurrency cap respected (executor max_workers == MAX_CONCURRENCY == 4)
assert peak <= 4, f"peak {peak} > 4"
# progress contract: at least one message carries N/total
import re
assert any(re.search(r"\d+/\d+", m) for m in msgs), msgs
print("PASS t2: order ok, peak", peak, "msgs", [m for m in msgs if '/' in m][-1:])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python3 _t2.py`
Expected: it currently runs **sequentially** so `peak` will be `1`, failing the intent (the test asserts `<= 4` which passes trivially) — to make the test meaningful first change the cap assertion to `assert peak >= 2`. Run and expect `AssertionError: peak 1` proving batches are serial today. Then restore the assertion to `assert peak <= 4` for Step 5.

- [ ] **Step 3: Add the import** — in `backend/agent/scoring.py`, change the stdlib import block near line 34-36 to add the executor and the providers cap:

```python
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Callable

from .knowledge import get_kb
from .providers import client, is_mock, extract_json, MAX_CONCURRENCY
```

- [ ] **Step 4: Rewrite `_score_requirements`** — replace the whole function body (lines 159-203) with the concurrent version:

```python
def _score_requirements(vendor, product, proposal_text, reqs, model_id, emit, should_cancel=None, segments=None) -> List[RequirementScore]:
    strengths = _vendor_cap_strength(vendor)
    proposal_low = (proposal_text or "").lower()
    if is_mock(model_id):
        # Mock is CPU-only and instant — stay sequential, never touch the executor/gate.
        return [_mock_score_requirement(r, proposal_text, strengths, proposal_low, segments) for r in reqs]

    kb = get_kb()
    system = kb.persona_system_prompt() + "\n\n" + kb.scoring_context()
    BATCH = 12
    total = len(reqs)
    retrieval_index = build_retrieval_index(proposal_text)  # built once, shared read-only across workers

    # Slice into batches up front; each batch is scored by an independent worker. The
    # global gate in providers.generate bounds how many actually hit the API at once
    # (across all vendors); the executor bounds this vendor's own fan-out.
    batches = [reqs[i:i + BATCH] for i in range(0, total, BATCH)]

    def score_batch(batch):
        # Returns {rid: row} for the batch, or {} on any failure (caller falls back per row).
        kws = _batch_keywords(batch)
        context = relevant_passages(proposal_text, kws, max_chunks=8, index=retrieval_index)
        user = _batch_prompt(vendor, product, batch, context)
        resp = client.generate(system, user, model_id, expect_json=True,
                               max_tokens=8192, temperature=0.15)
        if not resp["ok"]:
            return {}
        try:
            parsed = extract_json(resp["text"])
            rows = parsed if isinstance(parsed, list) else parsed.get("scores", [])
            return {row.get("rid"): row for row in rows}
        except Exception:
            return {}

    if should_cancel and should_cancel():
        raise EvaluationCancelled()

    by_rid: Dict[str, Dict[str, Any]] = {}
    done_reqs = 0
    cancelled = False
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        futures = {pool.submit(score_batch, b): b for b in batches}
        for fut in as_completed(futures):
            b = futures[fut]
            try:
                by_rid.update(fut.result())
            except Exception:
                pass  # leave this batch's rids unfilled -> per-row mock fallback below
            done_reqs += len(b)
            emit(f"Scored {min(done_reqs, total)}/{total} requirements…",
                 0.05 + 0.62 * (min(done_reqs, total) / total))
            if should_cancel and should_cancel():
                cancelled = True
                break
    if cancelled:
        raise EvaluationCancelled()

    # Build the output in ORIGINAL reqs order (not completion order). Any rid the model
    # skipped or a failed batch left out falls back to the deterministic engine, so the
    # rollups never have holes.
    out: List[RequirementScore] = []
    for r in reqs:
        row = by_rid.get(r["rid"])
        if row:
            out.append(_row_to_score(r, row, segments))
        else:
            out.append(_mock_score_requirement(r, proposal_text, strengths, proposal_low, segments))
    return out
```

- [ ] **Step 5: Run the test to verify it passes** (with `assert peak <= 4` restored)

Run: `cd backend && python3 _t2.py`
Expected: `PASS t2: order ok, peak <2..4> msgs ['Scored 30/30 requirements…']`

- [ ] **Step 6: Confirm the mock path is untouched** (throwaway harness `backend/_t2b.py`)

```python
# backend/_t2b.py — mock scoring stays deterministic & sequential (no executor)
import agent.scoring as S
reqs = [{"rid": f"r{i}", "domain": "D", "capability": "W2C", "priority": "Should",
         "requirement": "scheduling dispatch", "rfp_notes": ""} for i in range(5)]
out = S._score_requirements("IFS", "P", "proposal", reqs, "mock", lambda m, f: None)
assert [s.rid for s in out] == [r["rid"] for r in reqs]
assert all(hasattr(s, "quality") for s in out)
print("PASS t2b: mock path intact,", len(out), "scores")
```

Run: `cd backend && python3 _t2b.py`
Expected: `PASS t2b: mock path intact, 5 scores`

- [ ] **Step 7: Delete the harnesses and commit**

```bash
rm -f backend/_t2.py backend/_t2b.py
git add FSM_Scoring_Agent/backend/agent/scoring.py
git commit -m "feat(scoring): score requirement batches concurrently

Replace the sequential per-batch for-loop in _score_requirements with a
ThreadPoolExecutor(max_workers=MAX_CONCURRENCY); the providers gate bounds total
in-flight calls across vendors. Output is rebuilt in original reqs order so it is
identical regardless of completion order (regression anchor); progress counts
completed batches; cancellation is checked between completions; a failed batch
falls back to the deterministic engine per row. Mock path stays sequential.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Task 3: `/api/evaluate_batch` endpoint in `app.py`

**Files:**
- Modify: `backend/app.py` (add the route after `evaluate_upload`, i.e. after line 381; reuses `_new_job`, `_run_job`, `_split_urls`, `_validate_models`, `extract_sources`, `secure_filename`, `UPLOAD_DIR`, `ALLOWED_EXTS`, `uuid`)

**Interfaces:**
- Consumes: `_new_job() -> str`, `_run_job(jid, **kw)`, `_validate_models(*ids) -> str|None`, `_split_urls(raw) -> list`, `extract_sources(paths, urls) -> str`, `_JOBS`, `_JOBS_LOCK`.
- Produces: `POST /api/evaluate_batch` (multipart) → `202 {"batch_id": str, "jobs": [{"vendor": str, "job_id": str}], "rejected": [{"vendor": str, "reason": str}]}`.

**Request contract (multipart/form-data):**
- Shared: `count` (int, number of vendor rows), `scoring_model`, `vote_model` (or `vote_dual` JSON), `requirement_sample` (optional int).
- Per row `i` in `0..count-1`: `vendor_{i}` (str), `files_{i}` (repeatable file field), `urls_{i}` (newline/comma list).

- [ ] **Step 1: Write the failing test** (throwaway harness `backend/_t3.py`, uses Flask's test client + mock models so no keys/network)

```python
# backend/_t3.py — evaluate_batch launches one job per vendor and they complete
import io, time, json
import app as A
c = A.app.test_client()
data = {
    "count": "2",
    "scoring_model": "mock", "vote_model": "mock",
    "vendor_0": "Acme", "urls_0": "",
    "vendor_1": "Globex", "urls_1": "",
}
data["files_0"] = (io.BytesIO(b"Acme proposal: scheduling, dispatch, mobile."), "acme.txt")
data["files_1"] = (io.BytesIO(b"Globex proposal: billing and projects."), "globex.txt")
r = c.post("/api/evaluate_batch", data=data, content_type="multipart/form-data")
assert r.status_code == 202, (r.status_code, r.get_data(as_text=True))
body = r.get_json()
assert "batch_id" in body and len(body["jobs"]) == 2, body
vendors = sorted(j["vendor"] for j in body["jobs"])
assert vendors == ["Acme", "Globex"], vendors
# poll both jobs to completion
for j in body["jobs"]:
    for _ in range(50):
        s = c.get("/api/evaluate/status/" + j["job_id"]).get_json()
        if s["done"]:
            break
        time.sleep(0.1)
    assert s["done"] and not s["error"], (j["vendor"], s)
# a row with no files and no url is rejected, valid rows still run
data2 = {"count": "1", "scoring_model": "mock", "vote_model": "mock",
         "vendor_0": "Empty", "urls_0": ""}
r2 = c.post("/api/evaluate_batch", data=data2, content_type="multipart/form-data")
b2 = r2.get_json()
assert b2["jobs"] == [] and b2["rejected"] and b2["rejected"][0]["vendor"] == "Empty", b2
print("PASS t3: 2 jobs done, empty row rejected")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python3 _t3.py`
Expected: `assert r.status_code == 202` fails with `404` (route does not exist yet).

- [ ] **Step 3: Add the endpoint** — in `backend/app.py`, immediately after the `evaluate_upload` function (after line 381, before the `@app.route("/api/evaluate/status/<job_id>")` block) insert:

```python
@app.route("/api/evaluate_batch", methods=["POST"])
def evaluate_batch():
    """
    Evaluate MANY vendors in parallel from uploaded files/URLs (multipart/form-data).

    Shared fields: count, scoring_model, vote_model | vote_dual (JSON), requirement_sample?.
    Per row i in 0..count-1: vendor_i, files_i (repeatable), urls_i (newline/comma list).

    Launches one background job per valid vendor (the same machinery as the single
    endpoint); the global concurrency gate in providers.py bounds total in-flight LLM
    calls across all of them. Rows with no readable source are rejected, not fatal.
    """
    try:
        count = int(request.form.get("count", "0"))
    except ValueError:
        count = 0
    if count <= 0:
        return jsonify({"error": "count must be a positive integer"}), 400

    scoring_model = request.form.get("scoring_model", "mock")
    vote_model = request.form.get("vote_model", scoring_model)
    sample_n = request.form.get("requirement_sample", type=int)
    vote_dual = None
    if request.form.get("vote_dual"):
        try:
            vote_dual = json.loads(request.form["vote_dual"])
        except Exception:
            vote_dual = None
    pair_ids = [vote_dual[k] for k in ("openai", "anthropic", "synthesizer")
                if vote_dual and vote_dual.get(k)] if vote_dual else []
    err = _validate_models(scoring_model, vote_model, *pair_ids)
    if err:
        return jsonify({"error": err}), 400

    batch_id = uuid.uuid4().hex[:12]
    jobs, rejected = [], []
    for i in range(count):
        vendor = (request.form.get(f"vendor_{i}") or "").strip()
        if not vendor:
            rejected.append({"vendor": f"(row {i})", "reason": "missing vendor name"})
            continue
        urls = _split_urls(request.form.get(f"urls_{i}", ""))
        saved_paths, row_rejected = [], []
        vdir = os.path.join(UPLOAD_DIR, secure_filename(vendor) or "vendor")
        os.makedirs(vdir, exist_ok=True)
        for f in request.files.getlist(f"files_{i}"):
            if not f or not f.filename:
                continue
            name = secure_filename(f.filename)
            ext = os.path.splitext(name)[1].lower()
            if ext not in ALLOWED_EXTS:
                row_rejected.append(f.filename)
                continue
            dest = os.path.join(vdir, name)
            f.save(dest)
            saved_paths.append(dest)
        if not saved_paths and not urls:
            reason = "no file (.pdf/.docx/.xlsx/.txt/.md) or URL provided"
            if row_rejected:
                reason += f"; rejected unsupported: {', '.join(row_rejected)}"
            rejected.append({"vendor": vendor, "reason": reason})
            continue
        proposal_text = extract_sources(saved_paths, urls)
        if not (proposal_text or "").strip():
            rejected.append({"vendor": vendor, "reason": "no readable text extracted"})
            continue
        ingest_meta = {
            "files": [os.path.basename(p) for p in saved_paths],
            "urls": urls, "rejected": row_rejected, "chars_extracted": len(proposal_text),
        }
        jid = _new_job()
        with _JOBS_LOCK:
            _JOBS[jid]["ingest"] = ingest_meta
        threading.Thread(target=_run_job, kwargs=dict(
            jid=jid, vendor=vendor, product="", proposal_text=proposal_text,
            scoring_model=scoring_model, vote_model=vote_model, sample_n=sample_n,
            vote_dual=vote_dual), daemon=True).start()
        jobs.append({"vendor": vendor, "job_id": jid})

    if not jobs:
        return jsonify({"error": "No valid vendors to evaluate.", "rejected": rejected}), 400
    return jsonify({"batch_id": batch_id, "jobs": jobs, "rejected": rejected}), 202
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python3 _t3.py`
Expected: `PASS t3: 2 jobs done, empty row rejected`

- [ ] **Step 5: Delete the harness and commit**

```bash
rm -f backend/_t3.py
git add FSM_Scoring_Agent/backend/app.py
git commit -m "feat(api): /api/evaluate_batch fans N vendors to parallel jobs

Parse indexed multipart rows (vendor_i/files_i/urls_i + shared models), save each
vendor's files, extract text, and launch one existing-style background job per
valid vendor; the global gate bounds total in-flight calls. Rows with no readable
source are rejected without failing the batch. Returns {batch_id, jobs, rejected}.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Task 4: Batch evaluate tab (rows + pre-flight + board) in `frontend/index.html`

**Files:**
- Modify: `frontend/index.html` (add a `BatchRunner` component before `function App()` at line 1080; add the `["batch","Batch evaluate"]` nav entry at line 1131; mount the tab in the content area near line 1145)

**Interfaces:**
- Consumes: existing helpers `jget`, `jpost` (defined ~line 184-210), `fmt`, `STATIC`, and the App-level props `vendors`, `model` (scoring), `voteMode`, `voteModel`, `voteDual`, `onDone={loadResults}`. The status endpoint `/api/evaluate/status/<jid>`, cancel `/api/evaluate/cancel/<jid>`, and `POST /api/evaluate_batch` (Task 3).
- Produces: a `BatchRunner` React component rendered when `tab==="batch"`.

- [ ] **Step 1: Add the `BatchRunner` component** — insert this block immediately before `// ---- app ----` / `function App(){` (line 1079):

```jsx
// ---- batch runner: many vendors, one parallel run, live board -------------
const REQ_TOTAL = 422; // requirements in data/requirements.json; used only for the ~estimate
function BatchRunner({vendors, model, voteMode, voteModel, voteDual, onDone}){
  const [rows,setRows]=useState([{vendor:"", files:[], urls:""}]);
  const [confirm,setConfirm]=useState(null); // {text} pre-flight estimate, or null
  const [board,setBoard]=useState(null);     // [{vendor, job_id, stage, scored, total, done, error}]
  const [busy,setBusy]=useState(false);
  const [msg,setMsg]=useState(null);
  const ACCEPT=".pdf,.docx,.xlsx,.xlsm,.txt,.md";

  function setRow(i,patch){ setRows(rs=>rs.map((r,j)=>j===i?{...r,...patch}:r)); }
  function addRow(){ setRows(rs=>[...rs,{vendor:"", files:[], urls:""}]); }
  function removeRow(i){ setRows(rs=>rs.length>1?rs.filter((_,j)=>j!==i):rs); }
  function addFiles(i,list){ setRow(i,{files:[...rows[i].files,...Array.from(list)]}); }
  function removeFile(i,k){ setRow(i,{files:rows[i].files.filter((_,j)=>j!==k)}); }

  const valid = rows.filter(r=>r.vendor.trim() && (r.files.length>0 || r.urls.trim().length>0));
  const isMock = model==="mock";

  function preflight(){
    if(!valid.length){ setMsg({ok:false,text:"Add at least one vendor with a file or URL."}); return; }
    if(isMock){ launch(); return; } // free offline engine — no estimate needed
    const scoringPer=Math.ceil(REQ_TOTAL/12);
    const votePer=voteMode==="dual"?3:1;
    const n=valid.length;
    const text=`${n} vendor(s) x ~${scoringPer} = ~${n*scoringPer} scoring calls (${model})`
      +` + ${n*votePer} vote call(s) (${voteMode==="dual"?"dual":voteModel}). Proceed?`;
    setConfirm({text});
  }

  async function launch(){
    setConfirm(null); setBusy(true); setMsg(null);
    const fd=new FormData();
    fd.append("count",String(valid.length));
    fd.append("scoring_model",model);
    if(voteMode==="dual") fd.append("vote_dual",JSON.stringify(voteDual)); else fd.append("vote_model",voteModel);
    valid.forEach((r,i)=>{
      fd.append("vendor_"+i,r.vendor.trim());
      fd.append("urls_"+i,r.urls);
      r.files.forEach(f=>fd.append("files_"+i,f));
    });
    let res;
    try{
      const r=await fetch("/api/evaluate_batch",{method:"POST",body:fd});
      res=await r.json();
    }catch(e){ setBusy(false); setMsg({ok:false,text:"Batch upload failed - files may exceed the size limit, or the server is unreachable."}); return; }
    if(res.error){ setBusy(false); setMsg({ok:false,text:"Error: "+res.error}); return; }
    const init=res.jobs.map(j=>({...j, stage:"queued", scored:0, total:0, done:false, error:null}));
    setBoard(init);
    if(res.rejected && res.rejected.length) setMsg({ok:false,text:"Skipped: "+res.rejected.map(x=>x.vendor+" ("+x.reason+")").join("; ")});
    pollAll(init);
  }

  async function pollAll(jobs){
    const live={}; jobs.forEach(j=>live[j.job_id]=true);
    while(Object.values(live).some(Boolean)){
      await new Promise(r=>setTimeout(r,900));
      await Promise.all(jobs.map(async j=>{
        if(!live[j.job_id]) return;
        const s=await jget("/api/evaluate/status/"+j.job_id);
        setBoard(b=>b.map(x=>x.job_id===j.job_id?{...x, stage:s.stage, scored:s.scored, total:s.total, done:s.done, error:s.error}:x));
        if(s.done || s.error){ live[j.job_id]=false; }
      }));
    }
    setBusy(false); onDone();
  }
  async function cancelOne(jid){ await jpost("/api/evaluate/cancel/"+jid,{}); }

  const doneCount = board ? board.filter(b=>b.done).length : 0;

  return (
    <div>
      <div className="card" style={{marginBottom:14}}>
        <b className="small" style={{color:"var(--ssa-blue)"}}>Batch evaluate - run several vendors in parallel</b>
        {STATIC && <div className="small muted" style={{marginTop:6}}>Batch runs need the live server (the offline standalone is single-vendor only).</div>}
        {!STATIC && <>
          <div style={{marginTop:10,display:"flex",flexDirection:"column",gap:10}}>
            {rows.map((r,i)=>(
              <div key={i} className="grid" style={{gridTemplateColumns:"180px 1fr auto",gap:8,alignItems:"start"}}>
                <input className="pill" style={{padding:"8px 10px"}} placeholder="Vendor name"
                       value={r.vendor} onChange={e=>setRow(i,{vendor:e.target.value})}/>
                <div onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault(); addFiles(i,e.dataTransfer.files);}}>
                  <label className="btn ghost" style={{cursor:"pointer"}}>
                    + Files
                    <input type="file" multiple accept={ACCEPT} style={{display:"none"}}
                           onChange={e=>{addFiles(i,e.target.files); e.target.value="";}}/>
                  </label>
                  {r.files.length>0 && <div style={{display:"flex",flexWrap:"wrap",gap:6,marginTop:6}}>
                    {r.files.map((f,k)=>(<span key={k} className="pill">{f.name} <span style={{cursor:"pointer",color:"var(--bad)"}} onClick={()=>removeFile(i,k)}>&#10005;</span></span>))}
                  </div>}
                  <textarea value={r.urls} onChange={e=>setRow(i,{urls:e.target.value})} rows={1}
                    placeholder="or paste URL(s) - one per line"
                    style={{width:"100%",marginTop:6,border:"1px solid var(--line)",borderRadius:8,padding:"6px 8px",fontFamily:"var(--font)",fontSize:13}}/>
                </div>
                <button className="btn ghost" style={{padding:"6px 10px"}} onClick={()=>removeRow(i)} disabled={rows.length<=1}>Remove</button>
              </div>
            ))}
          </div>
          <div style={{marginTop:10,display:"flex",gap:8,alignItems:"center"}}>
            <button className="btn ghost" onClick={addRow}>+ Add vendor</button>
            <button className="btn" onClick={preflight} disabled={busy || !valid.length}>Run all ({valid.length})</button>
            {busy && <span className="small"><span className="spin"/> running…</span>}
          </div>
          {isMock && valid.length>0 && <div className="small" style={{color:"var(--warn)",marginTop:8}}>
            &#9888; A live model is recommended for real proposals - the offline "mock" engine doesn't read uploaded content deeply.
          </div>}
          {msg && <div className="small" style={{marginTop:8,color:msg.ok?"var(--good)":"var(--bad)"}}>{msg.text}</div>}
        </>}
      </div>

      {confirm && <div className="card" style={{marginBottom:14,borderColor:"var(--ssa-blue)"}}>
        <div className="small">{confirm.text}</div>
        <div style={{marginTop:8,display:"flex",gap:8}}>
          <button className="btn" onClick={launch}>Run all</button>
          <button className="btn ghost" onClick={()=>setConfirm(null)}>Cancel</button>
        </div>
      </div>}

      {board && <div className="card">
        <b className="small">Batch run - {doneCount} of {board.length} done</b>
        <div style={{marginTop:10,display:"flex",flexDirection:"column",gap:8}}>
          {board.map(b=>{
            const pct = b.total ? Math.round(100*b.scored/b.total) : (b.done?100:4);
            const state = b.error ? "error" : (b.done ? "done" : (b.stage||"queued"));
            return (
              <div key={b.job_id} className="grid" style={{gridTemplateColumns:"160px 1fr 120px",gap:10,alignItems:"center"}}>
                <span className="small" style={{fontWeight:600}}>{b.vendor}</span>
                <div style={{background:"var(--line)",borderRadius:6,height:10,overflow:"hidden"}}>
                  <div style={{width:pct+"%",height:"100%",background:b.error?"var(--bad)":"var(--ssa-blue)"}}/>
                </div>
                <span className="small muted">
                  {b.error ? ("error") :
                    b.done ? (<a href="#" onClick={e=>{e.preventDefault(); onDone();}}>done - view in Dashboard</a>) :
                    (<>{b.total?`${b.scored}/${b.total}`:state} <span style={{cursor:"pointer",color:"var(--bad)"}} onClick={()=>cancelOne(b.job_id)}>&#10005;</span></>)}
                </span>
              </div>
            );
          })}
        </div>
      </div>}
    </div>
  );
}
```

- [ ] **Step 2: Add the nav entry** — change the nav array at line 1131 to include the Batch tab between Compare and Methodology:

```jsx
        {[["dashboard","Dashboard"],["detail","Vendor detail"],["compare","Compare"],["batch","Batch evaluate"],["method","Methodology & rubric"],["chat","Ask the agent"]].map(([k,l])=>(
```

- [ ] **Step 3: Mount the tab** — after the `{tab==="compare" && <Compare results={results}/>}` line (line 1146) add:

```jsx
        {tab==="batch" && <BatchRunner vendors={vendors} model={model} voteMode={voteMode} voteModel={voteModel} voteDual={voteDual} onDone={loadResults}/>}
```

- [ ] **Step 4: Verify it compiles + mounts (headless)** — start the server, fetch the compiled DOM, confirm the app mounted (no Babel blank-page) and the Batch tab is present.

```bash
cd backend && (python3 app.py >/tmp/fsm_t4.log 2>&1 &) ; sleep 3
# 1 = compiled & mounted (Dashboard rendered); a Babel error would yield 0
curl -s --data-urlencode 'x=1' -G http://127.0.0.1:8000/ >/dev/null 2>&1 || true
python3 - <<'PY'
import urllib.request
html=urllib.request.urlopen("http://127.0.0.1:8000/").read().decode()
assert ">Dashboard<" in html or "id=\"root\"" in html, "index did not serve"
print("served index OK")
PY
```

Then drive it with a headless browser if available (chromium `--dump-dom`) and assert the Batch tab string appears; otherwise inspect manually in a browser:

```bash
# If chromium/chrome is available:
google-chrome --headless --disable-gpu --dump-dom http://127.0.0.1:8000/ 2>/dev/null | grep -c ">Dashboard<"
# Expected: 1  (app compiled and mounted; if 0, a JS/Babel error blanked the page)
pkill -f "python3 app.py" 2>/dev/null || true
```

Expected: `served index OK` and the grep prints `1`. Manually confirm in a browser that the **Batch evaluate** tab shows the vendor rows and "Run all".

- [ ] **Step 5: Commit**

```bash
git add FSM_Scoring_Agent/frontend/index.html
git commit -m "feat(ui): Batch evaluate tab - parallel multi-vendor run + live board

Add a BatchRunner: repeatable vendor rows (name + files/URLs), a pre-flight
call-count confirm on paid models (skipped for mock), and a live batch board that
polls each vendor's existing job-status endpoint with per-row progress, cancel,
and a link to the result. Single-vendor RunBar is untouched. ASCII-only JS
delimiters for in-browser Babel.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Task 5: Rebuild standalone + document the env knob

**Files:**
- Modify: `FSM_Evaluation_Agent_Standalone.html` (regenerated)
- Modify: `README.md`, `CLAUDE.md` (document `RESULTS_MAX_CONCURRENCY`)

- [ ] **Step 1: Document the env var in `CLAUDE.md`** — in the "Running it" section, after the `PORT` note, add a line:

```markdown
`RESULTS_MAX_CONCURRENCY` (default 6) caps how many LLM calls run at once across the
whole app (scoring batches + vendors share it); raise it if your provider rate limit
has headroom, lower it if you see 429s.
```

- [ ] **Step 2: Document the env var in `README.md`** — add the same `RESULTS_MAX_CONCURRENCY` line near where `PORT`/keys are described (search for `PORT` in `README.md`; place it alongside). If `README.md` has no env section, add a short "Environment variables" subsection listing `PORT`, the API keys, and `RESULTS_MAX_CONCURRENCY`.

- [ ] **Step 3: Rebuild the standalone bundle**

```bash
cd backend && python3 build_static.py
```
Expected: prints the written path `../FSM_Evaluation_Agent_Standalone.html` and a size (~1.5 MB).

- [ ] **Step 4: Verify the standalone still compiles (no blank page)**

```bash
# headless check if chromium is available, else open manually
google-chrome --headless --disable-gpu --dump-dom "file://$(cd .. && pwd)/FSM_Evaluation_Agent_Standalone.html" 2>/dev/null | grep -c ">Dashboard<"
# Expected: 1
```
Expected: `1`. The standalone is single-vendor by design; confirm it still shows the Dashboard and the existing RunBar (the Batch tab shows its "needs the live server" note under STATIC).

- [ ] **Step 5: Commit**

```bash
git add FSM_Scoring_Agent/FSM_Evaluation_Agent_Standalone.html FSM_Scoring_Agent/README.md FSM_Scoring_Agent/CLAUDE.md
git commit -m "build: rebuild standalone + document RESULTS_MAX_CONCURRENCY

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Manual end-to-end verification (after all tasks)

1. **Mock batch:** `cd backend && python3 app.py`, open the app, go to **Batch evaluate**, add 3 vendor rows each with a small `.txt`, scoring model `mock`, click **Run all** → board shows 3 rows reaching "done", results appear in the Dashboard.
2. **Live speed (keys present):** with `ANTHROPIC_API_KEY` set, pick Sonnet, run one vendor on the sample → completes in roughly `ceil(36 / RESULTS_MAX_CONCURRENCY)` waves rather than 36 serial calls (noticeably faster than before), no 429 storm in the server log.
3. **Cancel:** start a live batch, click a row's ✕ → that vendor stops cleanly ("cancelled"), the others finish.
4. **Pre-flight:** with a paid model selected, **Run all** shows the call-count confirm; with `mock` it fires immediately.

---

## Self-Review

**Spec coverage:** §2 concurrent batches → Task 2; one global env-tunable cap → Task 1 (`RESULTS_MAX_CONCURRENCY`/`_LLM_GATE`); retry+backoff on 429 → Task 1 (extends the existing `_is_transient` retry, now jittered, gate-held); bulk multi-vendor run / one job per vendor → Task 3; repeatable vendor rows + pre-flight call-count confirm + live batch board → Task 4; mock/single-vendor/persistence/evidence untouched → Tasks 2 & 4 (mock early-return preserved; RunBar untouched; no `store`/schema changes); standalone rebuilt + env documented → Task 5. §7 error cases: 429 retry (T1), per-batch fail-soft + ordering (T2), per-vendor reject + per-vendor error isolation (T3/T4), cancellation (T2/T4). All spec sections map to a task.

**Placeholder scan:** no TBD/TODO; every code step shows complete code; every test step shows the harness and expected output.

**Type consistency:** `MAX_CONCURRENCY` (constant) and `_LLM_GATE` are defined in Task 1 and consumed by name in Task 2; `_score_requirements` signature is unchanged; `/api/evaluate_batch` response keys (`batch_id`, `jobs[].vendor`, `jobs[].job_id`, `rejected[].vendor/.reason`) match between Task 3 (produces) and Task 4 (consumes); `_run_job`/`_new_job`/`_validate_models`/`extract_sources`/`_split_urls` are used with their real signatures from `app.py`.
