# Demo-Feedback Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four demo-feedback updates — response-completeness + red flags, an advisory winner/shortlist read, committee scorecard ingestion shown side-by-side, and advisory framing — per `docs/superpowers/specs/2026-06-25-demo-feedback-updates-design.md`.

**Architecture:** Features 1, 2, 4 are pure frontend derivations over data `/api/results` already returns. Feature 3 adds one backend module (`committee.py`), a few `app.py` endpoints with an in-memory store, a CSV template, and a new top-level "Committee scores" tab. No database. The offline standalone keeps working (committee upload gates on `STATIC`).

**Tech Stack:** Python 3.12 / Flask (stdlib `csv`; `openpyxl` optional, soft-fail to CSV). React 18 via CDN + Babel-in-browser (single `<script type="text/babel">` block in `frontend/index.html`). No test framework — verification is esbuild JSX transpile + small Node/Python scripts + manual checks.

## Global Constraints

- No new **required** dependencies. Excel parsing uses `openpyxl` only if importable; otherwise return a clear error telling the user to upload CSV. Never crash on a missing optional dep.
- No database. Committee data lives in a module-level dict in `app.py`, mirroring `_RESULTS`.
- The offline standalone (`FSM_Evaluation_Agent_Standalone.html`) must keep working. Committee upload is gated on `!STATIC`; everything else derives client-side and works offline.
- The offline "mock" engine must keep working. Don't touch the scoring pipeline.
- Reuse existing helpers verbatim: `fmt`, `jget`, `jpost`, `recoClass`, `STATIC`, `downloadCSV`, `exportFilename`. Reuse CSS variables (`--ssa-blue`, `--good`, `--warn`, `--bad`, `--line`, `--muted`) and existing classes (`card`, `section-title`, `table-scroll`, `dashboard-table`, `met-Yes`, `met-No`, `pill`, `badge`).
- Exact advisory framing string (used in two places): `The agent's advisory view — one input to your decision, not the decision. Built to be challenged.`
- Low-coverage threshold constant: `LOW_COVERAGE_PCT = 85`.
- After every frontend edit, transpile the Babel block with esbuild to catch syntax errors before manual testing (command in Task 1).
- Rebuild the standalone with `python3 build_static.py` only at the very end (Task 8).
- Commit after each task. End commit messages with the repo's required trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` and the `Claude-Session:` line.

### Completeness derivation (single source of truth — used by Tasks 1 & 3)
Over `requirement_scores` with `met !== "N/A"`:
- **not addressed** (silent): `met === "No"` AND `evidence` empty.
- **addressed**: everything else.
- `coverage_pct = round(addressed / total * 100)`; `low = coverage_pct < 85`.

---

## Task 1: Frontend derivation helpers

**Files:**
- Modify: `frontend/index.html` — add helpers just after `const recoClass = ...` (currently line 225).
- Test: `scratchpad/test_derivations.mjs` (Node, throwaway — not committed).

**Interfaces:**
- Produces (consumed by Tasks 2, 3, 7):
  - `LOW_COVERAGE_PCT` (const number, 85)
  - `ADVISORY_LINE` (const string, exact text from Global Constraints)
  - `deriveCompleteness(result)` → `{coverage_pct, total, addressed, partial, not_addressed, by_domain_gaps:[{domain,count}], missing_musts:[{rid,domain}], low}`
  - `deriveRedFlags(results)` → `{flagged:[{vendor, flags:[{type,text,detail}]}], clear:[vendorName]}`
  - `deriveAdvisoryRead(results)` → `{winner, shortlist:[result], disqualified:[result], allDisqualified}`

- [ ] **Step 1: Add the helpers**

In `frontend/index.html`, immediately after the line `const recoClass = r => "badge b-"+(r||"").replace(/[^A-Za-z]/g,"");` insert:

```javascript
// ---- demo-feedback derivations (pure; safe offline) ----------------------
const LOW_COVERAGE_PCT = 85;
const ADVISORY_LINE = "The agent's advisory view — one input to your decision, not the decision. Built to be challenged.";

function deriveCompleteness(r){
  const scores=(r.requirement_scores||[]).filter(s=>s.met!=="N/A");
  const total=scores.length;
  const notAddr=scores.filter(s=>s.met==="No" && !((s.evidence||"").trim()));
  const partial=scores.filter(s=>s.met==="Partial").length;
  const addressed=total-notAddr.length;
  const coverage_pct=total?Math.round(addressed/total*100):0;
  const byDom={};
  notAddr.forEach(s=>{const d=(s.domain||"").split(":")[0].trim(); byDom[d]=(byDom[d]||0)+1;});
  const by_domain_gaps=Object.keys(byDom).map(d=>({domain:d,count:byDom[d]})).sort((a,b)=>b.count-a.count);
  const missing_musts=notAddr.filter(s=>s.priority==="Must").map(s=>({rid:s.rid,domain:(s.domain||"").split(":")[0].trim()}));
  return {coverage_pct,total,addressed,partial,not_addressed:notAddr.length,by_domain_gaps,missing_musts,low:coverage_pct<LOW_COVERAGE_PCT};
}

function deriveRedFlags(results){
  const flagged=[], clear=[];
  results.forEach(r=>{
    const c=deriveCompleteness(r);
    const dq=!!(r.gating&&r.gating.disqualified);
    const flags=[];
    if(dq) flags.push({type:"disqualified",
      text:`DISQUALIFIED — ${r.gating.unmet_must_count} unmet Must requirement(s)`,
      detail:(r.gating.unmet_musts||[]).slice(0,3).map(m=>m.rid+(m.capability?` (${m.capability})`:"")).join(", ")});
    if(c.low) flags.push({type:"coverage",
      text:`Addressed ${c.coverage_pct}% of requirements`,
      detail:c.by_domain_gaps.slice(0,3).map(g=>g.domain).join(", ")});
    if(c.missing_musts.length && !dq) flags.push({type:"missing_must",
      text:`${c.missing_musts.length} Must requirement(s) not addressed`,
      detail:c.missing_musts.slice(0,3).map(m=>m.rid).join(", ")});
    if(flags.length) flagged.push({vendor:r.vendor,flags}); else clear.push(r.vendor);
  });
  return {flagged,clear};
}

function deriveAdvisoryRead(results){
  const passing=results.filter(r=>!(r.gating&&r.gating.disqualified)).sort((a,b)=>b.weighted_total-a.weighted_total);
  const disqualified=results.filter(r=>r.gating&&r.gating.disqualified).sort((a,b)=>b.weighted_total-a.weighted_total);
  return {winner:passing[0]||null, shortlist:passing.slice(0,3), disqualified, allDisqualified:passing.length===0};
}
```

- [ ] **Step 2: Write the Node verification script**

Create `scratchpad/test_derivations.mjs` (adjust the scratchpad path to your session dir). It extracts the three functions from the Babel block and runs them over the real seed data:

```javascript
import fs from "node:fs";
const html=fs.readFileSync("frontend/index.html","utf8");
const block=html.match(/<script type="text\/babel">([\s\S]*?)<\/script>/)[1];
// pull the three pure functions + the two consts (they use no JSX)
const start=block.indexOf("const LOW_COVERAGE_PCT");
const end=block.indexOf("function deriveAdvisoryRead");
const tail=block.slice(end); const endFn=tail.indexOf("\n}\n")+end+3;
const src=block.slice(start,endFn);
eval(src);
const seed=JSON.parse(fs.readFileSync("backend/data/sample_results.json","utf8"));
const rf=deriveRedFlags(seed); const ar=deriveAdvisoryRead(seed);
console.log("advisory winner:", ar.winner&&ar.winner.vendor, "| allDQ:", ar.allDisqualified);
console.log("shortlist:", ar.shortlist.map(r=>r.vendor), "| disq:", ar.disqualified.map(r=>r.vendor));
seed.forEach(r=>{const c=deriveCompleteness(r); console.log(`${r.vendor}: coverage ${c.coverage_pct}% addressed=${c.addressed} notAddr=${c.not_addressed} low=${c.low}`);});
console.log("red-flagged vendors:", rf.flagged.map(f=>f.vendor), "| clear:", rf.clear);
// assertions
if(!ar.disqualified.length) throw new Error("expected some disqualified vendors in seed");
if(ar.winner && ar.winner.gating.disqualified) throw new Error("winner must pass the gate");
console.log("OK");
```

- [ ] **Step 3: Run the verification script**

Run: `cd "$(git rev-parse --show-toplevel)/FSM_Scoring_Agent" && node scratchpad/test_derivations.mjs`
Expected: prints coverage per vendor, a winner that passes the gate, the disqualified list (Salesforce, ServiceMax in the seed), and `OK`.

- [ ] **Step 4: Transpile the Babel block to confirm JSX/JS validity**

Run:
```bash
python3 - <<'PY'
import re
s=open("frontend/index.html",encoding="utf-8").read()
open("scratchpad/app.jsx","w").write(re.search(r'<script type="text/babel">(.*?)</script>',s,re.S).group(1))
PY
npx --yes esbuild scratchpad/app.jsx --jsx=transform --outfile=scratchpad/app.out.js
```
Expected: esbuild exits 0, no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html
git commit -m "feat(dashboard): completeness/red-flag/advisory derivation helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HDRWRyRVpwi6EE1txTjDDs"
```

---

## Task 2: Advisory read + red-flags banner on the Dashboard

**Files:**
- Modify: `frontend/index.html` — add two components before `function Dashboard` (line 541); render them at the top of Dashboard's returned JSX (after `<div>` on line 546); add CSS in the `<style>` block.

**Interfaces:**
- Consumes: `deriveAdvisoryRead`, `deriveRedFlags`, `ADVISORY_LINE`, `fmt`, `recoClass` (Task 1 + existing).
- Produces: `<AdvisoryRead results/>`, `<RedFlags results/>` (used in Dashboard).

- [ ] **Step 1: Add the components**

Immediately before `function Dashboard({results, onOpen}){` insert:

```javascript
function AdvisoryRead({results}){
  const {winner,shortlist,disqualified,allDisqualified}=deriveAdvisoryRead(results);
  return (
    <div className="card advisory">
      <div className="advisory-line">{ADVISORY_LINE}</div>
      {allDisqualified
        ? <div className="advisory-head">Every vendor is disqualified on the Must gate — no standing recommendation.</div>
        : <div className="advisory-head">Agent's pick: <b>{winner.vendor}</b> — {fmt(winner.weighted_total)}/100, {winner.vote.recommendation}.</div>}
      <div className="advisory-cols">
        {shortlist.length>0 && <div><span className="lbl">Shortlist</span>{shortlist.map(r=><span key={r.vendor} className="chip">{r.vendor} · {fmt(r.weighted_total)}</span>)}</div>}
        {disqualified.length>0 && <div><span className="lbl">Disqualified</span>{disqualified.map(r=><span key={r.vendor} className="chip dq">{r.vendor} · {r.gating.unmet_must_count} unmet</span>)}</div>}
      </div>
    </div>
  );
}

function RedFlags({results}){
  const {flagged,clear}=deriveRedFlags(results);
  if(!flagged.length) return null;
  return (
    <div className="card redflags">
      <div className="section-title" style={{marginTop:0}}>Red flags — deal-breakers &amp; gaps</div>
      {flagged.map(f=>(
        <div key={f.vendor} className="redflag-row">
          <b>{f.vendor}</b>
          <ul>{f.flags.map((fl,i)=>(<li key={i} className={"rf-"+fl.type}>{fl.text}{fl.detail?<span className="muted small"> — {fl.detail}</span>:null}</li>))}</ul>
        </div>
      ))}
      {clear.length>0 && <div className="small muted" style={{marginTop:6}}>{clear.length} vendor(s) clear the gate with no major gaps: {clear.join(", ")}.</div>}
    </div>
  );
}
```

- [ ] **Step 2: Render them at the top of Dashboard**

In `Dashboard`, the return currently starts:
```javascript
  return (
    <div>
      <div className="section-title">Head-to-head ranking — the agent’s vote</div>
```
Insert the two components right after `<div>`:
```javascript
  return (
    <div>
      <AdvisoryRead results={results}/>
      <RedFlags results={results}/>
      <div className="section-title">Head-to-head ranking — the agent’s vote</div>
```

- [ ] **Step 3: Add CSS**

In the `<style>` block (near the other `.card`/chat rules), add:
```css
.advisory{border-left:4px solid var(--ssa-blue);margin-bottom:12px}
.advisory-line{font-size:11px;color:var(--muted);margin-bottom:6px}
.advisory-head{font-size:15px;margin-bottom:8px}
.advisory-cols{display:flex;gap:24px;flex-wrap:wrap}
.advisory-cols .lbl{display:block;font-size:11px;color:var(--muted);text-transform:uppercase;margin-bottom:4px}
.chip{display:inline-block;background:#eef2f7;border-radius:12px;padding:2px 10px;margin:2px 4px 2px 0;font-size:12px}
.chip.dq{background:#fae6e4;color:var(--bad)}
.redflags{border-left:4px solid var(--bad);margin-bottom:12px}
.redflag-row{margin:6px 0}
.redflag-row ul{margin:2px 0 0 16px;padding:0}
.rf-disqualified{color:var(--bad);font-weight:600}
.rf-coverage,.rf-missing_must{color:var(--warn)}
```

- [ ] **Step 4: Transpile to verify**

Run the esbuild command from Task 1 Step 4. Expected: exit 0, no errors.

- [ ] **Step 5: Manual check**

Start the server (`cd backend && python3 app.py`), open `http://127.0.0.1:8000`. Dashboard should show the advisory read (a winner that passes the gate) and a red-flags banner listing the disqualified vendors above the ranking table.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat(dashboard): advisory read + red-flags banner up top

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HDRWRyRVpwi6EE1txTjDDs"
```

---

## Task 3: Response-completeness panel in Vendor detail

**Files:**
- Modify: `frontend/index.html` — `VendorDetail` (line 594); add a panel immediately after the hero grid `<div className="grid detail-hero">…</div>` closes; add CSS.

**Interfaces:**
- Consumes: `deriveCompleteness` (Task 1).

- [ ] **Step 1: Add the completeness panel**

In `VendorDetail`, find the end of the hero grid block (the `</div>` that closes `<div className="grid detail-hero">`, just before the requirements-table controls). Immediately after that closing `</div>`, insert:

```javascript
      {(()=>{const c=deriveCompleteness(r);return (
        <div className="card" style={{marginTop:12}}>
          <h3>Response completeness</h3>
          <div className="cb-track"><div className={c.low?"cb-fill cb-low":"cb-fill cb-ok"} style={{width:c.coverage_pct+"%"}}/></div>
          <p className="small" style={{marginTop:6}}>Addressed <b>{c.coverage_pct}%</b> of {c.total} scored requirements — {c.addressed} addressed ({c.partial} partial), {c.not_addressed} not addressed.</p>
          {c.by_domain_gaps.length>0 && <p className="small">Biggest unaddressed areas: {c.by_domain_gaps.slice(0,4).map(g=>`${g.domain} (${g.count})`).join(", ")}.</p>}
          {c.missing_musts.length>0 && <p className="small met-No">{c.missing_musts.length} Must requirement(s) not addressed: {c.missing_musts.slice(0,8).map(m=>m.rid).join(", ")}.</p>}
        </div>
      );})()}
```

- [ ] **Step 2: Add CSS**

```css
.cb-track{height:10px;background:#eef2f7;border-radius:6px;overflow:hidden}
.cb-fill{height:100%}
.cb-ok{background:var(--good)}
.cb-low{background:var(--warn)}
```

- [ ] **Step 3: Transpile to verify**

Run the esbuild command from Task 1 Step 4. Expected: exit 0.

- [ ] **Step 4: Manual check**

Open a vendor's detail (Dashboard → Detail →). The completeness panel shows a coverage bar and the unaddressed areas. A disqualified vendor should show a lower bar and listed Must gaps.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html
git commit -m "feat(detail): response-completeness panel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HDRWRyRVpwi6EE1txTjDDs"
```

---

## Task 4: Advisory framing / simplicity copy pass

**Files:**
- Modify: `frontend/index.html` — Dashboard ranking section title + the app header subtitle area.

**Interfaces:** none new. Reuses `ADVISORY_LINE`.

- [ ] **Step 1: Reword the ranking section title**

In `Dashboard`, change:
```javascript
      <div className="section-title">Head-to-head ranking — the agent’s vote</div>
```
to:
```javascript
      <div className="section-title">Head-to-head ranking — the agent’s advisory vote</div>
```

- [ ] **Step 2: Confirm the advisory line is present on the Dashboard**

The `AdvisoryRead` component (Task 2) already renders `ADVISORY_LINE` at the top of the Dashboard. No further change needed here — this step is a check: load the Dashboard and confirm the framing line reads *"The agent's advisory view — one input to your decision, not the decision. Built to be challenged."*

- [ ] **Step 3: Transpile + commit**

Run the esbuild command from Task 1 Step 4 (expect exit 0), then:
```bash
git add frontend/index.html
git commit -m "feat(ui): advisory framing on dashboard

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HDRWRyRVpwi6EE1txTjDDs"
```

---

## Task 5: Backend committee parser + aggregator

**Files:**
- Create: `backend/agent/committee.py`
- Create: `backend/data/committee_template.csv`
- Test: `scratchpad/test_committee.py` (throwaway — not committed)

**Interfaces:**
- Produces (consumed by Task 6):
  - `parse_committee_file(data: bytes, filename: str) -> dict` → `{"rows":[{evaluator,vendor,score,verdict?,categories?}], "warnings":[str]}` or `{"error":str, "rows":[], "warnings":[]}`
  - `aggregate_committee(rows: list[dict]) -> dict` → `{"vendors":[{vendor,mean_score,min,max,stddev,n_evaluators,verdict_counts,modal_verdict,category_means}], "n_evaluators_total":int, "warnings":[]}`

- [ ] **Step 1: Write `backend/agent/committee.py`**

```python
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
```

- [ ] **Step 2: Write `backend/data/committee_template.csv`**

```
evaluator,vendor,score,verdict
Nick,IFS,82,Recommend
Nick,BuildOps,74,Shortlist
Nick,ServiceTitan,72,Shortlist
Nick,Salesforce,68,Reject
Nick,ServiceMax,61,Reject
Jeff,IFS,79,Recommend
Jeff,BuildOps,76,Shortlist
Jeff,ServiceTitan,71,Shortlist
Jeff,Salesforce,70,Reject
Jeff,ServiceMax,58,Reject
Fred,IFS,80,Recommend
Fred,BuildOps,73,Shortlist
Fred,ServiceTitan,74,Shortlist
Fred,Salesforce,66,Reject
Fred,ServiceMax,60,Reject
```

- [ ] **Step 3: Write the Python verification script**

Create `scratchpad/test_committee.py`:
```python
import sys
sys.path.insert(0, "backend")
from agent.committee import parse_committee_file, aggregate_committee

good = open("backend/data/committee_template.csv", "rb").read()
p = parse_committee_file(good, "committee_template.csv")
assert not p.get("error"), p
assert len(p["rows"]) == 15, len(p["rows"])
agg = aggregate_committee(p["rows"])
ifs = next(v for v in agg["vendors"] if v["vendor"] == "IFS")
assert ifs["n_evaluators"] == 3 and 79 <= ifs["mean_score"] <= 82, ifs
assert agg["vendors"][0]["vendor"] == "IFS", "IFS should rank first by mean"
assert ifs["modal_verdict"] == "Recommend", ifs

bad = b"evaluator,vendor,score\nNick,IFS,not-a-number\nJeff,,70\nFred,IFS,150\nSam,IFS,80\n"
pb = parse_committee_file(bad, "x.csv")
assert len(pb["rows"]) == 1 and len(pb["warnings"]) == 3, pb

missing = b"name,vendor,score\nNick,IFS,80\n"
pm = parse_committee_file(missing, "x.csv")
assert pm.get("error"), pm

xl = parse_committee_file(b"\x00\x01", "x.xlsx")  # garbage xlsx bytes
assert xl.get("error") and xl["rows"] == [], xl   # must soft-fail, never crash
print("OK", agg["n_evaluators_total"], [v["vendor"] for v in agg["vendors"]])
```

- [ ] **Step 4: Run the verification script**

Run: `cd "$(git rev-parse --show-toplevel)/FSM_Scoring_Agent" && python3 scratchpad/test_committee.py`
Expected: prints `OK 15 ['IFS', ...]` with no assertion error.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/committee.py backend/data/committee_template.csv
git commit -m "feat(committee): CSV/Excel scorecard parser + aggregator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HDRWRyRVpwi6EE1txTjDDs"
```

---

## Task 6: Committee API endpoints + in-memory store

**Files:**
- Modify: `backend/app.py` — add import, `_COMMITTEE` store, four routes.

**Interfaces:**
- Consumes: `parse_committee_file`, `aggregate_committee` (Task 5).
- Produces (consumed by Task 7): `GET/POST/DELETE /api/committee`, `GET /api/committee/template`.

- [ ] **Step 1: Add the import**

Near the other agent imports in `app.py` (e.g., next to `from agent.sample import sample_proposal_text`), add:
```python
from agent.committee import parse_committee_file, aggregate_committee
```

- [ ] **Step 2: Add the in-memory store**

Near `_RESULTS = {}` (the existing results cache), add:
```python
_COMMITTEE = {"aggregate": None}  # latest uploaded committee aggregate; in-memory only
```

- [ ] **Step 3: Add the routes**

First confirm the data-directory constant name used by `_seed_results` (it opens `SAMPLE_RESULTS`). Use the same directory. If the constant is `SAMPLE_RESULTS`, derive the dir with `os.path.dirname(SAMPLE_RESULTS)`. Add near the other `/api` read routes:

```python
@app.route("/api/committee", methods=["GET"])
def committee_get():
    return jsonify(_COMMITTEE["aggregate"] or {"vendors": [], "n_evaluators_total": 0, "warnings": []})

@app.route("/api/committee", methods=["POST"])
def committee_post():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file uploaded."}), 400
    parsed = parse_committee_file(f.read(), f.filename or "")
    if parsed.get("error"):
        return jsonify({"error": parsed["error"]}), 400
    agg = aggregate_committee(parsed["rows"])
    agg["warnings"] = parsed.get("warnings", [])
    _COMMITTEE["aggregate"] = agg
    return jsonify(agg)

@app.route("/api/committee", methods=["DELETE"])
def committee_delete():
    _COMMITTEE["aggregate"] = None
    return jsonify({"ok": True})

@app.route("/api/committee/template")
def committee_template():
    data_dir = os.path.dirname(SAMPLE_RESULTS)
    return send_from_directory(data_dir, "committee_template.csv",
                               as_attachment=True, download_name="committee_template.csv")
```

- [ ] **Step 4: Verify the endpoints**

Start the server (`cd backend && python3 app.py`). In another shell from the repo's `FSM_Scoring_Agent` dir:
```bash
curl -s http://127.0.0.1:8000/api/committee
curl -s -F "file=@backend/data/committee_template.csv" http://127.0.0.1:8000/api/committee | python3 -m json.tool | head -20
curl -s http://127.0.0.1:8000/api/committee/template | head -2
```
Expected: first returns the empty shape; the POST returns an aggregate with `vendors` (IFS first, mean ~80, n=3); the template returns the CSV header line.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py
git commit -m "feat(committee): /api/committee endpoints + in-memory store + template

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HDRWRyRVpwi6EE1txTjDDs"
```

---

## Task 7: Committee scores tab (frontend)

**Files:**
- Modify: `frontend/index.html` — add `Committee` component (before `function App`), add the tab to the tab array (line 1569) and the render switch (after line 1583), add CSS.

**Interfaces:**
- Consumes: `jget`, `STATIC`, `fmt`, `recoClass`, `ADVISORY_LINE` (existing + Task 1); `/api/committee` (Task 6); `results` from `App`.

- [ ] **Step 1: Add the Committee component**

Immediately before `function App(){` insert:

```javascript
function Committee({results}){
  const [agg,setAgg]=useState(null);
  const [busy,setBusy]=useState(false);
  const [msg,setMsg]=useState(null);
  useEffect(()=>{ if(STATIC) return; jget("/api/committee").then(d=>{ if(d&&d.vendors&&d.vendors.length) setAgg(d); }).catch(()=>{}); },[]);
  async function upload(file){
    if(STATIC){ setMsg({ok:false,text:"Run the Flask server to ingest committee scores — the offline build can't upload."}); return; }
    setBusy(true); setMsg(null);
    const fd=new FormData(); fd.append("file",file);
    try{
      const res=await fetch("/api/committee",{method:"POST",body:fd});
      const d=await res.json();
      if(d.error){ setMsg({ok:false,text:d.error}); }
      else{ setAgg(d); setMsg({ok:true,text:`Loaded ${d.n_evaluators_total} evaluator-scores across ${d.vendors.length} vendor(s).`+(d.warnings&&d.warnings.length?` ${d.warnings.length} row warning(s).`:"")}); }
    }catch(e){ setMsg({ok:false,text:"Upload failed — check the file format (CSV recommended)."}); }
    setBusy(false);
  }
  const byVendor={}; results.forEach(r=>byVendor[(r.vendor||"").toLowerCase().trim()]=r);
  const side = agg ? [...agg.vendors].sort((a,b)=>b.mean_score-a.mean_score)
                       .map(cv=>({cv, agent:byVendor[(cv.vendor||"").toLowerCase().trim()]||null})) : [];
  return (
    <div className="committee">
      <div className="advisory-line">{ADVISORY_LINE}</div>
      <div className="card" style={{margin:"10px 0"}}>
        <h3>Upload committee scores</h3>
        <p className="small muted">CSV with columns <code>evaluator, vendor, score</code> (optional <code>verdict</code> and category columns). <a href="/api/committee/template">Download template</a></p>
        <input type="file" accept=".csv,.xlsx" disabled={busy} onChange={e=>{ if(e.target.files[0]) upload(e.target.files[0]); }}/>
        {msg && <div className={"small "+(msg.ok?"met-Yes":"met-No")} style={{marginTop:6}}>{msg.text}</div>}
        {agg&&agg.warnings&&agg.warnings.length>0 && <ul className="small muted" style={{marginTop:6}}>{agg.warnings.slice(0,5).map((w,i)=><li key={i}>{w}</li>)}</ul>}
      </div>
      {agg && <div>
        <div className="section-title">Committee consensus</div>
        <div className="card" style={{padding:0}}><div className="table-scroll"><table className="dashboard-table">
          <thead><tr><th>Vendor</th><th>Mean score (n)</th><th>Spread</th><th>Verdict distribution</th></tr></thead>
          <tbody>{[...agg.vendors].sort((a,b)=>b.mean_score-a.mean_score).map(v=>(
            <tr key={v.vendor}>
              <td><b>{v.vendor}</b></td>
              <td>{fmt(v.mean_score)} <span className="muted small">(n={v.n_evaluators})</span></td>
              <td className="muted small">{fmt(v.min)}–{fmt(v.max)}</td>
              <td className="small">{Object.keys(v.verdict_counts||{}).map(k=>`${k}: ${v.verdict_counts[k]}`).join(" · ")||"—"}</td>
            </tr>
          ))}</tbody>
        </table></div></div>

        <div className="section-title">Committee vs the agent — side by side</div>
        <p className="small muted">Two independent views. The shortlist is the committee's; the agent sits beside it as one more voice. No blended score.</p>
        <div className="card" style={{padding:0}}><div className="table-scroll"><table className="dashboard-table">
          <thead><tr><th>Vendor</th><th>Committee mean</th><th>Committee verdict</th><th>Agent score</th><th>Agent vote</th><th>Agent gate</th></tr></thead>
          <tbody>{side.map(({cv,agent})=>(
            <tr key={cv.vendor}>
              <td><b>{cv.vendor}</b></td>
              <td>{fmt(cv.mean_score)} <span className="muted small">(n={cv.n_evaluators})</span></td>
              <td className="small">{cv.modal_verdict||"—"}</td>
              <td>{agent?fmt(agent.weighted_total):"—"}</td>
              <td>{agent?<span className={recoClass(agent.vote.recommendation)}>{agent.vote.recommendation}</span>:<span className="muted">—</span>}</td>
              <td>{agent?(agent.gating.disqualified?<span className="met-No">{agent.gating.unmet_must_count} unmet</span>:<span className="met-Yes">pass</span>):<span className="muted">—</span>}</td>
            </tr>
          ))}</tbody>
        </table></div></div>
      </div>}
    </div>
  );
}
```

- [ ] **Step 2: Add the tab to the tab array**

Change the tab array (line 1569) from:
```javascript
        {[["dashboard","Dashboard"],["detail","Vendor detail"],["compare","Compare"],["batch","Batch evaluate"],["method","Methodology & rubric"],["chat","Ask the agent"]].map(([k,l])=>(
```
to (add `["committee","Committee scores"]` after `chat`):
```javascript
        {[["dashboard","Dashboard"],["detail","Vendor detail"],["compare","Compare"],["batch","Batch evaluate"],["method","Methodology & rubric"],["chat","Ask the agent"],["committee","Committee scores"]].map(([k,l])=>(
```

- [ ] **Step 3: Add the render branch**

After the line `{tab==="chat" && <Chat model={model}/>}` (line 1601), add:
```javascript
        {tab==="committee" && <Committee results={results}/>}
```

- [ ] **Step 4: Add CSS**

```css
.committee input[type=file]{font-size:13px}
```

- [ ] **Step 5: Transpile to verify**

Run the esbuild command from Task 1 Step 4. Expected: exit 0.

- [ ] **Step 6: Manual check**

With the server running, open the app → Committee scores tab. Click "Download template", then upload that CSV. Confirm the consensus table (IFS first, mean ~80) and the side-by-side table (committee columns + agent columns, no blended number) render.

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html
git commit -m "feat(committee): Committee scores tab with consensus + side-by-side

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HDRWRyRVpwi6EE1txTjDDs"
```

---

## Task 8: Rebuild standalone + full verification

**Files:**
- Modify: `FSM_Evaluation_Agent_Standalone.html` (regenerated).

- [ ] **Step 1: Rebuild the standalone**

Run: `cd backend && python3 build_static.py`
Expected: prints "Wrote …FSM_Evaluation_Agent_Standalone.html".

- [ ] **Step 2: Confirm new pieces are bundled**

Run from the `FSM_Scoring_Agent` dir:
```bash
grep -c "deriveAdvisoryRead\|function Committee\|Response completeness" FSM_Evaluation_Agent_Standalone.html
```
Expected: a non-zero count (the new code is present).

- [ ] **Step 3: Offline smoke check**

Open `FSM_Evaluation_Agent_Standalone.html` in a browser (or confirm via the user). Dashboard advisory read, red flags, and vendor-detail completeness must render from the seeded data. The Committee tab must load and, on upload attempt, show the offline message ("Run the Flask server…") rather than erroring.

- [ ] **Step 4: Server-mode end-to-end check**

With `python3 app.py` running: Dashboard (advisory + red flags) → Detail (completeness) → Committee (upload template → consensus + side-by-side). Confirm no console errors.

- [ ] **Step 5: Commit**

```bash
git add FSM_Evaluation_Agent_Standalone.html
git commit -m "build: rebuild standalone with demo-feedback updates

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HDRWRyRVpwi6EE1txTjDDs"
```

---

## Spec coverage check

- Feature 1 (completeness + red flags): Tasks 1 (derivation), 2 (red-flags banner), 3 (completeness panel). ✓
- Feature 2 (advisory winner/shortlist): Tasks 1 (derivation), 2 (AdvisoryRead). ✓
- Feature 3 (committee ingestion + side-by-side): Tasks 5 (parser/aggregator), 6 (endpoints), 7 (tab). ✓ Own top-level tab. ✓ No blended score. ✓
- Feature 4 (advisory framing/simplicity): Task 4, plus `ADVISORY_LINE` on Dashboard (Task 2) and Committee (Task 7). ✓
- Offline standalone preserved + rebuilt: Task 8. ✓
- Out of scope (anonymity, doc parsing, in-app entry): not implemented, per spec. ✓
