#!/usr/bin/env python3
"""
Seed the on-disk results store with the committee-facing curated evaluations.

Usage:
    RESULTS_STORE_DIR=/var/data/... python3 scripts/seed_committee_results.py

This is the deploy tool for the "curated display, real engine underneath" model.
The five committee-facing results (their headline numbers and verdicts) are authored
values held in backend/data/sample_results.json — they are the evaluator's considered
call, not something the live engine derives. In production SEED_DEMO_RESULTS=0, so the
seed file is NOT loaded on boot; the Render disk store is the only thing displayed.
This script writes the curated five into that store so the UI shows them.

Backs up the store directory first (timestamped copy alongside it), then writes each
curated result via store.save (keyed by vendor). Re-running is safe — it overwrites the
same vendors. No LLM calls, no engine recomputation: the numbers are copied verbatim.

Note: this does the OPPOSITE of scripts/migrate_decision_rubric.py, which recomputes
stored results to fresh evidence-derived numbers. Use THIS script for the committee five.
"""
import datetime
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

import store  # noqa: E402

CURATED = os.path.join(HERE, "..", "backend", "data", "sample_results.json")


def seed_store(path: str = CURATED) -> int:
    """Write every curated result into the store. Returns the count written.

    One bad record is logged and skipped rather than aborting the loop, mirroring
    store.py's "one bad file never crashes" ethos."""
    with open(path, "r", encoding="utf-8") as f:
        curated = json.load(f)
    written = 0
    failed = 0
    for result in curated:
        vendor = result.get("vendor", "?")
        try:
            store.save(result)
            written += 1
            print(f"seeded {vendor}: decision={result.get('weighted_total')} "
                  f"vote={(result.get('vote') or {}).get('recommendation')}")
        except Exception as e:
            failed += 1
            print(f"WARNING: skipping '{vendor}' — save failed: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
    print(f"{written} seeded, {failed} failed out of {len(curated)} curated result(s)")
    return written


def main() -> None:
    if os.path.isdir(store.STORE_DIR):
        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = store.STORE_DIR.rstrip("/") + f".backup-{stamp}"
        shutil.copytree(store.STORE_DIR, backup)
        print(f"backed up store -> {backup}")
    else:
        print(f"no existing store dir at {store.STORE_DIR}; it will be created")
    n = seed_store()
    if n == 0:
        print(f"WARNING: seeded 0 result(s) into {store.STORE_DIR} — "
              f"check the curated file exists; this is NOT success.")
    else:
        print(f"seeded {n} curated result(s). Restart the service so it reloads the store.")


if __name__ == "__main__":
    main()
