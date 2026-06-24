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
