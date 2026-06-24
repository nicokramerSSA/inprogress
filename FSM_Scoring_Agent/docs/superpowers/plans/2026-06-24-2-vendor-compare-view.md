# 2-Vendor Compare View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Compare" tab that puts two vendor evaluations side by side, flags every divergence, and leads with a deterministic computed verdict — all client-side, no LLM call.

**Architecture:** One new React component (`Compare`) plus a few pure helper functions and presentational sub-components, all added to the single-file `frontend/index.html`. It is fed the existing `results` array (already delivered via `/api/results` / `window.__BOOT__`), so there are no backend, scoring, schema, or persistence changes. The offline standalone is regenerated from the same source via `backend/build_static.py`.

**Tech Stack:** React 18 via CDN + in-browser Babel (no build step, no npm). Plain ES helper functions. No new dependencies.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from `docs/superpowers/specs/2026-06-24-2-vendor-compare-view-design.md`.

- **Deterministic and client-side only.** No LLM call. No new backend endpoint. No changes to `backend/agent/*`, `backend/app.py`, schemas, or persistence. The only files that change are `frontend/index.html` and the generated `FSM_Evaluation_Agent_Standalone.html`.
- **"Meets a Must"** = `priority === "Must"` AND `met === "Yes"`. `Partial` does NOT count as met (consistent with gating).
- **Quality delta** uses the `quality` field (1–5). Rows where either side is `quality === 0` or `met === "N/A"` are EXCLUDED from the higher/tie/lower quality counts, but still appear in the diff table with "—".
- **Capability leadership** counts the 8 capabilities where one side's `score_1_5` exceeds the other's; equal within epsilon `0.05` is a tie.
- **Headline "lead"** = strictly greater value; within `1` point on a lens is treated as a tie for the takeaway wording.
- **Delta sign convention:** `delta = A − B` everywhere (positive ⇒ Vendor A ahead).
- **Divergence cues are colorblind-safe:** every delta shows an arrow + sign (`▲ +14`, `▼ -3`, `– 0`); color is a secondary cue only.
- **Read-only.** The view never mutates `results` or any evaluation object.
- **Join key is `rid`.** If a `rid` exists for one vendor and not the other, render the missing side as "—" and exclude it from quality-delta counts.
- **Must work in BOTH the live server and the offline standalone** (`STATIC` mode). Reuse the existing `results` prop path — do not add new fetches.
- **Reuse existing helpers and CSS:** `fmt`, `recoClass`, `BarRow`, and the existing CSS tokens / `.card` / `.grid` / `.rowbar` / `.table-scroll` / `.section-title` classes. Match the surrounding code's style (terse JSX, `className`, inline styles where the file already does).
- **No test suite / no toolchain** (project convention). Verification is manual: pure logic gets an executable Node assertion harness that extracts and evals the ACTUAL shipped functions; rendering is verified by a Babel-compile-and-mount check (`--dump-dom | grep`), a screenshot, and a documented manual tab-open.
- **After code changes, run `graphify update .`** to keep the knowledge graph current (final task).

### Shared facts the implementer needs (from the current `frontend/index.html`)

- The whole app is one `<script type="text/babel">` block (≈ lines 154–826). All components are top-level `function` declarations inside it.
- Hooks are destructured at the top: `const {useState, useEffect, useMemo, useRef} = React;` (line 154).
- Globals already defined: `STATIC` (bool), `BOOT`, `fmt = n => (n==null) ? "—" : Math.round(n*10)/10` (line 164), `recoClass = r => "badge b-"+(r||"").replace(/[^A-Za-z]/g,"")` (line 185), `BarRow({label,value,max=5,suffix="/5"})` (line 188).
- The nav tab array is at line 784:
  ```jsx
  {[["dashboard","Dashboard"],["detail","Vendor detail"],["method","Methodology & rubric"],["chat","Ask the agent"]].map(([k,l])=>(
  ```
- The App tab-render branches are lines 798–814 (`{tab==="dashboard" && ...}` … `{tab==="chat" && <Chat .../>}`).
- A vendor evaluation object `r` has: `vendor`, `product`, `is_demo`, `weighted_total`, `capability_weighted_total`, `gating{disqualified,unmet_must_count,unmet_musts[{rid,capability,reason}],architectural_gate_flags,summary}`, `categories[]{id,name,weight,raw_1_5,weighted_points,confidence,rationale}`, `capabilities[]{code,name,weight,score_1_5,n_requirements,n_unmet_must}`, `segment_fit[]{segment_id,segment_name,fit_1_5,rationale}`, `agentic_future{score_1_5,openness_1_5,ai_capability_1_5,data_control_risk,rationale}`, `vote{recommendation,confidence,narrative,dissent,top_risks,evidence_to_close}`, `requirement_scores[]{rid,domain,capability,priority,met,quality,vendor_code,confidence,rationale,evidence_gap}`.
- Build the standalone: `cd backend && python3 build_static.py` → writes `../FSM_Evaluation_Agent_Standalone.html`.
- The scratchpad for throwaway verification scripts is `/tmp/claude-1000/-home-chagood-workspace-projects-RFP-Agent-FSM-Scoring-Agent/b8bc3f98-10e6-4167-bcaa-b007f9b186a5/scratchpad`.

---

## File Structure

- **`frontend/index.html`** — all source changes:
  - Task 1: a marker-delimited block of pure helper functions (`cmpCapabilityLead`, `cmpReqDivergence`, `cmpTakeaway`) inserted after `BarRow`.
  - Task 2: the `Compare` component (pickers + empty state + takeaway), a nav entry, a render branch.
  - Task 3: rollup sections inside `Compare` + presentational `DeltaChip`/`CmpRow` + a small CSS block.
  - Task 4: requirement divergence summary + diff table inside `Compare`.
- **`FSM_Evaluation_Agent_Standalone.html`** — regenerated in Task 5.
- **No other files change.**

---

## Task 1: Deterministic compare helpers (pure, Node-testable)

**Files:**
- Modify: `frontend/index.html` (insert after `BarRow`, i.e. after the line `}` that closes `BarRow` at ≈ line 197, before the `// ---- dashboard` comment at ≈ line 276)
- Verify (throwaway, not committed): `<scratchpad>/verify_compare_helpers.js`

**Interfaces:**
- Consumes: nothing (pure functions over two vendor-evaluation objects).
- Produces (used by Tasks 2–4):
  - `cmpCapabilityLead(a, b, eps=0.05) -> {aLeads:int, bLeads:int, ties:int}`
  - `cmpReqDivergence(a, b) -> {mustAOnly:int, mustBOnly:int, aHigher:int, tie:int, bHigher:int, topDeltas:[{rid,domain,priority,a,b,delta}], total:int}`
  - `cmpTakeaway(a, b) -> string`
  - (`a` and `b` are full vendor-evaluation objects; `delta = A − B`.)

- [ ] **Step 1: Insert the marker-delimited helper block**

Insert exactly this block after the close of `BarRow` (≈ line 197) and before `// ---- dashboard (head-to-head)`:

```jsx
// ---- compare: deterministic helpers ------------------------------------
// Pure, self-contained (no outer-scope refs) so a Node harness can extract
// the block between the markers and exercise the ACTUAL shipped logic.
// === COMPARE_HELPERS_START ===
const _cr1 = n => (n===undefined||n===null) ? 0 : Math.round(n*10)/10;
const _plural = n => n===1 ? "" : "s";

// Count, over the 8 RFP capabilities, where each side leads (epsilon tie).
function cmpCapabilityLead(a, b, eps){
  eps = (eps===undefined) ? 0.05 : eps;
  const bMap = {}; (b.capabilities||[]).forEach(c => { bMap[c.code] = c; });
  let aLeads=0, bLeads=0, ties=0;
  (a.capabilities||[]).forEach(ca => {
    const cb = bMap[ca.code]; if(!cb) return;
    const d = ca.score_1_5 - cb.score_1_5;
    if(Math.abs(d) <= eps) ties++;
    else if(d > 0) aLeads++; else bLeads++;
  });
  return {aLeads, bLeads, ties};
}

// Requirement-level divergence. Must-met = priority Must AND met === "Yes".
// Quality counts exclude rows where either side is N/A or quality 0.
function cmpReqDivergence(a, b){
  const bMap = {}; (b.requirement_scores||[]).forEach(x => { bMap[x.rid] = x; });
  let mustAOnly=0, mustBOnly=0, aHigher=0, tie=0, bHigher=0;
  const deltas = [];
  (a.requirement_scores||[]).forEach(xa => {
    const xb = bMap[xa.rid]; if(!xb) return;
    if(xa.priority === "Must"){
      const aMet = xa.met === "Yes", bMet = xb.met === "Yes";
      if(aMet && !bMet) mustAOnly++;
      else if(bMet && !aMet) mustBOnly++;
    }
    const qOk = xa.quality>0 && xb.quality>0 && xa.met!=="N/A" && xb.met!=="N/A";
    if(qOk){
      const d = xa.quality - xb.quality;
      if(d>0) aHigher++; else if(d<0) bHigher++; else tie++;
      if(d!==0) deltas.push({rid:xa.rid, domain:xa.domain, priority:xa.priority, a:xa.quality, b:xb.quality, delta:d});
    }
  });
  deltas.sort((p,q) => Math.abs(q.delta) - Math.abs(p.delta));
  return {mustAOnly, mustBOnly, aHigher, tie, bHigher, topDeltas:deltas.slice(0,5), total:deltas.length};
}

// One-sentence deterministic verdict. Gating divergence leads; else headline
// lenses (with a 1-point tie band); else capability count breaks a tie.
function cmpTakeaway(a, b){
  const aDQ = !!(a.gating && a.gating.disqualified);
  const bDQ = !!(b.gating && b.gating.disqualified);
  const aMust = a.gating ? a.gating.unmet_must_count : 0;
  const bMust = b.gating ? b.gating.unmet_must_count : 0;
  if(aDQ && !bDQ) return `${b.vendor} is the standing option — ${a.vendor} is disqualified (${aMust} unmet Must${_plural(aMust)}).`;
  if(bDQ && !aDQ) return `${a.vendor} is the standing option — ${b.vendor} is disqualified (${bMust} unmet Must${_plural(bMust)}).`;
  if(aDQ && bDQ) return `Both ${a.vendor} and ${b.vendor} are disqualified (${aMust} vs ${bMust} unmet Musts) — neither passes the Must gate.`;
  const cap = cmpCapabilityLead(a, b);
  const ssaD = a.weighted_total - b.weighted_total;
  const c30D = a.capability_weighted_total - b.capability_weighted_total;
  const lens = `SSA ${_cr1(a.weighted_total)} vs ${_cr1(b.weighted_total)}, §30 ${_cr1(a.capability_weighted_total)} vs ${_cr1(b.capability_weighted_total)}`;
  const near = Math.abs(ssaD) <= 1 && Math.abs(c30D) <= 1;
  const split = (ssaD > 0) !== (c30D > 0);
  if(near || split){
    const capLeader = cap.aLeads > cap.bLeads ? a.vendor : cap.bLeads > cap.aLeads ? b.vendor : null;
    const capPhrase = capLeader ? `${capLeader} leads on ${Math.max(cap.aLeads, cap.bLeads)} of 8 capabilities` : `capabilities are split evenly`;
    return `Evenly matched on headline scores (${lens}); ${capPhrase}.`;
  }
  const leader = ssaD > 0 ? a : b;
  const ahead = ssaD > 0 ? cap.aLeads : cap.bLeads;
  return `${leader.vendor} leads — higher on both lenses (${lens}) and ahead on ${ahead} of 8 capabilities.`;
}
// === COMPARE_HELPERS_END ===
```

- [ ] **Step 2: Write the executable verification harness**

Create `<scratchpad>/verify_compare_helpers.js` (replace `<scratchpad>` with the absolute scratchpad path from Global Constraints, and `<repo>` with the repo root):

```js
const fs = require("fs");
const path = "<repo>/FSM_Scoring_Agent/frontend/index.html";
const src = fs.readFileSync(path, "utf8");
const m = src.match(/\/\/ === COMPARE_HELPERS_START ===([\s\S]*?)\/\/ === COMPARE_HELPERS_END ===/);
if(!m){ console.error("MARKERS NOT FOUND"); process.exit(1); }
const api = new Function(m[1] + "\nreturn {cmpCapabilityLead, cmpReqDivergence, cmpTakeaway};")();

let pass=0, fail=0;
function check(name, cond){ console.log((cond?"PASS":"FAIL")+" "+name); cond?pass++:fail++; }
function eq(name, got, want){ const ok = JSON.stringify(got)===JSON.stringify(want);
  console.log((ok?"PASS":"FAIL")+" "+name + (ok?"":` got=${JSON.stringify(got)} want=${JSON.stringify(want)}`)); ok?pass++:fail++; }

// --- fixtures -------------------------------------------------------------
function cap(code, s){ return {code, name:code, weight:0.125, score_1_5:s, n_requirements:10, n_unmet_must:0}; }
const caps8 = ss => ss.map((s,i)=>cap("C"+i, s));
function req(rid, priority, met, quality){ return {rid, domain:"D", capability:"W2C", priority, met, quality}; }

const A = {
  vendor:"Aerion", weighted_total:78, capability_weighted_total:75,
  gating:{disqualified:false, unmet_must_count:0},
  capabilities:caps8([5,5,5,4,4,4,3,3]),
  requirement_scores:[ req("R1","Must","Yes",5), req("R2","Must","No",2), req("R3","Should","Yes",4), req("R4","Could","N/A",0) ],
};
const B = {
  vendor:"Brightfield", weighted_total:64, capability_weighted_total:61,
  gating:{disqualified:true, unmet_must_count:1},
  capabilities:caps8([3,3,3,3,3,5,5,5]),
  requirement_scores:[ req("R1","Must","No",2), req("R2","Must","Yes",5), req("R3","Should","Yes",2), req("R4","Could","N/A",0) ],
};

// --- cmpCapabilityLead ----------------------------------------------------
eq("capLead A vs B", api.cmpCapabilityLead(A,B), {aLeads:5, bLeads:3, ties:0});
eq("capLead identical -> all ties", api.cmpCapabilityLead({capabilities:caps8([3,3,3,3,3,3,3,3])},{capabilities:caps8([3,3,3,3,3,3,3,3])}), {aLeads:0,bLeads:0,ties:8});
eq("capLead epsilon tie", api.cmpCapabilityLead({capabilities:[cap("C0",3.00)]},{capabilities:[cap("C0",3.04)]}), {aLeads:0,bLeads:0,ties:1});

// --- cmpReqDivergence -----------------------------------------------------
// R1: A Must-met, B not -> mustAOnly. R2: B Must-met, A not -> mustBOnly.
// quality (both >0, not N/A): R1 5 vs 2 (A higher), R2 2 vs 5 (B higher), R3 4 vs 2 (A higher). R4 excluded (N/A).
const div = api.cmpReqDivergence(A,B);
eq("div musts", {mA:div.mustAOnly, mB:div.mustBOnly}, {mA:1, mB:1});
eq("div quality counts", {aH:div.aHigher, tie:div.tie, bH:div.bHigher}, {aH:2, tie:0, bH:1});
eq("div total deltas", div.total, 3);
check("div topDeltas sorted by |delta|", div.topDeltas[0].rid==="R1" || div.topDeltas[0].rid==="R2");
check("div topDeltas length <=5", div.topDeltas.length<=5);

// --- cmpTakeaway ----------------------------------------------------------
check("takeaway: B disqualified -> A standing", api.cmpTakeaway(A,B).indexOf("Aerion is the standing option")===0);
check("takeaway: A disqualified -> B standing",
  api.cmpTakeaway({...A,gating:{disqualified:true,unmet_must_count:2}}, {...B,gating:{disqualified:false,unmet_must_count:0}})
    .indexOf("Brightfield is the standing option")===0);
check("takeaway: both DQ", api.cmpTakeaway({...A,gating:{disqualified:true,unmet_must_count:3}},{...B,gating:{disqualified:true,unmet_must_count:1}}).startsWith("Both"));
const clear = api.cmpTakeaway({...A,gating:{disqualified:false,unmet_must_count:0}},{...B,gating:{disqualified:false,unmet_must_count:0}});
check("takeaway: clear leader names Aerion leads", clear.indexOf("Aerion leads")===0);
const tieT = api.cmpTakeaway(
  {...A,weighted_total:70,capability_weighted_total:70,gating:{disqualified:false,unmet_must_count:0}},
  {...B,weighted_total:70.5,capability_weighted_total:70.5,gating:{disqualified:false,unmet_must_count:0}});
check("takeaway: near-tie wording", tieT.startsWith("Evenly matched"));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
```

- [ ] **Step 3: Run the harness and confirm all checks pass**

Run: `node "<scratchpad>/verify_compare_helpers.js"`
Expected: every line prints `PASS`, final line `13 passed, 0 failed`, exit code 0.

If any line prints `FAIL`, fix the helper block in `frontend/index.html` (not the harness, unless a fixture is genuinely wrong) and re-run until clean.

- [ ] **Step 4: Confirm the helpers don't break the page (compile + mount check)**

The harness proves the logic but evals only the marker block. Confirm the edited file still compiles as JSX under the real Babel pipeline and React still mounts:

Run:
```bash
cd "<repo>/FSM_Scoring_Agent/backend" && python3 app.py & SRV=$!; sleep 3; \
google-chrome --headless --disable-gpu --no-sandbox --dump-dom http://127.0.0.1:8000 2>/dev/null | grep -c "Head-to-head"; \
kill $SRV
```
Expected: prints `1` or more (the Dashboard content rendered ⇒ the whole Babel script compiled and React mounted). If it prints `0`, the script has a syntax error introduced by the helper block — fix it. (If `google-chrome` is unavailable, use `chromium` or `chromium-browser`; if none, open `http://127.0.0.1:8000` in a browser and confirm the Dashboard renders.)

- [ ] **Step 5: Commit**

```bash
cd "<repo>" && git add FSM_Scoring_Agent/frontend/index.html && \
git commit -m "feat(compare): deterministic compare helpers (takeaway, capability lead, requirement divergence)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```
(The scratchpad harness is throwaway and outside the repo — not committed.)

---

## Task 2: Compare component shell — pickers, empty state, takeaway, nav wiring

**Files:**
- Modify: `frontend/index.html` — insert the `Compare` component after `VendorDetail` (after its closing `}` at ≈ line 504, before `// ---- methodology`); add a nav entry (line 784) and a render branch (after the dashboard branch at ≈ line 798).

**Interfaces:**
- Consumes: `cmpTakeaway` (Task 1); `results` array prop; globals `fmt`.
- Produces: `Compare({results})` React component; the picked objects `A`/`B` and selection state pattern that Tasks 3–4 extend in the SAME component.

- [ ] **Step 1: Add the `Compare` component (shell only)**

Insert after `VendorDetail`'s closing brace (≈ line 504):

```jsx
// ---- compare (two vendors side by side) ----------------------------------
function Compare({results}){
  const names = results.map(r => r.vendor);
  const [aName, setAName] = useState(null);
  const [bName, setBName] = useState(null);

  // Default to the top two by SSA weighted_total once results arrive.
  useEffect(() => {
    if(results.length < 2) return;
    const ranked = [...results].sort((x,y) => y.weighted_total - x.weighted_total);
    setAName(prev => (prev && names.includes(prev)) ? prev : ranked[0].vendor);
    setBName(prev => (prev && names.includes(prev) && prev!==ranked[0].vendor) ? prev : ranked[1].vendor);
  }, [results]);

  if(results.length < 2){
    return <p className="muted">Need at least two evaluated vendors to compare. Run another evaluation above.</p>;
  }

  // Same-vendor guard: if A and B collide, shift B to the next distinct vendor.
  let bSafe = bName;
  if(bSafe === aName) bSafe = names.find(n => n !== aName) || bName;
  const A = results.find(r => r.vendor === aName);
  const B = results.find(r => r.vendor === bSafe);
  if(!A || !B) return <p className="muted">Pick two vendors to compare.</p>;

  // Guard a partial/legacy result missing a sub-object, so one bad field can't
  // throw and blank the whole React tree (spec §9 — prevent-throw is the binding
  // requirement; a component-level notice is the chosen interpretation).
  const REQUIRED = ["gating","categories","capabilities","segment_fit","agentic_future","vote","requirement_scores"];
  const missing = REQUIRED.find(k => !A[k] || !B[k]);
  if(missing) return <p className="muted">One of these evaluations is missing data ({missing}); re-run it before comparing.</p>;

  return (
    <div>
      <div className="cmp-pickers">
        <label className="small muted">Vendor A
          <select className="pill" style={{padding:"5px 8px",marginLeft:6}} value={aName} onChange={e=>setAName(e.target.value)}>
            {names.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <span className="muted">vs</span>
        <label className="small muted">Vendor B
          <select className="pill" style={{padding:"5px 8px",marginLeft:6}} value={bSafe} onChange={e=>setBName(e.target.value)}>
            {names.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        {bName === aName && <span className="small" style={{color:"var(--warn)"}}>Pick two different vendors — showing the next one.</span>}
      </div>

      <div className="cmp-takeaway">{cmpTakeaway(A, B)}</div>

      {/* rollup + requirement sections added in later tasks */}
    </div>
  );
}
```

- [ ] **Step 2: Add the nav entry**

At line 784, change the tab array to include Compare (after `detail`):

```jsx
{[["dashboard","Dashboard"],["detail","Vendor detail"],["compare","Compare"],["method","Methodology & rubric"],["chat","Ask the agent"]].map(([k,l])=>(
```

- [ ] **Step 3: Add the render branch**

After the dashboard render branch (≈ line 798, the `{tab==="dashboard" && ...}` line), add:

```jsx
        {tab==="compare" && <Compare results={results}/>}
```

- [ ] **Step 4: Add the picker/takeaway CSS**

In the `<style>` block, after the `.requirement-controls` rule (≈ line 114), add:

```css
  .cmp-pickers{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:16px}
  .cmp-pickers label{display:flex;align-items:center}
  .cmp-takeaway{background:#eef3fb;border:1px solid #c9d9ed;border-radius:8px;padding:14px 16px;font-size:14px;line-height:1.5;margin-bottom:8px}
```

- [ ] **Step 5: Verify compile + mount, and that the Compare tab button is present**

Run:
```bash
cd "<repo>/FSM_Scoring_Agent/backend" && python3 app.py & SRV=$!; sleep 3; \
google-chrome --headless --disable-gpu --no-sandbox --dump-dom http://127.0.0.1:8000 2>/dev/null | grep -c ">Compare<"; \
google-chrome --headless --disable-gpu --no-sandbox --window-size=1440,2000 --screenshot="<scratchpad>/compare_shell.png" http://127.0.0.1:8000 2>/dev/null; \
kill $SRV
```
Expected: the grep prints `1` (the Compare nav button rendered ⇒ script compiled and mounted). The screenshot writes to scratchpad.

- [ ] **Step 6: Manual tab check (documented)**

Open `http://127.0.0.1:8000` in a browser, click **Compare**. Confirm: two pickers default to the top two vendors (highest SSA totals), the takeaway sentence reads correctly, switching either picker updates the sentence, and selecting the same vendor in both shows the warning + auto-shifts B. Note the result in the task report.

- [ ] **Step 7: Commit**

```bash
cd "<repo>" && git add FSM_Scoring_Agent/frontend/index.html && \
git commit -m "feat(compare): Compare tab shell — pickers, empty state, takeaway, nav wiring

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Task 3: Rollup comparison sections (headline, capabilities, categories, gating, segment, agentic, vote)

**Files:**
- Modify: `frontend/index.html` — add `DeltaChip` + `CmpRow` helpers (just before the `Compare` function), fill in the rollup sections where Task 2 left the `{/* rollup ... */}` comment, and add CSS for the compare rows.

**Interfaces:**
- Consumes: `cmpCapabilityLead` (used indirectly via takeaway only; not needed here), `fmt`, `recoClass`, the `A`/`B` objects from Task 2.
- Produces: `DeltaChip({delta, digits})` and `CmpRow({label, a, b, max, sub})` presentational components (reused by Task 4's summary if helpful).

- [ ] **Step 1: Add `DeltaChip` and `CmpRow` before `Compare`**

Insert immediately before `function Compare({results}){`:

```jsx
// delta = A - B; arrow + sign carry meaning (colorblind-safe), color secondary.
function DeltaChip({delta, digits=1}){
  const p = Math.pow(10, digits);
  const d = Math.round((delta||0) * p) / p;
  if(d > 0) return <span className="delta-up" title="Vendor A higher">{"▲"} +{d}</span>;
  if(d < 0) return <span className="delta-down" title="Vendor B higher">{"▼"} {d}</span>;
  return <span className="delta-zero" title="tie">{"–"} 0</span>;
}

// One paired metric row: label | A value | delta | B value, with mini bars.
function CmpRow({label, a, b, max=5, sub}){
  const pa = Math.max(0, Math.min(100, (a/max)*100));
  const pb = Math.max(0, Math.min(100, (b/max)*100));
  return (
    <div className="cmp-metric">
      <div className="cmp-metric-label">{label}{sub && <div className="small muted">{sub}</div>}</div>
      <div className="cmp-side">
        <div className="bar"><span style={{width:pa+"%"}}/></div>
        <span className="cmp-num">{fmt(a)}</span>
      </div>
      <div className="cmp-delta"><DeltaChip delta={a-b}/></div>
      <div className="cmp-side">
        <div className="bar"><span style={{width:pb+"%"}}/></div>
        <span className="cmp-num">{fmt(b)}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Replace the rollup placeholder comment with the rollup sections**

Replace the line `{/* rollup + requirement sections added in later tasks */}` in `Compare` with:

```jsx
      {/* Column headers */}
      <div className="cmp-colhead">
        <div></div>
        <div className="cmp-vendorhead"><b>{A.vendor}</b><div className="small muted">{A.product}{A.is_demo && <span className="tag" style={{marginLeft:6}}>demo</span>}</div></div>
        <div></div>
        <div className="cmp-vendorhead"><b>{B.vendor}</b><div className="small muted">{B.product}{B.is_demo && <span className="tag" style={{marginLeft:6}}>demo</span>}</div></div>
      </div>

      {/* Headline lenses */}
      <div className="section-title">Headline scores</div>
      <div className="card">
        <CmpRow label="SSA weighted total" a={A.weighted_total} b={B.weighted_total} max={100}/>
        <CmpRow label={"RFP §30 capability lens"} a={A.capability_weighted_total} b={B.capability_weighted_total} max={100}/>
      </div>

      {/* Gating */}
      <div className="section-title">Gate (MoSCoW + architectural)</div>
      <div className="grid detail-grid">
        {[A,B].map((r,i)=>(
          <div className="card" key={i}>
            <b>{r.vendor}: {r.gating.disqualified ? <span className="met-No">DISQUALIFIED</span> : <span className="met-Yes">PASS</span>}</b>
            <p className="small muted" style={{marginTop:4}}>{r.gating.summary}</p>
            {r.gating.unmet_musts.length>0 && <ul className="small" style={{margin:"6px 0 0 16px",padding:0}}>
              {r.gating.unmet_musts.slice(0,6).map(m=>(<li key={m.rid}>{m.rid} ({m.capability}): {m.reason}</li>))}
            </ul>}
            {r.gating.architectural_gate_flags.map((f,j)=>(<div key={j} className="small" style={{color:"var(--warn)",marginTop:6}}>{"⚑"} {f}</div>))}
          </div>
        ))}
      </div>

      {/* §30 capabilities */}
      <div className="section-title">{"RFP capabilities (Section 30)"}</div>
      <div className="card">
        {A.capabilities.map(ca=>{
          const cb = B.capabilities.find(x=>x.code===ca.code) || {score_1_5:0,n_unmet_must:0};
          return <CmpRow key={ca.code} label={`${ca.code} · ${ca.name}`}
                   sub={(ca.n_unmet_must>0||cb.n_unmet_must>0) ? `unmet Must — ${A.vendor}: ${ca.n_unmet_must}, ${B.vendor}: ${cb.n_unmet_must}` : null}
                   a={ca.score_1_5} b={cb.score_1_5}/>;
        })}
      </div>

      {/* SSA categories */}
      <div className="section-title">SSA scorecard categories</div>
      <div className="card">
        {A.categories.map(ca=>{
          const cb = B.categories.find(x=>x.id===ca.id) || {raw_1_5:0};
          return <CmpRow key={ca.id} label={`${ca.name} (${Math.round(ca.weight*100)}%)`} a={ca.raw_1_5} b={cb.raw_1_5}/>;
        })}
      </div>

      {/* Segment fit */}
      <div className="section-title">OpCo-segment fit</div>
      <div className="card">
        {A.segment_fit.map(sa=>{
          const sb = B.segment_fit.find(x=>x.segment_id===sa.segment_id) || {fit_1_5:0};
          return <CmpRow key={sa.segment_id} label={sa.segment_name} a={sa.fit_1_5} b={sb.fit_1_5}/>;
        })}
      </div>

      {/* Agentic future */}
      <div className="section-title">Fit into an agentic future</div>
      <div className="card">
        <CmpRow label="Overall" a={A.agentic_future.score_1_5} b={B.agentic_future.score_1_5}/>
        <CmpRow label="Openness / data access" a={A.agentic_future.openness_1_5} b={B.agentic_future.openness_1_5}/>
        <CmpRow label="AI capability (shipped)" a={A.agentic_future.ai_capability_1_5} b={B.agentic_future.ai_capability_1_5}/>
        <div className="cmp-metric">
          <div className="cmp-metric-label">Data-control risk</div>
          <div className="cmp-side"><span className="cmp-num">{A.agentic_future.data_control_risk}</span></div>
          <div className="cmp-delta"></div>
          <div className="cmp-side"><span className="cmp-num">{B.agentic_future.data_control_risk}</span></div>
        </div>
      </div>

      {/* Vote */}
      <div className="section-title">{"The agent’s vote"}</div>
      <div className="grid detail-grid">
        {[A,B].map((r,i)=>(
          <div className="card" key={i}>
            <b>{r.vendor}</b> <span className={recoClass(r.vote.recommendation)}>{r.vote.recommendation}</span>
            <span className="small muted"> · {r.vote.confidence} confidence</span>
            <details style={{marginTop:8}}>
              <summary className="small" style={{cursor:"pointer",color:"var(--ssa-blue)"}}>Narrative</summary>
              <p className="small" style={{marginTop:6}}>{r.vote.narrative}</p>
              {r.vote.dissent && <p className="small muted" style={{marginTop:6}}><b>Dissent:</b> {r.vote.dissent}</p>}
            </details>
          </div>
        ))}
      </div>
```

- [ ] **Step 3: Add the compare-row CSS**

In `<style>`, right after the `.cmp-takeaway` rule added in Task 2, add:

```css
  .cmp-colhead,.cmp-metric{display:grid;grid-template-columns:minmax(160px,1.4fr) 1fr 64px 1fr;gap:12px;align-items:center}
  .cmp-colhead{margin:6px 0 2px;padding:0 22px}
  .cmp-vendorhead{text-align:left}
  .cmp-metric{font-size:13px;margin:9px 0}
  .cmp-metric-label{color:var(--ink);line-height:1.25}
  .cmp-side{display:flex;align-items:center;gap:10px}
  .cmp-side .bar{flex:1}
  .cmp-num{font-variant-numeric:tabular-nums;color:var(--muted);min-width:34px;text-align:right}
  .cmp-delta{text-align:center;font-size:12px;font-variant-numeric:tabular-nums}
  .delta-up{color:var(--good);font-weight:600}
  .delta-down{color:var(--bad);font-weight:600}
  .delta-zero{color:var(--muted)}
  @media (max-width:1080px){ .cmp-colhead,.cmp-metric{grid-template-columns:minmax(120px,1fr) 1fr 52px 1fr} }
```

- [ ] **Step 4: Verify compile + mount + screenshot**

Run:
```bash
cd "<repo>/FSM_Scoring_Agent/backend" && python3 app.py & SRV=$!; sleep 3; \
google-chrome --headless --disable-gpu --no-sandbox --dump-dom http://127.0.0.1:8000 2>/dev/null | grep -c ">Compare<"; \
google-chrome --headless --disable-gpu --no-sandbox --window-size=1440,2600 --screenshot="<scratchpad>/compare_rollups.png" http://127.0.0.1:8000 2>/dev/null; \
kill $SRV
```
Expected: grep prints `1` (still compiles/mounts). Screenshot written.

- [ ] **Step 5: Manual value cross-check (documented)**

Open the app, Compare tab. Pick the same two vendors you can open in **Vendor detail**. Confirm for at least one pair: the SSA total, §30 lens, each of the 8 capability `score_1_5`, gating status, and vote recommendation shown in Compare match the single-vendor detail tab exactly, and the delta arrows point toward the higher value (▲ green = A ahead, ▼ red = B ahead, – = tie). Record the cross-check in the task report.

- [ ] **Step 6: Commit**

```bash
cd "<repo>" && git add FSM_Scoring_Agent/frontend/index.html && \
git commit -m "feat(compare): rollup sections (headline, gate, capabilities, categories, segment, agentic, vote)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Task 4: Requirement divergence summary + filterable 422-row diff table

**Files:**
- Modify: `frontend/index.html` — add the requirement section at the end of the `Compare` component body (just before its final `</div>` return close), plus local state at the top of `Compare`.

**Interfaces:**
- Consumes: `cmpReqDivergence` (Task 1); the `A`/`B` objects; `DeltaChip` (Task 3).
- Produces: nothing downstream (final task touching `Compare`).

- [ ] **Step 1: Add local state to `Compare`**

At the top of `Compare`, immediately after the `const [bName, setBName] = useState(null);` line, add:

```jsx
  const [showTable, setShowTable] = useState(false);
  const [onlyDiff, setOnlyDiff] = useState(true);
  const [prio, setPrio] = useState("ALL");
```

- [ ] **Step 2: Compute the divergence + merged rows (after `A`/`B` are resolved)**

Immediately after the `if(!A || !B) return ...` guard line in `Compare`, add:

```jsx
  const div = cmpReqDivergence(A, B);
  const bReq = {}; B.requirement_scores.forEach(x => { bReq[x.rid] = x; });
  const mergedRows = A.requirement_scores.map(xa => {
    const xb = bReq[xa.rid] || {};
    const qa = xa.quality || 0, qb = (xb.quality || 0);
    const hasB = bReq[xa.rid] !== undefined;
    return {rid:xa.rid, domain:xa.domain, priority:xa.priority,
            a:qa, b:hasB ? qb : null, met_a:xa.met, met_b:hasB ? xb.met : "—",
            delta: hasB ? (qa - qb) : 0,
            differ: !hasB || qa !== qb || xa.met !== xb.met};
  });
  const visibleRows = mergedRows.filter(r =>
    (prio === "ALL" || r.priority === prio) && (!onlyDiff || r.differ));
```

- [ ] **Step 3: Add the requirement section before the final closing `</div>` of `Compare`'s return**

Insert just before the last `</div>` that closes the `return (...)` of `Compare`:

```jsx
      {/* Requirement-level divergence */}
      <div className="section-title">Requirement divergence (422 requirements)</div>
      <div className="card">
        <div className="kpi" style={{marginBottom:6}}>
          <div className="k">Musts met by {A.vendor} only<b>{div.mustAOnly}</b></div>
          <div className="k">Musts met by {B.vendor} only<b>{div.mustBOnly}</b></div>
          <div className="k">{A.vendor} higher quality<b>{div.aHigher}</b></div>
          <div className="k">Tie<b>{div.tie}</b></div>
          <div className="k">{B.vendor} higher quality<b>{div.bHigher}</b></div>
        </div>
        {div.topDeltas.length>0 && <div className="small" style={{marginTop:8}}>
          <b>Biggest quality gaps</b>
          <ul style={{margin:"6px 0 0 16px",padding:0}}>
            {div.topDeltas.map(d=>(<li key={d.rid}>{d.rid} ({d.priority}): {A.vendor} {d.a} vs {B.vendor} {d.b} <DeltaChip delta={d.delta}/></li>))}
          </ul>
        </div>}
        <div className="requirement-controls" style={{marginTop:12}}>
          <button className="btn ghost small" onClick={()=>setShowTable(s=>!s)}>{showTable ? "Hide" : "Show"} full diff table</button>
          {showTable && <React.Fragment>
            <label className="small muted" style={{display:"flex",alignItems:"center",gap:6}}>
              <input type="checkbox" checked={onlyDiff} onChange={e=>setOnlyDiff(e.target.checked)}/> only where they differ
            </label>
            <select className="pill" style={{padding:"5px 8px"}} value={prio} onChange={e=>setPrio(e.target.value)}>
              <option value="ALL">All priorities</option>
              <option value="Must">Must</option><option value="Should">Should</option>
              <option value="Could">Could</option><option value="Won't">Won't</option>
            </select>
            <span className="muted small" style={{alignSelf:"center"}}>showing {visibleRows.length} of {mergedRows.length}</span>
          </React.Fragment>}
        </div>
        {showTable && <div className="table-scroll requirement-table-wrap">
          <table className="requirement-table">
            <thead><tr>
              <th>RID</th><th>Domain</th><th>Priority</th>
              <th>{A.vendor}</th><th>{B.vendor}</th><th>{"Δ"}</th>
            </tr></thead>
            <tbody>
            {visibleRows.slice(0,422).map(r=>(
              <tr key={r.rid}>
                <td className="code">{r.rid}</td>
                <td className="small">{r.domain}</td>
                <td>{r.priority}</td>
                <td>{r.a || "—"} <span className={"met-"+r.met_a.replace("/","")} style={{fontSize:11}}>{r.met_a}</span></td>
                <td>{r.b===null ? "—" : (r.b || "—")} <span className={"met-"+String(r.met_b).replace("/","")} style={{fontSize:11}}>{r.met_b}</span></td>
                <td>{r.b===null ? "—" : <DeltaChip delta={r.delta}/>}</td>
              </tr>
            ))}
            </tbody>
          </table>
        </div>}
      </div>
```

- [ ] **Step 4: Verify compile + mount + screenshot (table expanded)**

Run:
```bash
cd "<repo>/FSM_Scoring_Agent/backend" && python3 app.py & SRV=$!; sleep 3; \
google-chrome --headless --disable-gpu --no-sandbox --dump-dom http://127.0.0.1:8000 2>/dev/null | grep -c ">Compare<"; \
kill $SRV
```
Expected: prints `1` (compiles/mounts).

- [ ] **Step 5: Manual functional check (documented)**

Open the app → Compare. Confirm: the summary counts render; clicking **Show full diff table** reveals the table; with "only where they differ" ON the row count is < 422 and equals `mergedRows` that actually differ; turning it OFF shows all 422; the priority filter narrows correctly; the Δ column arrows match the A/B quality values. Spot-check that `div.aHigher + div.tie + div.bHigher` equals the number of rows where both vendors have a real (non-N/A) quality. Record results in the task report.

- [ ] **Step 6: Commit**

```bash
cd "<repo>" && git add FSM_Scoring_Agent/frontend/index.html && \
git commit -m "feat(compare): requirement divergence summary + filterable 422-row diff table

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Task 5: Rebuild standalone + offline verification + graph refresh

**Files:**
- Modify (generated): `FSM_Evaluation_Agent_Standalone.html`
- Run: `backend/build_static.py`, `graphify update .`

**Interfaces:**
- Consumes: the finished `frontend/index.html` (Tasks 1–4).
- Produces: a standalone HTML that includes the Compare tab and works offline (`STATIC` mode).

- [ ] **Step 1: Rebuild the standalone**

Run: `cd "<repo>/FSM_Scoring_Agent/backend" && python3 build_static.py`
Expected: prints success and writes `../FSM_Evaluation_Agent_Standalone.html` (file size noticeably > 0; ~900 KB+).

- [ ] **Step 2: Verify the standalone compiles, mounts, and includes Compare offline**

Run:
```bash
google-chrome --headless --disable-gpu --no-sandbox --dump-dom "file://<repo>/FSM_Scoring_Agent/FSM_Evaluation_Agent_Standalone.html" 2>/dev/null | grep -c ">Compare<"
```
Expected: prints `1` (Compare nav button present ⇒ the bundled script compiled and React mounted with `STATIC`/`BOOT` data, no server).

- [ ] **Step 3: Manual offline check (documented)**

Open `FSM_Evaluation_Agent_Standalone.html` directly in a browser (no server). Click **Compare**: confirm pickers default to the top two vendors, the takeaway renders, rollup sections show values, and the diff table expands/filters. This proves the offline-demo invariant holds. Record in the task report.

- [ ] **Step 4: Refresh the knowledge graph**

Run: `cd "<repo>/FSM_Scoring_Agent" && graphify update .`
Expected: completes (AST-only, no API cost).

- [ ] **Step 5: Commit**

```bash
cd "<repo>" && git add FSM_Scoring_Agent/FSM_Evaluation_Agent_Standalone.html && \
git commit -m "build(compare): rebuild standalone with Compare tab

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```
(The regenerated `graphify-out/` is gitignored — nothing to commit there.)

---

## Notes for the executor

- **Babel curly-quote hazard:** the Edit tool has previously injected Unicode curly quotes (`“`/`”`/`’`) in place of ASCII string delimiters (`"`/`'`), which break in-browser Babel and blank the whole page. This is the real hazard — keep every JS/JSX quote ASCII. Display symbols (`§`, `▲`, `▼`, `–`, `—`, `Δ`, `⚑`) are valid literal UTF-8 and Babel compiles them fine; where they appear in JSX they are wrapped in `{"…"}` string expressions so they stay isolated. After each edit, the compile/mount check (`grep -c ">Compare<"`) is the fast guard against an accidental quote mangle.
- **One component, grown across tasks:** Tasks 2–4 all edit the same `Compare` function. The reviewer for each task should see only that task's diff growing the component — that is expected, not duplication.
- **No backend touched:** if any task finds itself editing `backend/`, stop — that violates the Global Constraints and the spec's client-side decision record.
```
