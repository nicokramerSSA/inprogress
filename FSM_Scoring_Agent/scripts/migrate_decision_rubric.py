#!/usr/bin/env python3
"""
Migrate the on-disk results store to the corrected decision rubric.

Usage:
    RESULTS_STORE_DIR=/var/data/... python3 scripts/migrate_decision_rubric.py

Backs up the store directory first (timestamped copy alongside it), then re-derives
every persisted evaluation's decision rollups in place from its already-scored
`requirement_scores` — no LLM calls. See backend/agent/migrate_decision_rubric.py
for what "re-derive" recomputes vs. leaves untouched.

Not run automatically anywhere; this is a deploy-time operator script.

WARNING — do NOT run this against the committee-facing five. Their headline numbers
are authored/curated values (see scripts/seed_committee_results.py), and re-deriving
them from evidence will REPLACE those numbers with the live engine's own output. This
tool is for bringing OTHER stored results onto the current engine, not for the curated
committee set. For the committee five, use seed_committee_results.py.
"""
import datetime
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from agent.migrate_decision_rubric import rederive_result  # noqa: E402
import store  # noqa: E402


def migrate_store() -> int:
    """Re-derive every persisted result and save it back. Returns the count migrated.

    Mirrors store.py's "one bad file never crashes" ethos: a record that fails to
    re-derive (e.g. missing requirement_scores) is logged and skipped rather than
    aborting the whole loop mid-way, so one bad file doesn't strand every other
    vendor's result un-migrated."""
    all_results = store.load_all()
    migrated = 0
    failed = 0
    for vendor, result in all_results.items():
        try:
            store.save(rederive_result(result))
            migrated += 1
        except Exception as e:
            failed += 1
            print(f"WARNING: skipping vendor '{vendor}' — re-derive failed: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
    print(f"{migrated} succeeded, {failed} failed out of {len(all_results)} result(s)")
    return migrated


def main() -> None:
    if os.path.isdir(store.STORE_DIR):
        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = store.STORE_DIR.rstrip("/") + f".backup-{stamp}"
        shutil.copytree(store.STORE_DIR, backup)
        print(f"backed up store -> {backup}")
    else:
        print(f"no existing store dir at {store.STORE_DIR}; nothing to back up")
    n = migrate_store()
    if n == 0:
        print(f"WARNING: migrated 0 result(s) from {store.STORE_DIR} — "
              f"check RESULTS_STORE_DIR is set correctly; this is NOT success.")
    else:
        print(f"migrated {n} result(s)")


if __name__ == "__main__":
    main()
