"""committee.py — parse + aggregate human committee scorecards (CSV/Excel).

Tolerant by design: required columns are evaluator/vendor/score; verdict and
per-category columns are optional. Bad rows become warnings, never crashes.
Excel needs openpyxl; if it's absent we tell the user to upload CSV (soft-fail).
"""
from __future__ import annotations
import csv, io, statistics
from typing import List, Dict, Any, Tuple, Optional

REQUIRED = ("evaluator", "vendor", "score")
_KNOWN = {"evaluator", "vendor", "score", "verdict"}

def _norm(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "").replace("_", "")

def _rows_from_header(header: List[str], raw_rows: List[List[str]]) -> Tuple[Optional[List[dict]], List[str]]:
    idx = {_norm(h): i for i, h in enumerate(header)}
    for req in REQUIRED:
        if req not in idx:
            return None, [f"Missing required column '{req}'. Found: {', '.join(str(h) for h in header)}."]
    cat_cols = [(h, i) for h, i in idx.items() if h not in _KNOWN]
    rows: List[dict] = []
    warnings: List[str] = []
    for n, raw in enumerate(raw_rows, start=2):
        if not any(str(c or "").strip() for c in raw):
            continue
        try:
            ev = str(raw[idx["evaluator"]]).strip()
            vn = str(raw[idx["vendor"]]).strip()
            sc = float(str(raw[idx["score"]]).strip())
        except (IndexError, ValueError):
            warnings.append(f"Row {n}: could not read evaluator/vendor/score — skipped.")
            continue
        if not ev or not vn:
            warnings.append(f"Row {n}: blank evaluator or vendor — skipped.")
            continue
        if not (0 <= sc <= 100):
            warnings.append(f"Row {n}: score {sc} out of 0–100 — skipped.")
            continue
        row: Dict[str, Any] = {"evaluator": ev, "vendor": vn, "score": sc}
        if "verdict" in idx and idx["verdict"] < len(raw):
            v = str(raw[idx["verdict"]]).strip()
            if v:
                row["verdict"] = v
        cats: Dict[str, float] = {}
        for h, i in cat_cols:
            if i < len(raw):
                try:
                    cats[h] = float(str(raw[i]).strip())
                except ValueError:
                    pass
        if cats:
            row["categories"] = cats
        rows.append(row)
    return rows, warnings

def _parse_csv(data: bytes) -> dict:
    text = data.decode("utf-8-sig", errors="replace")
    reader = list(csv.reader(io.StringIO(text)))
    if not reader:
        return {"error": "Empty file.", "rows": [], "warnings": []}
    rows, warnings = _rows_from_header(reader[0], reader[1:])
    if rows is None:
        return {"error": warnings[0], "rows": [], "warnings": []}
    return {"rows": rows, "warnings": warnings}

def _parse_xlsx(data: bytes) -> dict:
    import openpyxl  # caller guarantees availability
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    grid = [list(row) for row in ws.iter_rows(values_only=True)]
    if not grid:
        return {"error": "Empty sheet.", "rows": [], "warnings": []}
    header = [str(c) if c is not None else "" for c in grid[0]]
    body = [[("" if c is None else str(c)) for c in r] for r in grid[1:]]
    rows, warnings = _rows_from_header(header, body)
    if rows is None:
        return {"error": warnings[0], "rows": [], "warnings": []}
    return {"rows": rows, "warnings": warnings}

def parse_committee_file(data: bytes, filename: str) -> dict:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl  # noqa: F401
        except Exception:
            return {"error": "Excel parsing needs openpyxl on the server. Please upload a CSV instead.",
                    "rows": [], "warnings": []}
        try:
            return _parse_xlsx(data)
        except Exception:
            return {"error": "Could not read that Excel file. Please re-save it or upload a CSV.",
                    "rows": [], "warnings": []}
    try:
        return _parse_csv(data)
    except Exception:
        return {"error": "Could not read that CSV file.", "rows": [], "warnings": []}

def aggregate_committee(rows: List[dict]) -> dict:
    by_vendor: Dict[str, List[dict]] = {}
    for r in rows:
        by_vendor.setdefault(r["vendor"], []).append(r)
    vendors = []
    for vn, rs in by_vendor.items():
        scores = [r["score"] for r in rs]
        verdict_counts: Dict[str, int] = {}
        for r in rs:
            v = r.get("verdict")
            if v:
                verdict_counts[v] = verdict_counts.get(v, 0) + 1
        modal = max(verdict_counts, key=verdict_counts.get) if verdict_counts else None
        cats: Dict[str, List[float]] = {}
        for r in rs:
            for k, v in (r.get("categories") or {}).items():
                cats.setdefault(k, []).append(v)
        cat_means = {k: round(statistics.mean(v), 1) for k, v in cats.items()}
        vendors.append({
            "vendor": vn,
            "mean_score": round(statistics.mean(scores), 1),
            "min": round(min(scores), 1),
            "max": round(max(scores), 1),
            "stddev": round(statistics.pstdev(scores), 1) if len(scores) > 1 else 0.0,
            "n_evaluators": len(rs),
            "verdict_counts": verdict_counts,
            "modal_verdict": modal,
            "category_means": cat_means,
        })
    vendors.sort(key=lambda v: -v["mean_score"])
    return {"vendors": vendors, "n_evaluators_total": len(rows), "warnings": []}
