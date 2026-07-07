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
"""
import datetime
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from agent.migrate_decision_rubric import rederive_result  # noqa: E402
import store  # noqa: E402


def migrate_store() -> int:
    """Re-derive every persisted result and save it back. Returns the count migrated."""
    all_results = store.load_all()
    for vendor, result in all_results.items():
        store.save(rederive_result(result))
    return len(all_results)


def main() -> None:
    if os.path.isdir(store.STORE_DIR):
        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = store.STORE_DIR.rstrip("/") + f".backup-{stamp}"
        shutil.copytree(store.STORE_DIR, backup)
        print(f"backed up store -> {backup}")
    else:
        print(f"no existing store dir at {store.STORE_DIR}; nothing to back up")
    n = migrate_store()
    print(f"migrated {n} result(s)")


if __name__ == "__main__":
    main()
