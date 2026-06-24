# Scorecard Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add client-side CSV and SSA-branded print-to-PDF exports to the FSM evaluation app — all-vendor ranking, head-to-head compare, and per-vendor 422-row requirement detail — with zero backend runtime change and full offline-standalone parity.

**Architecture:** One new self-contained helper block in `frontend/index.html` (pure functions inside a `// === EXPORT_HELPERS ===` marked block, mirroring the existing `COMPARE_HELPERS` block so a Node harness can exercise the *actual shipped* logic), plus contextual export buttons on the Dashboard, Compare, and Vendor-detail tabs. PDFs are produced by opening a new window with a self-contained SSA-branded HTML document and calling `window.print()`. One asset line in `build_static.py` embeds the color logo for the standalone build.

**Tech Stack:** React 18 via CDN + in-browser Babel (no build step), plain DOM `Blob`/`window.print` APIs, Python 3.12 `build_static.py`. Tests are Node harnesses that extract the marked block (the project's established pattern); no pytest, no npm.

## Global Constraints

Copied verbatim from the spec and project conventions — every task implicitly includes these:

- **No backend runtime change, no new endpoint, no new Python dependency.** Export is pure client-side presentation of already-loaded results.
- **The offline standalone (`FSM_Evaluation_Agent_Standalone.html`) must keep working** from `file://` — no network fetch at export time; logo comes from `BOOT.logo_dark` in standalone mode.
- **The offline mock engine must stay untouched.** No export path touches `scoring.py`/`vote.py`/`providers.py`.
- **API keys never touched.** Export only renders computed results.
- **Honest by construction.** Empty/`(unlocated)` evidence exports as-is; never fabricate a quote/page.
- **In-browser-Babel hazard:** a non-ASCII (smart) quote used as a JS *string delimiter* blanks the whole page. Use straight ASCII `'`/`"`/`` ` `` for all JS string delimiters. Verify every frontend task with the headless mount check (exactly one `>Dashboard<`).
- **Python is `python3`** (no `python` alias). Run frontend tests with `node`.
- **Brand tokens (use these exact hex):** `--ssa-blue #003399`, `--ssa-teal #336179`, `--ink #0f1b33`, `--muted #5b6677`, `--line #E0E4EA`, `--good #1f7a4d`, `--warn #D97706`, `--bad #b3261e`. Font stack: `'Avenir Next LT Pro','Avenir','Segoe UI',system-ui,sans-serif`.
- **Reuse, do not reinvent:** the Dashboard rank sort is `(a.gating.disqualified-b.gating.disqualified) || (b.weighted_total-a.weighted_total)` (`frontend/index.html:374-375`); the compare verdict is `cmpTakeaway(a,b)` (`frontend/index.html:270`). Exports must reuse these so on-screen and exported orderings/wording match.

**Scratchpad for throwaway harnesses:** `/tmp/claude-1000/-home-chagood-workspace-projects-RFP-Agent-FSM-Scoring-Agent/b8bc3f98-10e6-4167-bcaa-b007f9b186a5/scratchpad`

---

## File Structure

- **Modify `frontend/index.html`:**
  - New `// === EXPORT_HELPERS_START === … === EXPORT_HELPERS_END ===` block immediately after the `COMPARE_HELPERS` block (after `frontend/index.html:293`). Holds all pure export logic: `toCSV`, `csvSlug`, `exportFilename`, `rankingRows`, `compareRows`, `requirementRows`, `brandedDoc`. Pure — no React, no outer-scope refs — so the Node harness can extract and run it.
  - Two small impure helpers near the block: `downloadCSV(filename, rows, headers)` (Blob download) and `printBranded(title, bodyHTML)` (new-window print + popup-block fallback). These touch the DOM and are not unit-tested.
  - Export buttons in `Dashboard` (`:373`), `Compare` (`:646`), `VendorDetail` (`:414`).
- **Modify `backend/build_static.py:26-35`:** also read `ssa_logo_long_b64.txt` into `boot["logo_dark"]`.
- **Rebuild `FSM_Evaluation_Agent_Standalone.html`** via `python3 build_static.py` (Task 5).

The marked-block test harness extracts the JS between the markers, `eval`s it in Node, and asserts on the pure functions — exactly as the compare feature does.

---

### Task 1: Export core — `toCSV`, `csvSlug`, `exportFilename`, and `downloadCSV`

Pure CSV string builder + filename helpers (RFC-4180), plus the one DOM download side-effect. This is the foundation every CSV export uses.

**Files:**
- Modify: `frontend/index.html` (insert the `EXPORT_HELPERS` marked block after line 293; add `downloadCSV` just after the block's end marker)
- Test: `scratchpad/test_export_core.js` (Node harness, extracts the marked block)

**Interfaces:**
- Consumes: nothing (foundation).
- Produces:
  - `toCSV(rows, headers)` → `string`. `rows`: array of plain objects. `headers`: ordered array of `{key, label}`. Output: a header row of `label`s, then one row per object reading `row[key]`. Fields containing `,`, `"`, `\r`, or `\n` are wrapped in double-quotes with embedded `"` doubled to `""`. Values that are `null`/`undefined` render as empty string; booleans render via the caller (pass strings). Line terminator `\r\n`. No trailing newline after the last row is fine; a single trailing `\r\n` is also acceptable — pick **no trailing newline**.
  - `csvSlug(s)` → `string`: lowercase, replace any run of non-`[a-z0-9]` with `-`, trim leading/trailing `-`. (`"Acme Corp!"` → `"acme-corp"`.)
  - `exportFilename(kind, parts, dateStr)` → `string`: joins `["fsm", kind, ...parts.map(csvSlug)]` with `-`, appends `-<dateStr>.csv`. `dateStr` is passed in (caller computes `new Date().toISOString().slice(0,10)`) so the pure function stays deterministic.
  - `downloadCSV(filename, rows, headers)` (impure): `const txt = toCSV(rows, headers); const blob = new Blob([txt], {type:"text/csv;charset=utf-8"}); const url = URL.createObjectURL(blob);` create `<a href=url download=filename>`, append, click, remove, `URL.revokeObjectURL(url)`.

- [ ] **Step 1: Write the failing test**

Create `scratchpad/test_export_core.js`:

```js
const fs = require("fs");
const html = fs.readFileSync(process.argv[2] || "frontend/index.html", "utf8");
const m = html.match(/=== EXPORT_HELPERS_START ===([\s\S]*?)=== EXPORT_HELPERS_END ===/);
if (!m) { console.error("FAIL: EXPORT_HELPERS block not found"); process.exit(1); }
const block = m[1];
const sandbox = {};
new Function("exports", block + "\nexports.toCSV=toCSV;exports.csvSlug=csvSlug;exports.exportFilename=exportFilename;")(sandbox);
const { toCSV, csvSlug, exportFilename } = sandbox;

let ok = true;
function check(name, cond){ console.log((cond?"PASS":"FAIL")+": "+name); if(!cond) ok=false; }

// header row + simple values
check("header+rows", toCSV([{a:"1",b:"x"}],[{key:"a",label:"A"},{key:"b",label:"B"}]) === "A,B\r\n1,x");
// comma quoting
check("comma quoted", toCSV([{a:"a,b"}],[{key:"a",label:"A"}]) === 'A\r\n"a,b"');
// quote doubling
check("quote doubled", toCSV([{a:'he said "hi"'}],[{key:"a",label:"A"}]) === 'A\r\n"he said ""hi"""');
// newline quoting
check("newline quoted", toCSV([{a:"line1\nline2"}],[{key:"a",label:"A"}]) === 'A\r\n"line1\nline2"');
// null/undefined -> empty
check("null empty", toCSV([{a:null,b:undefined}],[{key:"a",label:"A"},{key:"b",label:"B"}]) === "A,B\r\n,");
// slug
check("slug", csvSlug("Acme Corp!") === "acme-corp");
// filename
check("filename", exportFilename("ranking", [], "2026-06-24") === "fsm-ranking-2026-06-24.csv");
check("filename parts", exportFilename("requirements", ["Acme Corp"], "2026-06-24") === "fsm-requirements-acme-corp-2026-06-24.csv");

process.exit(ok?0:1);
```

Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && node scratchpad/test_export_core.js`
Expected: FAIL — "EXPORT_HELPERS block not found".

- [ ] **Step 2: Add the marked block with the three pure functions**

In `frontend/index.html`, immediately after line 293 (`// === COMPARE_HELPERS_END ===`), insert:

```js
// ---- export helpers ------------------------------------------------------
// Pure, self-contained (no outer-scope refs) so a Node harness can extract
// the block between the markers and exercise the ACTUAL shipped logic.
// === EXPORT_HELPERS_START ===
function toCSV(rows, headers){
  const esc = v => {
    if(v===null || v===undefined) return "";
    const s = String(v);
    return /[",\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const lines = [headers.map(h => esc(h.label)).join(",")];
  rows.forEach(row => lines.push(headers.map(h => esc(row[h.key])).join(",")));
  return lines.join("\r\n");
}
function csvSlug(s){
  return String(s||"").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
function exportFilename(kind, parts, dateStr){
  return ["fsm", kind].concat((parts||[]).map(csvSlug)).join("-") + "-" + dateStr + ".csv";
}
// === EXPORT_HELPERS_END ===
```

- [ ] **Step 3: Run test to verify it passes**

Run: `node scratchpad/test_export_core.js`
Expected: all `PASS`, exit 0.

- [ ] **Step 4: Add the impure `downloadCSV` after the end marker**

Immediately after `// === EXPORT_HELPERS_END ===`:

```js
function downloadCSV(filename, rows, headers){
  const blob = new Blob([toCSV(rows, headers)], {type:"text/csv;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 5: Headless mount check (Babel-hazard guard)**

Run: `cd backend && python3 build_static.py && cd .. && (CHROME=$(command -v google-chrome || command -v chromium || command -v chromium-browser); [ -n "$CHROME" ] && "$CHROME" --headless --dump-dom file://$PWD/FSM_Evaluation_Agent_Standalone.html 2>/dev/null | grep -c ">Dashboard<" || echo "no-chrome: verify in browser")`
Expected: `1` (or `no-chromium` note → open the standalone in a browser, confirm the Dashboard renders, no blank page). Do NOT proceed if the page is blank.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat(export): CSV core (toCSV/slug/filename) + downloadCSV helper"
```

---

### Task 2: Row builders — `rankingRows`, `requirementRows`, `compareRows` (+ their headers)

The three pure functions that turn evaluation objects into `{rows, headers}` for CSV. Reuse the Dashboard sort and the existing compare deltas so exports match the screen.

**Files:**
- Modify: `frontend/index.html` (inside the `EXPORT_HELPERS` block, before the end marker)
- Test: `scratchpad/test_export_rows.js` (Node harness; loads `backend/data/sample_results.json`)

**Interfaces:**
- Consumes: `toCSV` shape (`{key,label}` headers); the `VendorEvaluation` JSON shape (fields: `vendor, product, weighted_total, capability_weighted_total, model_used, is_demo, gating.{disqualified,unmet_must_count}, vote.{recommendation,confidence}, agentic_future.{score_1_5,openness_1_5,ai_capability_1_5,data_control_risk}, categories[].{name,raw_1_5}, capabilities[].{code,name,score_1_5}, segment_fit[].{segment_name,fit_1_5}, requirement_scores[].{rid,domain,capability,priority,met,quality,vendor_code,confidence,rationale,evidence{quote,source,locator}}`).
- Produces:
  - `rankingRows(results)` → `{rows, headers}`. Sort a copy with the Dashboard comparator `(a.gating.disqualified-b.gating.disqualified) || (b.weighted_total-a.weighted_total)`. One row per vendor: `{rank, vendor, product, ssa, cap, gate, vote, vote_conf, model, demo}` where `gate = r.gating.disqualified ? "DISQUALIFIED" : "PASS"`, `demo = r.is_demo ? "yes" : "no"`, `ssa = _cr1(r.weighted_total)`, `cap = _cr1(r.capability_weighted_total)` (reuse `_cr1` from the compare block — it is in scope in the browser; in the harness define a local copy, see test). Headers in this order: Rank, Vendor, Product, "SSA score (0-100)", "§30 capability score (0-100)", Gate, Vote, "Vote confidence", Model, "Demo?".
  - `requirementRows(vendorEval)` → `{rows, headers}`. One row per `requirement_scores` entry, **in array order** (already canonical RID order): `{rid, domain, capability, priority, met, quality, code, confidence, rationale, ev_quote, ev_source, ev_locator}` where `code = x.vendor_code`, `ev_quote = (x.evidence&&x.evidence.quote)||""`, `ev_source = (x.evidence&&x.evidence.source)||""`, `ev_locator = (x.evidence&&x.evidence.locator)||"(unlocated)"`. Headers: RID, Domain, Capability, Priority, Met, "Quality (1-5)", "Response code", Confidence, Rationale, "Evidence quote", "Evidence source", "Evidence locator".
  - `compareRows(a, b)` → `{rows, headers}`. Section/metric rows comparing two evals. Headers: Section, Metric, `a.vendor`, `b.vendor`, "Delta (A-B)". Build rows in this order (delta blank `""` for non-numeric rows):
    - Headline: `{section:"Headline", metric:"SSA score (0-100)", aVal:_cr1(a.weighted_total), bVal:_cr1(b.weighted_total), delta:_cr1(a.weighted_total-b.weighted_total)}`; same for "§30 capability score (0-100)" using `capability_weighted_total`.
    - Gate: `{section:"Gate", metric:"MoSCoW gate", aVal:a.gating.disqualified?"DISQUALIFIED":"PASS", bVal:b.gating.disqualified?"DISQUALIFIED":"PASS", delta:""}`.
    - Capabilities: for each `ca` in `a.capabilities`, match `b.capabilities` by `code`; `{section:"§30 capability", metric:ca.name, aVal:_cr1(ca.score_1_5), bVal:_cr1(cb?cb.score_1_5:0), delta:_cr1(ca.score_1_5-(cb?cb.score_1_5:0))}`.
    - SSA categories: for each `ca` in `a.categories`, match `b.categories` by `name`; metric `ca.name`, values `raw_1_5`.
    - Segment fit: for each in `a.segment_fit`, match by `segment_name`; values `fit_1_5`.
    - Agentic future: rows for overall `score_1_5`, `openness_1_5`, `ai_capability_1_5` (numeric, with delta) and one row `metric:"Data-control risk"` with `aVal:a.agentic_future.data_control_risk`, `bVal:b...`, `delta:""`.
    - Vote: `{section:"Vote", metric:"Recommendation", aVal:a.vote.recommendation, bVal:b.vote.recommendation, delta:""}`.
    - Map these objects to header keys: use keys `section, metric, aVal, bVal, delta` and headers `[{key:"section",label:"Section"},{key:"metric",label:"Metric"},{key:"aVal",label:a.vendor},{key:"bVal",label:b.vendor},{key:"delta",label:"Delta (A-B)"}]`.

- [ ] **Step 1: Write the failing test**

Create `scratchpad/test_export_rows.js`:

```js
const fs = require("fs");
const ROOT = "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent";
const html = fs.readFileSync(ROOT + "/frontend/index.html", "utf8");
const m = html.match(/=== EXPORT_HELPERS_START ===([\s\S]*?)=== EXPORT_HELPERS_END ===/)[1];
const sandbox = {};
// _cr1 is defined in the COMPARE block; provide it so the export block can call it.
const prelude = "const _cr1 = n => (n===undefined||n===null)?0:Math.round(n*10)/10;\n";
new Function("exports", prelude + m + "\nexports.rankingRows=rankingRows;exports.requirementRows=requirementRows;exports.compareRows=compareRows;")(sandbox);
const { rankingRows, requirementRows, compareRows } = sandbox;

const results = JSON.parse(fs.readFileSync(ROOT + "/backend/data/sample_results.json", "utf8"));
const arr = Array.isArray(results) ? results : (results.results || Object.values(results));
let ok = true; const check=(n,c)=>{console.log((c?"PASS":"FAIL")+": "+n); if(!c) ok=false;};

const rk = rankingRows(arr);
check("ranking header count", rk.headers.length === 10);
check("ranking one row per vendor", rk.rows.length === arr.length);
check("ranking rank starts at 1", rk.rows[0].rank === 1);
check("ranking gate vocab", rk.rows.every(r => r.gate==="PASS"||r.gate==="DISQUALIFIED"));

const rq = requirementRows(arr[0]);
check("requirements row count == requirement_scores", rq.rows.length === (arr[0].requirement_scores||[]).length);
check("requirements has 13 headers", rq.headers.length === 12);
check("requirements locator fallback", rq.rows.every(r => r.ev_locator !== undefined && r.ev_locator !== null && r.ev_locator !== ""));

const cp = compareRows(arr[0], arr[1]);
check("compare 5 headers", cp.headers.length === 5);
check("compare vendor name headers", cp.headers[2].label === arr[0].vendor && cp.headers[3].label === arr[1].vendor);
check("compare has headline + gate + vote rows", cp.rows.some(r=>r.metric==="SSA score (0-100)") && cp.rows.some(r=>r.section==="Gate") && cp.rows.some(r=>r.section==="Vote"));
check("compare gate delta blank", cp.rows.find(r=>r.section==="Gate").delta === "");

process.exit(ok?0:1);
```

Run: `node scratchpad/test_export_rows.js`
Expected: FAIL — `rankingRows is not a function` (block has no builders yet).

- [ ] **Step 2: Add the three builders inside the marked block**

Insert before `// === EXPORT_HELPERS_END ===` (after `exportFilename`). The builders may call `_cr1` (defined in the compare block, in scope in the browser):

```js
function rankingRows(results){
  const ranked = [...results].sort((a,b) =>
    (a.gating.disqualified - b.gating.disqualified) || (b.weighted_total - a.weighted_total));
  const headers = [
    {key:"rank",label:"Rank"},{key:"vendor",label:"Vendor"},{key:"product",label:"Product"},
    {key:"ssa",label:"SSA score (0-100)"},{key:"cap",label:"§30 capability score (0-100)"},
    {key:"gate",label:"Gate"},{key:"vote",label:"Vote"},{key:"vote_conf",label:"Vote confidence"},
    {key:"model",label:"Model"},{key:"demo",label:"Demo?"}];
  const rows = ranked.map((r,i) => ({
    rank:i+1, vendor:r.vendor, product:r.product,
    ssa:_cr1(r.weighted_total), cap:_cr1(r.capability_weighted_total),
    gate:r.gating.disqualified ? "DISQUALIFIED" : "PASS",
    vote:r.vote.recommendation, vote_conf:r.vote.confidence,
    model:r.model_used, demo:r.is_demo ? "yes" : "no"}));
  return {rows, headers};
}
function requirementRows(v){
  const headers = [
    {key:"rid",label:"RID"},{key:"domain",label:"Domain"},{key:"capability",label:"Capability"},
    {key:"priority",label:"Priority"},{key:"met",label:"Met"},{key:"quality",label:"Quality (1-5)"},
    {key:"code",label:"Response code"},{key:"confidence",label:"Confidence"},{key:"rationale",label:"Rationale"},
    {key:"ev_quote",label:"Evidence quote"},{key:"ev_source",label:"Evidence source"},{key:"ev_locator",label:"Evidence locator"}];
  const rows = (v.requirement_scores||[]).map(x => ({
    rid:x.rid, domain:x.domain, capability:x.capability, priority:x.priority, met:x.met,
    quality:x.quality, code:x.vendor_code, confidence:x.confidence, rationale:x.rationale,
    ev_quote:(x.evidence&&x.evidence.quote)||"", ev_source:(x.evidence&&x.evidence.source)||"",
    ev_locator:(x.evidence&&x.evidence.locator)||"(unlocated)"}));
  return {rows, headers};
}
function compareRows(a, b){
  const rows = [];
  const num = (section, metric, av, bv) => rows.push({section, metric, aVal:_cr1(av), bVal:_cr1(bv), delta:_cr1(av-bv)});
  const txt = (section, metric, av, bv) => rows.push({section, metric, aVal:av, bVal:bv, delta:""});
  const byKey = (list, k) => { const map={}; (list||[]).forEach(x=>map[x[k]]=x); return map; };
  num("Headline","SSA score (0-100)", a.weighted_total, b.weighted_total);
  num("Headline","§30 capability score (0-100)", a.capability_weighted_total, b.capability_weighted_total);
  txt("Gate","MoSCoW gate", a.gating.disqualified?"DISQUALIFIED":"PASS", b.gating.disqualified?"DISQUALIFIED":"PASS");
  const bc = byKey(b.capabilities,"code");
  (a.capabilities||[]).forEach(ca => num("§30 capability", ca.name, ca.score_1_5, (bc[ca.code]||{}).score_1_5||0));
  const bcat = byKey(b.categories,"name");
  (a.categories||[]).forEach(ca => num("SSA category", ca.name, ca.raw_1_5, (bcat[ca.name]||{}).raw_1_5||0));
  const bseg = byKey(b.segment_fit,"segment_name");
  (a.segment_fit||[]).forEach(s => num("OpCo segment", s.segment_name, s.fit_1_5, (bseg[s.segment_name]||{}).fit_1_5||0));
  num("Agentic future","Overall", a.agentic_future.score_1_5, b.agentic_future.score_1_5);
  num("Agentic future","Openness", a.agentic_future.openness_1_5, b.agentic_future.openness_1_5);
  num("Agentic future","AI capability", a.agentic_future.ai_capability_1_5, b.agentic_future.ai_capability_1_5);
  txt("Agentic future","Data-control risk", a.agentic_future.data_control_risk, b.agentic_future.data_control_risk);
  txt("Vote","Recommendation", a.vote.recommendation, b.vote.recommendation);
  const headers = [
    {key:"section",label:"Section"},{key:"metric",label:"Metric"},
    {key:"aVal",label:a.vendor},{key:"bVal",label:b.vendor},{key:"delta",label:"Delta (A-B)"}];
  return {rows, headers};
}
```

- [ ] **Step 3: Run test to verify it passes**

Run: `node scratchpad/test_export_rows.js`
Expected: all `PASS`, exit 0. (If `requirements row count` differs from 422, that is fine — it asserts equality with the sample's own `requirement_scores` length, not a hard-coded 422.)

- [ ] **Step 4: Headless mount check**

Run: `cd backend && python3 build_static.py && cd .. && (CHROME=$(command -v google-chrome || command -v chromium || command -v chromium-browser); [ -n "$CHROME" ] && "$CHROME" --headless --dump-dom file://$PWD/FSM_Evaluation_Agent_Standalone.html 2>/dev/null | grep -c ">Dashboard<" || echo "no-chrome: verify in browser")`
Expected: `1` (or browser-verify note).

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html
git commit -m "feat(export): row builders for ranking, requirements, compare CSV"
```

---

### Task 3: SSA-branded PDF document — `brandedDoc` + `printBranded`

The pure branded-HTML builder and the new-window print side-effect (with popup-block fallback). Used by the ranking and compare PDF buttons.

**Files:**
- Modify: `frontend/index.html` (`brandedDoc` inside the marked block; `printBranded` after the end marker; logo source resolution)
- Test: `scratchpad/test_branded_doc.js` (Node harness)

**Interfaces:**
- Consumes: nothing new (string templating).
- Produces:
  - `brandedDoc(opts)` → full HTML document `string`. `opts = {title, dateStr, logoSrc, contextLine, takeaway, tableHTML}`. `logoSrc` may be `""` (→ wordmark fallback). Must include: `<!doctype html>`, a `<style>` with `@page{size:A4;margin:18mm}`, `thead{display:table-header-group}`, `tr{break-inside:avoid}`, the brand palette as literal hex, the Avenir font stack; a header band containing either `<img src=logoSrc>` (when truthy) or the text `SSA & Company` (wordmark, when falsy) plus `title` and `dateStr`; the `contextLine`; the `takeaway` (if provided); the `tableHTML`; a footer with `SSA & Company` + `Advisory` disclaimer.
  - `tableHTML(rows, headers)` helper (pure, inside block) → an HTML `<table>` string from the same `{rows, headers}` shape the CSV builders produce, HTML-escaping cell values. Gate/vote cells may be wrapped in a chip span; keep it simple — escape and emit `<td>`.
  - `printBranded(title, bodyOpts)` (impure): resolve `logoSrc` (see Step 4), call `brandedDoc`, `const w = window.open("","_blank")`. If `w` is null (popup blocked) → call `printViaHiddenContainer(html)` fallback. Else `w.document.open(); w.document.write(html); w.document.close();` then `w.onload = () => { w.focus(); w.print(); }`.
  - `htmlEsc(s)` (pure, inside block) → escape `& < > "`.

- [ ] **Step 1: Write the failing test**

Create `scratchpad/test_branded_doc.js`:

```js
const fs = require("fs");
const ROOT = "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent";
const html = fs.readFileSync(ROOT + "/frontend/index.html", "utf8");
const m = html.match(/=== EXPORT_HELPERS_START ===([\s\S]*?)=== EXPORT_HELPERS_END ===/)[1];
const sandbox = {};
const prelude = "const _cr1 = n => (n===undefined||n===null)?0:Math.round(n*10)/10;\n";
new Function("exports", prelude + m + "\nexports.brandedDoc=brandedDoc;exports.tableHTML=tableHTML;exports.htmlEsc=htmlEsc;")(sandbox);
const { brandedDoc, tableHTML, htmlEsc } = sandbox;
let ok=true; const check=(n,c)=>{console.log((c?"PASS":"FAIL")+": "+n); if(!c) ok=false;};

check("htmlEsc", htmlEsc('a<b>&"c') === 'a&lt;b&gt;&amp;&quot;c');
const t = tableHTML([{x:"1,2",y:"<b>"}],[{key:"x",label:"X"},{key:"y",label:"Y"}]);
check("table has header", t.includes("<th>X</th>") && t.includes("<th>Y</th>"));
check("table escapes", t.includes("&lt;b&gt;") && !t.includes("<b>"));

const withLogo = brandedDoc({title:"Ranking", dateStr:"2026-06-24", logoSrc:"data:image/png;base64,AAAA", contextLine:"5 vendors", takeaway:"", tableHTML:t});
check("doctype", /^<!doctype html>/i.test(withLogo.trim()));
check("A4 page", withLogo.includes("@page") && withLogo.includes("18mm"));
check("thead repeat", withLogo.includes("table-header-group"));
check("brand blue", withLogo.includes("#003399"));
check("logo img when present", withLogo.includes("data:image/png;base64,AAAA"));
check("footer disclaimer", /Advisory/i.test(withLogo) && withLogo.includes("SSA & Company"));

const noLogo = brandedDoc({title:"X", dateStr:"2026-06-24", logoSrc:"", contextLine:"", takeaway:"T", tableHTML:t});
check("wordmark fallback", noLogo.includes("SSA & Company") && !noLogo.includes("<img"));
check("takeaway rendered", noLogo.includes("T"));

process.exit(ok?0:1);
```

Run: `node scratchpad/test_branded_doc.js`
Expected: FAIL — `brandedDoc is not a function`.

- [ ] **Step 2: Add `htmlEsc`, `tableHTML`, `brandedDoc` inside the marked block**

Insert before the end marker:

```js
function htmlEsc(s){
  return String(s===null||s===undefined?"":s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function tableHTML(rows, headers){
  const head = "<thead><tr>" + headers.map(h => "<th>"+htmlEsc(h.label)+"</th>").join("") + "</tr></thead>";
  const body = "<tbody>" + rows.map(r =>
    "<tr>" + headers.map(h => "<td>"+htmlEsc(r[h.key])+"</td>").join("") + "</tr>").join("") + "</tbody>";
  return "<table>" + head + body + "</table>";
}
function brandedDoc(o){
  const logo = o.logoSrc
    ? '<img class="logo" src="'+o.logoSrc+'" alt="SSA & Company"/>'
    : '<div class="wordmark">SSA &amp; Company</div>';
  const takeaway = o.takeaway ? '<p class="takeaway">'+htmlEsc(o.takeaway)+'</p>' : "";
  const ctx = o.contextLine ? '<p class="ctx">'+htmlEsc(o.contextLine)+'</p>' : "";
  return '<!doctype html><html><head><meta charset="utf-8"><title>'+htmlEsc(o.title)+'</title><style>'
    + '@page{size:A4;margin:18mm}'
    + 'body{font-family:\'Avenir Next LT Pro\',\'Avenir\',\'Segoe UI\',system-ui,sans-serif;color:#0f1b33;margin:0}'
    + '.band{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #003399;padding-bottom:8px;margin-bottom:14px}'
    + '.logo{height:34px}.wordmark{font-weight:700;font-size:18px;color:#003399}'
    + '.band .meta{text-align:right;color:#5b6677;font-size:12px}'
    + 'h1{color:#003399;font-size:18px;margin:0 0 2px}'
    + '.ctx{color:#5b6677;font-size:12px;margin:0 0 10px}'
    + '.takeaway{background:#003399;color:#fff;padding:8px 12px;border-radius:6px;font-size:13px;margin:0 0 12px}'
    + 'table{border-collapse:collapse;width:100%;font-size:11px}'
    + 'thead{display:table-header-group}tr{break-inside:avoid}'
    + 'th{background:#336179;color:#fff;text-align:left;padding:5px 7px}'
    + 'td{border:1px solid #E0E4EA;padding:4px 7px;vertical-align:top}'
    + 'tbody tr:nth-child(even){background:#FAFBFC}'
    + 'footer{position:fixed;bottom:8mm;left:18mm;right:18mm;color:#8BA4C4;font-size:10px;border-top:1px solid #E0E4EA;padding-top:4px}'
    + '</style></head><body>'
    + '<div class="band"><div><div class="meta-logo">'+logo+'</div></div>'
    + '<div class="meta"><div>'+htmlEsc(o.title)+'</div><div>Generated '+htmlEsc(o.dateStr)+'</div></div></div>'
    + '<h1>'+htmlEsc(o.title)+'</h1>'+ctx+takeaway+(o.tableHTML||"")
    + '<footer>SSA &amp; Company · Advisory evaluation — augments the human committee · Generated '+htmlEsc(o.dateStr)+'</footer>'
    + '</body></html>';
}
```

Note: all JS string delimiters are straight ASCII quotes; the only non-ASCII characters are inside string *contents* (`·`, `—`), which is safe. Do not use a smart quote as a delimiter.

- [ ] **Step 3: Run test to verify it passes**

Run: `node scratchpad/test_branded_doc.js`
Expected: all `PASS`, exit 0.

- [ ] **Step 4: Add `printBranded` + logo resolution + popup fallback after the end marker**

After `downloadCSV` (added in Task 1), add:

```js
// Resolve the color logo for the print header. Standalone: BOOT.logo_dark.
// Server: fetch the served color asset. Either may be absent -> wordmark.
async function resolvePrintLogo(){
  if(typeof BOOT !== "undefined" && BOOT && BOOT.logo_dark) return BOOT.logo_dark;
  if(typeof STATIC !== "undefined" && STATIC) return "";
  try { return (await (await fetch("/ssa_logo_long_b64.txt")).text()).trim(); }
  catch(e){ return ""; }
}
function printViaHiddenContainer(docHTML){
  // Fallback when popups are blocked: write an iframe, print it, remove it.
  const iframe = document.createElement("iframe");
  iframe.style.position="fixed"; iframe.style.right="0"; iframe.style.bottom="0";
  iframe.style.width="0"; iframe.style.height="0"; iframe.style.border="0";
  document.body.appendChild(iframe);
  const d = iframe.contentWindow.document;
  d.open(); d.write(docHTML); d.close();
  iframe.contentWindow.focus();
  setTimeout(()=>{ iframe.contentWindow.print(); setTimeout(()=>iframe.remove(), 1000); }, 200);
}
async function printBranded(title, parts){
  const dateStr = new Date().toISOString().slice(0,10);
  const logoSrc = await resolvePrintLogo();
  const docHTML = brandedDoc({title, dateStr, logoSrc,
    contextLine:parts.contextLine||"", takeaway:parts.takeaway||"", tableHTML:parts.tableHTML||""});
  const w = window.open("", "_blank");
  if(!w){ printViaHiddenContainer(docHTML); return; }
  w.document.open(); w.document.write(docHTML); w.document.close();
  w.onload = () => { w.focus(); w.print(); };
}
```

- [ ] **Step 5: Run both prior harnesses + headless mount check (no regressions)**

Run:
```
node scratchpad/test_export_core.js && node scratchpad/test_export_rows.js && node scratchpad/test_branded_doc.js
cd backend && python3 build_static.py && cd .. && (CHROME=$(command -v google-chrome || command -v chromium || command -v chromium-browser); [ -n "$CHROME" ] && "$CHROME" --headless --dump-dom file://$PWD/FSM_Evaluation_Agent_Standalone.html 2>/dev/null | grep -c ">Dashboard<" || echo "no-chrome: verify in browser")
```
Expected: all PASS; mount check `1` (or browser-verify).

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat(export): SSA-branded PDF doc builder + print-to-window with popup fallback"
```

---

### Task 4: Wire export buttons into the Dashboard, Compare, and Vendor-detail tabs

Add the contextual buttons that call the builders. This is where the feature becomes visible.

**Files:**
- Modify: `frontend/index.html` — `Dashboard` (`:373-411`), `Compare` (`:646+`), `VendorDetail` (`:414+`)
- Test: manual click-through + headless mount check (no unit test for JSX wiring)

**Interfaces:**
- Consumes: `downloadCSV`, `printBranded`, `rankingRows`, `compareRows`, `requirementRows`, `tableHTML`, `exportFilename`, `cmpTakeaway` (compare block, `:270`).
- Produces: visible UI only.

- [ ] **Step 1: Dashboard ranking buttons**

In `Dashboard`, after the `<div className="section-title">Head-to-head ranking …` line (`:379`), add a button row. Use the existing `.btn` / `.ghost` classes (already used at `:399`):

```jsx
<div style={{display:"flex",gap:8,margin:"0 0 10px"}}>
  <button className="btn small" onClick={()=>{
    const {rows,headers}=rankingRows(results);
    downloadCSV(exportFilename("ranking",[],new Date().toISOString().slice(0,10)),rows,headers);
  }}>Export ranking (CSV)</button>
  <button className="btn ghost small" onClick={()=>{
    const {rows,headers}=rankingRows(results);
    printBranded("Vendor ranking — FSM RFP evaluation",{
      contextLine:results.length+" vendors evaluated · advisory scoring",
      tableHTML:tableHTML(rows,headers)});
  }}>Export ranking (PDF)</button>
</div>
```

- [ ] **Step 2: Vendor-detail requirements CSV button**

In `VendorDetail` (`:414`), near the top of the returned markup (after the vendor heading), add:

```jsx
<button className="btn small" style={{marginBottom:10}} onClick={()=>{
  const {rows,headers}=requirementRows(data);
  downloadCSV(exportFilename("requirements",[data.vendor],new Date().toISOString().slice(0,10)),rows,headers);
}}>Export requirements (CSV)</button>
```

(`data` is the `VendorEvaluation` prop — confirm the prop name at `:414`; it is `data`.)

- [ ] **Step 3: Compare buttons (disabled until two distinct vendors)**

In `Compare` (`:646`), where `A` and `B` are resolved (`:667-668`), add a button row that is disabled unless both exist and differ. Reuse `cmpTakeaway(A,B)` for the PDF takeaway:

```jsx
<div style={{display:"flex",gap:8,margin:"10px 0"}}>
  <button className="btn small" disabled={!A||!B||A===B} onClick={()=>{
    const {rows,headers}=compareRows(A,B);
    downloadCSV(exportFilename("compare",[A.vendor,"vs",B.vendor],new Date().toISOString().slice(0,10)),rows,headers);
  }}>Export comparison (CSV)</button>
  <button className="btn ghost small" disabled={!A||!B||A===B} onClick={()=>{
    const {rows,headers}=compareRows(A,B);
    printBranded(A.vendor+" vs "+B.vendor+" — FSM RFP comparison",{
      takeaway:cmpTakeaway(A,B), tableHTML:tableHTML(rows,headers)});
  }}>Export comparison (PDF)</button>
</div>
```

Place this after the two vendor pickers and before the rollup table so it reads naturally. Confirm the picker/rollup boundary by reading `:646-720` first.

- [ ] **Step 4: Headless mount check (critical — three JSX edits)**

Run: `cd backend && python3 build_static.py && cd .. && (CHROME=$(command -v google-chrome || command -v chromium || command -v chromium-browser); [ -n "$CHROME" ] && "$CHROME" --headless --dump-dom file://$PWD/FSM_Evaluation_Agent_Standalone.html 2>/dev/null | grep -c ">Dashboard<" || echo "no-chrome: verify in browser")`
Expected: `1`. If `0`, a JSX/Babel error blanked the page — fix before committing.

- [ ] **Step 5: Manual click-through (record evidence)**

Start the server (`cd backend && python3 app.py`), open `http://127.0.0.1:8000`:
- Dashboard: click "Export ranking (CSV)" → a `fsm-ranking-<date>.csv` downloads, opens cleanly in a spreadsheet with the 10 columns. Click "Export ranking (PDF)" → a new window opens with the SSA header/footer and the ranked table; print preview repeats the header row across pages.
- Vendor detail: pick a vendor, "Export requirements (CSV)" → 422-ish rows, evidence columns present, `(unlocated)` where applicable.
- Compare: with one vendor selected the buttons are disabled; pick two distinct vendors → enabled; CSV downloads side-by-side diff; PDF shows the takeaway banner + delta column.
Record what you observed (pass/fail per button) in the commit message or task notes.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat(export): contextual CSV/PDF buttons on Dashboard, Compare, Vendor detail"
```

---

### Task 5: Standalone parity — embed the color logo in `build_static.py`, rebuild, graphify

Make SSA branding work in the offline standalone (where there is no server to fetch the logo), rebuild the single-file bundle, and refresh the graph.

**Files:**
- Modify: `backend/build_static.py:26-35`
- Rebuild: `FSM_Evaluation_Agent_Standalone.html`
- Test: standalone has `logo_dark`; headless mount check; PDF branding visible from `file://`

**Interfaces:**
- Consumes: `resolvePrintLogo` reads `BOOT.logo_dark` (Task 3).
- Produces: `BOOT.logo_dark` in the standalone bundle.

- [ ] **Step 1: Add the color-logo read to `build_static.py`**

After the existing white-logo read (`build_static.py:26-27`):

```python
with open(os.path.join(FRONT, "ssa_logo_long_b64.txt")) as f:
    logo_dark = f.read().strip()
```

And add it to the `boot` dict (near `:35`, alongside `"logo": logo,`):

```python
    "logo_dark": logo_dark,
```

- [ ] **Step 2: Rebuild the standalone**

Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent/backend" && python3 build_static.py`
Expected: prints success; `../FSM_Evaluation_Agent_Standalone.html` updated (~1.5MB+).

- [ ] **Step 3: Verify `logo_dark` is embedded and the page mounts**

Run:
```
cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent"
grep -c "logo_dark" FSM_Evaluation_Agent_Standalone.html
(CHROME=$(command -v google-chrome || command -v chromium || command -v chromium-browser); [ -n "$CHROME" ] && "$CHROME" --headless --dump-dom file://$PWD/FSM_Evaluation_Agent_Standalone.html 2>/dev/null | grep -c ">Dashboard<" || echo "no-chrome: verify in browser")
```
Expected: `logo_dark` count ≥ 1; mount check `1`.

- [ ] **Step 4: Manual standalone PDF check**

Open `FSM_Evaluation_Agent_Standalone.html` by double-click (`file://`). On the Dashboard click "Export ranking (PDF)" → the print window shows the **color** SSA logo in the header (not the wordmark fallback), confirming `BOOT.logo_dark` resolved offline. Click "Export ranking (CSV)" → file downloads from `file://`.

- [ ] **Step 5: Refresh the knowledge graph**

Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && graphify update .`
Expected: completes (AST-only, no API cost).

- [ ] **Step 6: Commit**

```bash
git add backend/build_static.py FSM_Evaluation_Agent_Standalone.html graphify-out
git commit -m "feat(export): embed color logo for standalone PDF branding + rebuild bundle"
```

---

## Self-Review

**1. Spec coverage:**
- CSV all-vendor ranking → Task 2 `rankingRows` + Task 4 Step 1. ✓
- CSV head-to-head compare → Task 2 `compareRows` + Task 4 Step 3. ✓
- CSV per-vendor 422-row → Task 2 `requirementRows` + Task 4 Step 2. ✓
- PDF ranking brief (branded) → Task 3 `brandedDoc` + Task 4 Step 1. ✓
- PDF compare brief (branded, takeaway) → Task 3 + Task 4 Step 3 (`cmpTakeaway`). ✓
- SSA branding (logo/palette/font/footer/page rules) → Task 3 Step 2. ✓
- Client-side print-to-PDF + popup fallback → Task 3 Step 4. ✓
- Standalone logo parity (`BOOT.logo_dark`) → Task 5. ✓
- Honest evidence (`(unlocated)`/empty) → Task 2 `requirementRows`. ✓
- Filenames dated/slugged → Task 1 `exportFilename`/`csvSlug`. ✓
- No backend runtime change / no new dep / mock untouched → only `build_static.py` (build-time) touched. ✓
- Disabled compare buttons until two distinct vendors → Task 4 Step 3. ✓
- `is_demo` surfaced → ranking CSV "Demo?" column (Task 2) + PDF context line (Task 4 Step 1). ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; harnesses are full. ✓

**3. Type consistency:** `{rows, headers}` shape is produced by all three builders and consumed identically by `toCSV`/`downloadCSV`/`tableHTML`. `{key,label}` header objects consistent throughout. `brandedDoc(opts)` keys (`title,dateStr,logoSrc,contextLine,takeaway,tableHTML`) match `printBranded`'s call. `_cr1` is defined in the compare block (in scope in-browser) and stubbed in the Node harness prelude. ✓

Note for the implementer: the requirement-row test asserts equality with the sample's own `requirement_scores.length` (not hard-coded 422), so it passes regardless of the seed's exact count.
