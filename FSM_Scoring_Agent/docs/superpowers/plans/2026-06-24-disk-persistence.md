# Disk Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completed vendor evaluations survive a server restart via a versioned JSON disk store, overlaid on top of the read-only demo seed at boot.

**Architecture:** A new app-layer module `backend/store.py` owns all disk I/O for runtime evaluations (one versioned JSON file per vendor, durable-latest). `app.py`'s in-memory `_RESULTS` stays the runtime source of truth; `store.py` is its durable shadow. `app.py` calls it in exactly two functional places — boot overlay (after the demo seed, store wins) and save-on-completion — plus one `.gitignore` line.

**Tech Stack:** Python 3.12 (invoked as `python3`), Flask, stdlib `json`/`os`/`tempfile`/`logging`. No new dependencies. No automated test suite in this project — pure-function verification uses standalone `python3` heredoc harnesses; integration is verified manually.

## Global Constraints

- **No DB / versioned JSON only.** CLAUDE.md: "No DB." Storage is human-inspectable JSON files.
- **Keys never written to disk.** The result dict carries `model_used`, never API keys. `store.py` persists only the result dict; nothing secret reaches disk.
- **The offline mock engine must always work.** Persistence must not break the keyless path.
- **No change to the in-memory `_RESULTS` shape or any API response shape.** The `schema_version` wrapper is on-disk only.
- **Durable-latest.** Re-evaluating a vendor overwrites its stored result; no run history.
- **Store wins over the demo seed.** On boot: seed `sample_results.json`, then overlay `store.load_all()` (store wins per vendor).
- **Atomic writes.** Write a temp file, then `os.replace` onto the final name.
- **Store dir is gitignored.** Add `backend/data/store/` to `.gitignore`.
- **`python3`, never `python`.** This WSL env has no `python` alias.
- **Do NOT touch** `ingest.py`, `scoring.py`, `schemas.py`, or `frontend/index.html` — those belong to the parallel evidence-drill-down branch (#4).

---

### Task 1: `backend/store.py` — versioned JSON result store

**Files:**
- Create: `backend/store.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `STORE_DIR: str` — `os.environ["RESULTS_STORE_DIR"]` or `<backend>/data/store/results`.
  - `save(result: dict) -> None` — atomically writes `{schema_version, saved_at, result}` to `<STORE_DIR>/<slug>.json`.
  - `load_all() -> dict[str, dict]` — vendor name → result dict, for every readable `*.json`; `{}` if the dir is absent; bad files skipped with a warning.

- [ ] **Step 1: Write the module**

Create `backend/store.py` with exactly this content:

```python
"""
store.py — durable disk persistence for runtime vendor evaluations.

Evaluations live in app.py's in-memory _RESULTS at runtime; this module is their
durable shadow on disk so they survive a restart. Storage is versioned JSON, one
file per vendor (durable-latest: a re-eval overwrites). The bundled demo seed
(data/sample_results.json) stays the read-only first-boot default; on boot the
store is overlaid on top of it (store wins per vendor).

Consistent with the project ethos: no DB, human-inspectable JSON, keys never
written (the result dict carries model_used, never API keys).
"""
from __future__ import annotations

import os
import re
import json
import logging
import tempfile
from datetime import datetime, timezone
from typing import Dict, Any

_log = logging.getLogger("store")

SCHEMA_VERSION = 1

_HERE = os.path.dirname(os.path.abspath(__file__))
STORE_DIR = os.environ.get(
    "RESULTS_STORE_DIR",
    os.path.join(_HERE, "data", "store", "results"),
)


def _slug(vendor: str) -> str:
    """Filesystem-safe slug for a vendor name. Vendor identity lives inside the
    file content, so the slug is only a filename; a collision between two distinct
    vendors is last-write-wins (acceptable at this scale)."""
    s = re.sub(r"[^a-z0-9]+", "-", (vendor or "").lower()).strip("-")
    return s or "_"


def save(result: Dict[str, Any]) -> None:
    """Persist one evaluation dict atomically as versioned JSON. Writes
    {schema_version, saved_at, result} to <STORE_DIR>/<slug>.json via a temp file
    + os.replace, so a crash never leaves a half-written file in place."""
    os.makedirs(STORE_DIR, exist_ok=True)
    record = {
        "schema_version": SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result": result,
    }
    path = os.path.join(STORE_DIR, _slug(result.get("vendor", "")) + ".json")
    fd, tmp = tempfile.mkstemp(dir=STORE_DIR, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _migrate(record: Dict[str, Any]) -> Dict[str, Any]:
    """Forward-migrate an on-disk record to the current schema. v1 = passthrough;
    future additive field changes (e.g. evidence drill-down) are absorbed here
    without a data migration."""
    return record


def load_all() -> Dict[str, Dict[str, Any]]:
    """Load every persisted evaluation, keyed by vendor name. A file that cannot
    be read/parsed (or lacks result.vendor) is skipped with a warning — one bad
    file must never crash boot. Returns {} if the store dir does not exist. Only
    *.json files are read, so *.json.tmp leftovers from an interrupted write are
    ignored."""
    out: Dict[str, Dict[str, Any]] = {}
    if not os.path.isdir(STORE_DIR):
        return out
    for name in sorted(os.listdir(STORE_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(STORE_DIR, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = _migrate(json.load(f))
            result = record["result"]
            vendor = result["vendor"]
        except Exception as e:
            _log.warning("skipping unreadable result file %s: %s: %s",
                         name, type(e).__name__, e)
            continue
        out[vendor] = result
    return out
```

- [ ] **Step 2: Run the acceptance harness (round-trip, overwrite, corrupt-skip, empty-dir, slug)**

Run from `backend/` (the harness points the store at a temp dir via env, so it never writes into the repo). Run it *before* writing the module to see it fail (ImportError), then after to see it pass:

```bash
cd backend && rm -rf /tmp/store_test && RESULTS_STORE_DIR=/tmp/store_test python3 - <<'PY'
import os, json, store

# 1) empty / missing dir -> {}
assert store.load_all() == {}, "missing dir should yield {}"

# 2) save + round-trip
r1 = {"vendor": "Aerion Systems", "weighted_total": 78.0, "model_used": "mock"}
store.save(r1)
loaded = store.load_all()
assert loaded == {"Aerion Systems": r1}, loaded
# file is wrapped with schema_version + saved_at
raw = json.load(open(os.path.join(store.STORE_DIR, "aerion-systems.json")))
assert raw["schema_version"] == 1 and "saved_at" in raw and raw["result"] == r1, raw

# 3) durable-latest: re-save overwrites
store.save({**r1, "weighted_total": 80.0})
assert store.load_all()["Aerion Systems"]["weighted_total"] == 80.0

# 4) second vendor -> separate file, both load
store.save({"vendor": "Brightfield", "weighted_total": 61.0})
assert set(store.load_all()) == {"Aerion Systems", "Brightfield"}

# 5) corrupt file is skipped, others still load
open(os.path.join(store.STORE_DIR, "broken.json"), "w").write("{ not json")
got = store.load_all()
assert set(got) == {"Aerion Systems", "Brightfield"}, got

# 6) .json.tmp leftover is ignored
open(os.path.join(store.STORE_DIR, "leftover.json.tmp"), "w").write("{}")
assert set(store.load_all()) == {"Aerion Systems", "Brightfield"}

# 7) slug edge cases
assert store._slug("") == "_"
assert store._slug("A/B C!") == "a-b-c"
print("STORE OK")
PY
```

Expected: `STORE OK` (the corrupt-file skip logs a `WARNING:store:` line — that is correct, not a failure).

- [ ] **Step 3: Commit**

```bash
cd backend && git add store.py && git commit -m "feat(persist): versioned JSON result store (store.py)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

### Task 2: Wire persistence into `app.py` (boot overlay + save-on-completion) + `.gitignore`

**Files:**
- Modify: `backend/app.py` (import; `_run_and_cache` ~L104-124; `_seed_results` ~L186-193)
- Modify: `.gitignore` (repo root)

**Interfaces:**
- Consumes: `store.save(result)`, `store.load_all()` from Task 1.
- Produces: no new public interface; `/api/results` now serves demo seed overlaid by the persisted store, and completed evaluations are written to disk.

- [ ] **Step 1: Import the store module**

In `backend/app.py`, immediately after the agent import block (after `from agent.sample import sample_proposal_text`, ~L73), add:

```python
import store  # app-layer disk persistence for runtime evaluations (sibling module)
```

- [ ] **Step 2: Persist on completion in `_run_and_cache`**

In `backend/app.py`, in `_run_and_cache`, replace this tail (currently ~L122-124):

```python
    with _RESULTS_LOCK:
        _RESULTS[vendor] = result
    return result
```

with:

```python
    with _RESULTS_LOCK:
        _RESULTS[vendor] = result
    # Persist outside the in-memory lock (disk I/O must not be held under it). A
    # failed write must not fail an evaluation the user already paid for — the
    # result is still served from memory and will persist on the next success.
    try:
        store.save(result)
    except Exception as e:
        app.logger.warning("Could not persist result for %s: %s", vendor, e)
    return result
```

- [ ] **Step 3: Overlay the store on boot in `_seed_results`**

In `backend/app.py`, replace `_seed_results` (currently ~L186-193):

```python
def _seed_results():
    if os.path.exists(SAMPLE_RESULTS):
        try:
            with open(SAMPLE_RESULTS, "r", encoding="utf-8") as f:
                for ev in json.load(f):
                    _RESULTS[ev["vendor"]] = ev
        except Exception as e:
            app.logger.warning("Could not seed sample results: %s", e)
```

with:

```python
def _seed_results():
    # 1) Read-only demo seed (the five bundled vendors) so the UI has content on
    #    first boot / fresh checkout.
    if os.path.exists(SAMPLE_RESULTS):
        try:
            with open(SAMPLE_RESULTS, "r", encoding="utf-8") as f:
                for ev in json.load(f):
                    _RESULTS[ev["vendor"]] = ev
        except Exception as e:
            app.logger.warning("Could not seed sample results: %s", e)
    # 2) Overlay persisted runtime evaluations (durable-latest). The store wins
    #    over the demo seed: once the operator runs an evaluation, that is the
    #    real result. A store problem must never block boot.
    try:
        for vendor, result in store.load_all().items():
            _RESULTS[vendor] = result
    except Exception as e:
        app.logger.warning("Could not load persisted results: %s", e)
```

- [ ] **Step 4: Gitignore the store dir**

The git root is `/home/chagood/workspace/projects/RFP Agent` (one level *above* `FSM_Scoring_Agent/`). Append to `/home/chagood/workspace/projects/RFP Agent/.gitignore` (create the file if absent):

```
# Runtime evaluation store (durable-latest; not source)
FSM_Scoring_Agent/backend/data/store/
```

Verify with Step 6 (`git check-ignore`).

- [ ] **Step 5: Verify save + restart persistence end-to-end (mock engine, no keys)**

The status route is `/api/evaluate/status/<job_id>` (confirmed in `app.py` ~L364).

```bash
cd backend && rm -rf data/store
# Start the server (mock engine), submit one evaluation, poll to completion.
python3 app.py >/tmp/persist_app.log 2>&1 &
APP=$!; sleep 2
JID=$(curl -s -X POST localhost:8000/api/evaluate -H 'Content-Type: application/json' \
  -d '{"vendor":"IFS","use_sample":true,"scoring_model":"mock","vote_model":"mock"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
for i in $(seq 1 30); do
  DONE=$(curl -s localhost:8000/api/evaluate/status/$JID | python3 -c 'import sys,json;print(json.load(sys.stdin).get("done"))')
  [ "$DONE" = "True" ] && break; sleep 1
done
ls -1 data/store/results/                       # expect: ifs.json
kill $APP; sleep 1
# Restart and confirm the persisted IFS result is served (model_used=mock from the run).
python3 app.py >/tmp/persist_app2.log 2>&1 &
APP=$!; sleep 2
curl -s localhost:8000/api/results | python3 -c '
import sys,json
rs={r["vendor"]:r for r in json.load(sys.stdin)}
print("n_results", len(rs))
print("IFS model_used", rs["IFS"]["model_used"])
'
kill $APP
```

Expected: `data/store/results/ifs.json` exists after the run; after restart `n_results 5` and `IFS model_used mock` (the persisted run overriding the bundled demo).

- [ ] **Step 6: Verify corrupt-file resilience + fresh-checkout + gitignore**

```bash
cd backend
# Corrupt the persisted file -> boot still succeeds, that vendor falls back to demo.
echo "{ broken" > data/store/results/ifs.json
python3 app.py >/tmp/persist_app3.log 2>&1 &
APP=$!; sleep 2
curl -s localhost:8000/api/health | python3 -c 'import sys,json;print("ok",json.load(sys.stdin)["ok"])'
grep -i "skipping unreadable" /tmp/persist_app3.log || echo "(warning line optional)"
kill $APP
# Fresh checkout: no store -> exactly the 5 bundled demos.
rm -rf data/store
python3 app.py >/tmp/persist_app4.log 2>&1 &
APP=$!; sleep 2
curl -s localhost:8000/api/results | python3 -c 'import sys,json;print("n_results",len(json.load(sys.stdin)))'
kill $APP
# Gitignore: the store dir must be untracked/ignored.
mkdir -p data/store/results && echo '{}' > data/store/results/probe.json
git check-ignore -v data/store/results/probe.json && rm -rf data/store
```

Expected: health `ok True` with a corrupt file present; `n_results 5` on a fresh checkout; `git check-ignore` prints a matching `.gitignore` rule (proving the store is ignored).

- [ ] **Step 7: Confirm the standalone build is unaffected**

```bash
cd backend && python3 build_static.py && ls -la ../FSM_Evaluation_Agent_Standalone.html
```

Expected: rebuilds without error (the standalone is client-side; it does not use the store). Optional headless render check:
`google-chrome --headless --disable-gpu --no-sandbox --dump-dom file://$(cd .. && pwd)/FSM_Evaluation_Agent_Standalone.html | grep -c ">Dashboard<"` → `1`.

- [ ] **Step 8: Commit**

```bash
cd "/home/chagood/workspace/projects/RFP Agent" && git add FSM_Scoring_Agent/backend/app.py .gitignore && git commit -m "feat(persist): overlay store on boot + save on completion; gitignore store dir

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

(Do NOT commit the rebuilt standalone from Step 7 — persistence makes no UI change, so committing it only adds noise.)

---

## Notes for the executor

- Tasks are sequential (Task 2 imports Task 1's module). Task 1 is mechanical (cheap model); Task 2 is integration (standard model).
- This plan touches only `backend/store.py`, `backend/app.py`, and `.gitignore`. It must not touch `ingest.py`, `scoring.py`, `schemas.py`, or `frontend/index.html` (parallel evidence branch).
