# Disk Persistence — Design

**Date:** 2026-06-24
**Roadmap item:** #2 (from `2026-06-23-dual-provider-vote-and-robustness-design.md` §9)
**Status:** Approved, ready for implementation plan
**Parallel sibling:** Evidence-source drill-down (#4) — specced separately
(`2026-06-24-evidence-drill-down-design.md`). The two touch disjoint files and
run as parallel branches.

---

## 1. Problem

Every evaluation lives only in the in-memory `_RESULTS` dict and dies on server
restart. `_seed_results()` reloads the bundled `data/sample_results.json` (the
five demo vendors) on boot, but anything the operator actually *ran* — a live
(paid) Opus evaluation against a real uploaded proposal, or a mock run against a
real proposal — is gone after a reboot. With real proposals due **2026-07-02**,
losing an expensive live run to a restart is a real cost.

This adds durable disk persistence: completed evaluations survive restart, while
the bundled demo seed remains the read-only factory default for a fresh checkout.

## 2. Goals / non-goals

**Goals**

- Completed evaluations survive a server restart.
- The bundled `sample_results.json` stays the read-only first-boot seed; a fresh
  checkout still shows the five demo vendors with no store present.
- Anything the operator runs (live *or* mock) persists and takes precedence over
  the bundled demo for that vendor.
- Human-inspectable, diffable storage consistent with the project's "no DB / all
  knowledge is editable JSON" ethos.
- On-disk schema is versioned so the future evidence-drill-down fields (#4) drop
  in with an additive bump, no migration pain.
- The offline standalone build is unaffected (it is pure client-side).

**Non-goals (this round)**

- **No run history.** Re-evaluating overwrites the vendor's stored result;
  the store keeps only the current result per vendor (durable-latest). A
  "compare runs over time" capability would be its own future item.
- **No SQLite / no database.** Versioned JSON files only.
- **No UI reset/delete endpoint.** Re-evaluating overwrites a bad run; a full
  reset is `rm -rf data/store/` (the store dir is gitignored). Documented, not
  built.
- No change to the in-memory `_RESULTS` shape or to any API response shape — the
  version wrapper is on-disk only.
- No change to how uploads are stored (`data/uploads/<vendor>/` already exists
  and is out of scope).

## 3. Decision record (why versioned JSON, durable-latest)

- **Versioned JSON over SQLite.** CLAUDE.md states the project convention
  explicitly: "No DB." All knowledge is editable JSON. With at most a handful of
  vendors and lock-serialized writes, SQLite's concurrency and query strengths
  are unused, while it would add a binary, non-inspectable store. JSON files stay
  diffable, mirror the existing `sample_results.json` shape, and are trivially
  resettable.
- **Durable-latest over run history.** The problem is "survive restart," which
  durable-latest solves with the least surface. Run history adds storage and a
  history-management UI for a capability nobody has requested (YAGNI).
- **Store wins over demo seed.** Once the operator runs an evaluation, that is
  the real result; the bundled demo is only a placeholder. So the boot overlay
  applies the store *after* the demo seed, store winning per vendor.

## 4. Architecture

`_RESULTS` (in `app.py`) remains the single runtime source of truth. A new
app-layer module `backend/store.py` owns **all** disk I/O for runtime
evaluations. `app.py` calls it in exactly two functional places (boot load,
eval-complete write) plus one `.gitignore` addition.

```
boot:            sample_results.json ──seed──▶ _RESULTS ──overlay (store wins)──▶ store.load_all()
eval complete:   _run_and_cache ──_RESULTS[vendor]=result (lock)──▶ store.save(result) (atomic file)
read:            /api/results ──▶ list(_RESULTS.values())   (unchanged)
```

## 5. Component — `backend/store.py`

Responsibility: persist and reload runtime evaluation dicts as versioned JSON.
Pure functions over a directory; no knowledge of Flask, scoring, or the engine.

**Constants**

- `SCHEMA_VERSION = 1`
- `STORE_DIR` = `os.environ.get("RESULTS_STORE_DIR")` or
  `<backend>/data/store/results` by default.

**Functions**

- `save(result: dict) -> None`
  - Compute a filesystem-safe slug from `result["vendor"]` (lowercase, non-alnum
    → `-`, collapse repeats, strip). Empty/all-symbol vendor → slug `"_"`.
  - Write `{"schema_version": SCHEMA_VERSION, "saved_at": <iso8601 UTC>,
    "result": result}` to `<STORE_DIR>/<slug>.json`.
  - **Atomic:** write to `<slug>.json.tmp` in the same dir, `os.replace` onto the
    final name. Create `STORE_DIR` (and parents) if absent.
  - Vendor name lives inside `result`, so the slug is only a filename; a slug
    collision between two distinct vendors is last-write-wins (acceptable at this
    scale and noted).
- `load_all() -> dict[str, dict]`
  - If `STORE_DIR` does not exist, return `{}`.
  - For each `*.json` in `STORE_DIR`: read, parse, migrate by `schema_version`
    (v1 = passthrough; `_migrate(record)` is the forward-migration hook), extract
    `record["result"]`, key the returned dict by `result["vendor"]`.
  - A file that fails to read/parse, lacks `result`, or lacks `result["vendor"]`
    is **skipped with a logged warning** — a single bad file must never crash
    boot. (`.tmp` leftovers from an interrupted write are ignored — only `*.json`
    is read.)

## 6. `app.py` changes

1. **Import:** `import store` (sibling module; `app.py` already runs from
   `backend/`).
2. **Boot overlay.** In `_seed_results()` (still called from `__main__`), after
   the existing demo seed loop, overlay the store:
   ```python
   for vendor, result in store.load_all().items():
       _RESULTS[vendor] = result   # store wins over the demo seed
   ```
   Wrapped in try/except with a logged warning so a store problem never blocks
   boot (mirrors the existing seed's soft-fail).
3. **Persist on completion.** In `_run_and_cache`, after the `with _RESULTS_LOCK:`
   block that sets `_RESULTS[vendor] = result`, call `store.save(result)`
   **outside** the lock (disk I/O must not be held under the in-memory lock).
   Wrap in try/except + warning: a failed disk write must not fail the
   evaluation the user already paid for — the result is still served from memory;
   it just is not durable until the next successful save.
4. **`.gitignore`:** add `backend/data/store/`.

## 7. Error handling & edge cases

- **Corrupt / partial store file** → `load_all` skips it with a warning; that
  vendor falls back to the demo seed. Boot survives.
- **Store dir absent** → `load_all` returns `{}`; created on first `save`.
- **Concurrent background jobs** → different vendors write different files (no
  contention); same vendor re-eval is an atomic `os.replace`.
- **Demo overwrite** → running any evaluation for a vendor persists it and
  overrides that vendor's bundled demo on next boot. This is intended. Reset =
  delete `data/store/`.
- **Secrets** → the result dict carries `model_used`, never API keys, so nothing
  secret reaches disk (consistent with "keys from env only, never written").
- **Failed save** → logged warning; the in-memory result is unaffected and still
  served. Durability resumes on the next successful save.
- The store module never mutates the dict it is handed; it only reads/writes.

## 8. Testing / verification

No automated test suite (project convention — verification is manual). Verify:

1. Run a mock evaluation for a vendor → a `<slug>.json` appears under
   `data/store/results/` with `schema_version`, `saved_at`, and `result`.
2. Restart the server → `/api/results` shows the persisted evaluation overriding
   that vendor's bundled demo (e.g. `evaluated_at`/`model_used` match the run,
   not the seed).
3. Corrupt one store file (truncate it) → boot still succeeds, logs a warning,
   and that vendor falls back to the demo seed.
4. Fresh checkout / empty store (`rm -rf data/store/`, or rename it) → the five
   bundled demos show exactly as before.
5. Two different vendors evaluated back-to-back → two distinct files, both load
   after restart.
6. The standalone build (`python3 build_static.py`) is unaffected — confirm it
   still renders (client-side; no Flask, no store).

## 9. Risk & rollback

Purely additive: one new module (`store.py`) plus a boot overlay, one save call,
and a `.gitignore` line in `app.py`. No change to engine, schemas, API shapes, or
the in-memory store's structure. Rollback = revert the `app.py` changes and
delete `store.py`; the bundled demo seed path is exactly as it was. The future
evidence fields (#4) persist for free because `save`/`load_all` are
content-agnostic over the result dict.
