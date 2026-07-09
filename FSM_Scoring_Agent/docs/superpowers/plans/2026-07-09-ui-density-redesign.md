# Vendor-Detail + Methodology Readability Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut perceived density on the Vendor detail and Methodology & rubric pages using progressive disclosure (lead + expand, tabs, gaps-first), touching layout only.

**Architecture:** All changes live in `frontend/index.html` (React-via-CDN, Babel in-browser, no build step). Add three reusable primitives — CSS `:root` type tokens, a native-`<details>` `Disclosure` pattern, and a small React `Tabs` component — then reshape the two page render functions to use them. No backend, schema, or stored-data changes. Everything new is *derived* client-side from fields already present on the result object.

**Tech Stack:** React 18 (CDN UMD), Babel standalone, plain CSS custom properties. No npm, no bundler, no test runner. Verification is manual (browser) plus a Python assertion that curated numbers are byte-identical.

## Global Constraints

- **Layout/formatting only.** Do NOT change the LLM output schema, `vote.narrative`/`vote.dissent` text, gating logic, the two scoring lenses, API routes, auth, or requirement data.
- **Curated results byte-identical.** `backend/data/sample_results.json` stays unchanged; IFS decision score reads `61.4` and OOB `55.1` after the change, all five verdicts unchanged.
- **SSA brand preserved.** Keep navy/teal header (`--ssa-blue:#003399`, `--ssa-teal:#336179`), logo, Avenir font stack, `.card`, `.badge` / `.b-Recommend` system.
- **Typography changes are app-wide.** New type tokens are added to `:root` at values equal to today's effective sizes, so no existing page shifts; any future size change propagates through the token to all eight tabs. Do NOT hard-code a new font-size on a single page.
- **Reversible.** Additive CSS + one React component + native `<details>`. No rewrite of the render tree beyond the two page functions.
- **Standalone parity.** Rebuild `FSM_Evaluation_Agent_Standalone.html` via `python3 build_static.py`; it must open and run offline.
- **Python is `python3`** (no bare `python` alias in this env).
- **Offline mock engine must keep working** (no keys, no network) — it seeds `BOOT.results` from `sample_results.json`.

---

## File Structure

- `frontend/index.html` — the only file modified. Regions:
  - `:root` CSS tokens (lines ~15–23) — add type tokens.
  - CSS rules block (lines ~55–200) — add `.disclosure`, `.subtabs`, `.lead-strip`, `.measure` rules.
  - Helpers region (after line ~241, near `fmt`/`recoClass`) — add pure derive helpers + `Disclosure`/`Tabs` components.
  - `VendorDetail({data})` (lines 753–~975) — vote lead+expand, tabbed deep-dives, gaps-first table.
  - `Methodology({kb})` (lines 1230–1278) — identity card + tightened OpCo cards.
- `FSM_Evaluation_Agent_Standalone.html` — regenerated (not hand-edited) in the final task.

**Running the app for verification (used by every task):**
```bash
cd backend && python3 app.py    # → http://127.0.0.1:8000 , offline mock, no keys needed
```
Open `http://127.0.0.1:8000` in a browser. If a JSX/syntax error is introduced, the whole SPA renders blank — a blank page IS a failed verification.

---

## Task 1: Shared foundations — type tokens, `Disclosure`, `Tabs`, helpers

**Files:**
- Modify: `frontend/index.html` `:root` (lines 15–23), CSS block (after line ~200), helpers (after line ~330, following `BarRow`).

**Interfaces:**
- Produces (consumed by Tasks 2–6):
  - CSS tokens: `--fs-body`, `--fs-lead`, `--fs-label`, `--lh-prose`, `--measure`.
  - CSS classes: `.disclosure`, `.disclosure > summary`, `.subtabs`, `.subtabs button`, `.subtabs button.active`, `.lead-strip`, `.measure`.
  - React component `Disclosure({label, children, tone})` → native `<details>` wrapper.
  - React component `Tabs({tabs})` where `tabs = [{id:string, label:string, render:()=>ReactNode}]`; renders first tab by default.
  - `leadAndRest(text, n=3)` → `{lead:string, rest:string}` (rest is `""` when ≤ n sentences).
  - `voteBottomLine(r)` → `string`.
  - `whatToCloseRows(r)` → `Array<{rid,capability,priority,met,quality,code,note}>`.
  - `archetypePriorities(fitEmphasis, n=3)` → `Array<string>` of capability codes.

- [ ] **Step 1: Add type tokens to `:root`** (values equal current effective sizes, so nothing shifts)

In `frontend/index.html`, inside `:root{...}` (after the `--font:` line, line 22), add:

```css
    /* Prose scale — introduced at current effective values so the whole app is
       unchanged today; a future tweak here propagates to all eight tabs. */
    --fs-body:14px; --fs-lead:15px; --fs-label:12px; --lh-prose:1.6; --measure:68ch;
```

- [ ] **Step 2: Add component CSS**

After the evidence-details rules (after line 198, before the closing of the `<style>` block), add:

```css
  /* Reusable disclosure (native details) */
  .disclosure{margin-top:10px;border-top:1px solid var(--line);padding-top:10px}
  .disclosure>summary{cursor:pointer;color:var(--ssa-blue);font-size:var(--fs-label);font-weight:600;list-style:none}
  .disclosure>summary::-webkit-details-marker{display:none}
  .disclosure>summary::before{content:"▸ ";font-size:10px}
  .disclosure[open]>summary::before{content:"▾ "}
  .disclosure .body{margin-top:8px}
  /* Prose reading width for long narrative */
  .measure{max-width:var(--measure);line-height:var(--lh-prose)}
  /* Lead strip above the vote */
  .lead-strip{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:0 0 12px}
  .lead-strip .bl{font-size:var(--fs-body);color:var(--ink)}
  /* In-card sub-tabs (scoring deep-dives) */
  .subtabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin-bottom:14px}
  .subtabs button{background:none;border:none;padding:9px 14px;font-family:var(--font);font-size:var(--fs-body);color:var(--muted);cursor:pointer;border-bottom:2px solid transparent}
  .subtabs button.active{color:var(--ssa-blue);border-bottom-color:var(--ssa-blue);font-weight:600}
```

- [ ] **Step 3: Add the `Disclosure` and `Tabs` components**

In the JS region, immediately after `function BarRow(...){...}` (ends ~line 326), add:

```jsx
function Disclosure({label, children, tone}){
  return (
    <details className="disclosure">
      <summary style={tone?{color:tone}:null}>{label}</summary>
      <div className="body">{children}</div>
    </details>
  );
}

function Tabs({tabs}){
  const [active,setActive]=useState(tabs[0] ? tabs[0].id : null);
  const cur=tabs.find(t=>t.id===active) || tabs[0];
  return (
    <div>
      <div className="subtabs">
        {tabs.map(t=>(
          <button key={t.id} className={t.id===active?"active":""} onClick={()=>setActive(t.id)}>{t.label}</button>
        ))}
      </div>
      <div>{cur && cur.render()}</div>
    </div>
  );
}
```

- [ ] **Step 4: Add the pure derive helpers**

Immediately after the `Tabs` component, add:

```jsx
// Split prose into a lead (first n sentences) + the remainder. rest==="" when short.
function leadAndRest(text, n=3){
  const s=String(text||"").trim();
  if(!s) return {lead:"", rest:""};
  const parts=s.match(/[^.!?]+[.!?]+(\s|$)/g);
  if(!parts || parts.length<=n) return {lead:s, rest:""};
  return {lead:parts.slice(0,n).join("").trim(), rest:parts.slice(n).join("").trim()};
}

// One-line "bottom line" from fields already on the result — no new stored text.
function voteBottomLine(r){
  const gate=(r.gating && r.gating.summary) ? r.gating.summary : "";
  return `${fmt(r.weighted_total)}/100 decision · ${fmt(r.capability_weighted_total)}/100 capability` + (gate?` · ${gate}`:"");
}

// Rows that matter for "what to close": unmet Must, GAP/ROADMAP code, or quality ≤ 2.
function whatToCloseRows(r){
  return (r.requirement_scores||[]).filter(x=>{
    const code=(x.vendor_code||"").toUpperCase();
    const badCode=code==="GAP"||code==="ROADMAP";
    const unmetMust=x.priority==="Must" && x.met!=="Yes" && x.met!=="N/A";
    const lowQ=typeof x.quality==="number" && x.quality>0 && x.quality<=2;
    return badCode||unmetMust||lowQ;
  }).map(x=>({rid:x.rid,capability:x.capability,priority:x.priority,met:x.met,quality:x.quality,code:x.vendor_code,note:x.evidence_gap||x.rationale}));
}

// Top capability codes an archetype emphasizes (multiplier > 1), highest first.
function archetypePriorities(fitEmphasis, n=3){
  return Object.entries(fitEmphasis||{}).filter(([_,v])=>v>1).sort((a,b)=>b[1]-a[1]).slice(0,n).map(([k])=>k);
}
```

- [ ] **Step 5: Verify the app still loads with no visual change**

```bash
cd backend && python3 app.py
```
Open `http://127.0.0.1:8000`. Expected: app renders exactly as before (tokens equal current sizes; new components/helpers are defined but not yet used). No blank page, no console error. Stop the server (Ctrl-C) when done.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): add type tokens, Disclosure/Tabs components, derive helpers"
```

---

## Task 2: Vendor detail — vote lead + expand, dissent behind disclosure

**Files:**
- Modify: `frontend/index.html` `VendorDetail` vote block (lines 822–851).

**Interfaces:**
- Consumes: `leadAndRest`, `voteBottomLine`, `Disclosure`, `recoClass` (existing), `fmt` (existing), classes `.lead-strip`, `.measure`, `.disclosure`.
- Produces: nothing new for later tasks.

- [ ] **Step 1: Replace the narrative `<p>` and dissent block**

Replace lines 823–832 (the `<div className="card">` opening through the dissent block) so the card starts like this. Leave the `raw_votes`/"How the panel debated" block (lines 834–850) exactly as-is:

```jsx
      <div className="card">
        <div className="lead-strip">
          <span className={recoClass(r.vote.recommendation)} style={{fontSize:14}}>{r.vote.recommendation}</span>
          <span className="muted small">{r.vote.confidence} confidence</span>
          <span className="bl">{voteBottomLine(r)}</span>
        </div>
        {(()=>{const {lead,rest}=leadAndRest(r.vote.narrative,3);return (
          <div className="measure">
            <p style={{marginTop:0}}>{lead}</p>
            {rest && <Disclosure label="Read full reasoning"><p style={{marginTop:0}}>{rest}</p></Disclosure>}
          </div>
        );})()}
        <div className="grid vote-columns" style={{marginTop:12}}>
          <div><b className="small">Top risks</b><ul className="small" style={{margin:"6px 0 0 16px",padding:0}}>
            {r.vote.top_risks.map((t,i)=>(<li key={i}>{t}</li>))}</ul></div>
          <div><b className="small">Evidence to close in Charlotte demos</b><ul className="small" style={{margin:"6px 0 0 16px",padding:0}}>
            {r.vote.evidence_to_close.map((t,i)=>(<li key={i}>{t}</li>))}</ul></div>
        </div>
        {r.vote.dissent && <Disclosure label="Dissent — steel-manned counter-argument">
          <p className="small measure" style={{marginTop:0}}>{r.vote.dissent}</p></Disclosure>}
        {r.vote.note && <div className="small muted" style={{marginTop:8}}>&#8505; {r.vote.note}</div>}
```

(The existing `{r.vote.mode==="dual" ...}` block and the closing `</div>` of the card at line 851 remain unchanged directly below.)

- [ ] **Step 2: Verify in browser**

Run the server (Task 1 Step 5 command). Go to **Vendor detail → IFS**. Expected:
- A one-line strip: `Recommend · High confidence · 61.4/100 decision · 55.1/100 capability · Passes the Must gate. …`.
- Only the first ~3 sentences of the vote show, then a **"▸ Read full reasoning"** toggle that expands the rest.
- **Dissent** is collapsed behind **"▸ Dissent — steel-manned counter-argument"** and expands on click.
- Top risks / evidence-to-close columns unchanged.

- [ ] **Step 3: Verify curated numbers unchanged**

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -c "
import json; d=json.load(open('backend/data/sample_results.json'))
r=[x for x in (d if isinstance(d,list) else d.get('results',d)) if x.get('vendor')=='IFS'][0]
print('weighted_total',r['weighted_total'],'capability',r['capability_weighted_total'],'verdict',r['vote']['recommendation'])
assert round(r['weighted_total'],1)==61.4 and r['vote']['recommendation']=='Recommend'
print('OK curated intact')"
```
Expected: `OK curated intact`.

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): vendor vote as lead + expand, dissent behind disclosure"
```

---

## Task 3: Vendor detail — scoring deep-dives into tabs

**Files:**
- Modify: `frontend/index.html` `VendorDetail` (lines 853–921): the two `detail-grid` rows and the external-research section become one `Tabs`.

**Interfaces:**
- Consumes: `Tabs`, `BarRow` (existing), `fmt` (existing).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Replace lines 853–921 with a single tabbed region**

Replace the three comment-delimited blocks — `{/* Categories + capabilities */}`, `{/* Segment fit + agentic */}`, and `{/* External research */}` (lines 853 through 921) — with:

```jsx
      {/* Scoring deep-dives (tabbed) */}
      <div className="section-title">Scoring detail</div>
      <div className="card">
        <Tabs tabs={[
          {id:"cat", label:"Scorecard categories", render:()=>(
            <div>
              {r.categories.map(c=>(
                <div key={c.id}>
                  <BarRow label={`${c.name} (${Math.round(c.weight*100)}%)`} value={c.raw_1_5}/>
                  <div className="small muted" style={{margin:"-2px 0 8px 0"}}>{c.rationale} · <span className={"conf-"+c.confidence}>{c.confidence} conf</span></div>
                </div>
              ))}
            </div>
          )},
          {id:"cap", label:"RFP capabilities (§30)", render:()=>(
            <div>
              {r.capabilities.map(c=>(
                <div key={c.code}>
                  <BarRow label={`${c.code} · ${c.name} (${Math.round(c.weight*100)}%)`} value={c.score_1_5}/>
                  {c.n_unmet_must>0 && <div className="small met-No" style={{margin:"-2px 0 8px 0"}}>{c.n_unmet_must} unmet Must(s)</div>}
                </div>
              ))}
            </div>
          )},
          {id:"seg", label:"OpCo-segment fit", render:()=>(
            <div>
              {r.segment_fit.map(s=>(
                <div key={s.segment_id}>
                  <BarRow label={s.segment_name.length>34?s.segment_name.slice(0,34)+"…":s.segment_name} value={s.fit_1_5}/>
                  <div className="small muted" style={{margin:"-2px 0 8px 0"}}>{s.rationale}</div>
                </div>
              ))}
            </div>
          )},
          {id:"agentic", label:"Agentic future & research", render:()=>(
            <div>
              <div className="kpi" style={{margin:"4px 0 12px"}}>
                <div className="k">Overall<b>{fmt(r.agentic_future.score_1_5)}/5</b></div>
                <div className="k">Openness / data<b>{fmt(r.agentic_future.openness_1_5)}/5</b></div>
                <div className="k">AI capability<b>{fmt(r.agentic_future.ai_capability_1_5)}/5</b></div>
                <div className="k">Data-control risk<b>{r.agentic_future.data_control_risk}</b></div>
              </div>
              <p className="small measure">{r.agentic_future.rationale}</p>
              {r.agentic_future.citations?.length>0 && <div className="small muted">Sources: {r.agentic_future.citations.map((c,i)=>(
                <span key={i}>{c.url? <a href={c.url} target="_blank" rel="noreferrer">{c.title||c.url}</a> : c.title}{i<r.agentic_future.citations.length-1?", ":""}</span>))}</div>}
              {r.external_research && r.external_research.name && (
                <div style={{marginTop:14,paddingTop:14,borderTop:"1px solid var(--line)"}}>
                  <b className="small">External research (cited, distinct from internal scoring)</b>
                  <div className="kpi" style={{margin:"10px 0"}}>
                    {Object.entries(r.external_research.ratings||{}).map(([k,v])=>(
                      <div className="k" key={k}>{k.replace(/_/g," ")}<b>{v}</b></div>))}
                  </div>
                  <div className="research-grid small">
                    <p style={{margin:"4px 0"}}><b>Ownership/stability:</b> {r.external_research.ownership}</p>
                    <p style={{margin:"4px 0"}}><b>Analyst:</b> {r.external_research.analyst}</p>
                    <p style={{margin:"4px 0"}}><b>HVAC fit:</b> {r.external_research.hvac_fit}</p>
                    <p style={{margin:"4px 0"}}><b>Project financials:</b> {r.external_research.project_financials}</p>
                    <p style={{margin:"4px 0"}}><b>Agentic AI:</b> {r.external_research.agentic_ai}</p>
                    <p style={{margin:"4px 0"}}><b>Risks for this buyer:</b> {r.external_research.risks}</p>
                  </div>
                  {r.external_research.sources && <div className="muted small" style={{marginTop:8}}>Sources: {r.external_research.sources.map((s,i)=>(
                    <span key={i}><a href={s.url} target="_blank" rel="noreferrer">{s.title||s.url}</a>{i<r.external_research.sources.length-1?" · ":""}</span>))}</div>}
                </div>
              )}
            </div>
          )},
        ]}/>
      </div>
```

- [ ] **Step 2: Verify in browser**

Restart the server and open **Vendor detail → IFS**. Expected:
- One "Scoring detail" card with four sub-tabs: **Scorecard categories | RFP capabilities (§30) | OpCo-segment fit | Agentic future & research**.
- Default tab = Scorecard categories, showing the same bars/rationales as before.
- Clicking each tab swaps the panel; "Agentic future & research" shows the KPI row, rationale, and the external-research block below a divider.
- No content from the old four sections is lost.

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): consolidate vendor scoring deep-dives into tabs"
```

---

## Task 4: Vendor detail — 422 table collapsed, gaps-first

**Files:**
- Modify: `frontend/index.html` `VendorDetail` requirement-table region (lines 923–end of table `</div>`, ~line 975).

**Interfaces:**
- Consumes: `whatToCloseRows`, `Disclosure`. Reuses existing `capFilter`/`filter`/`sortKey` state and the `rows` grid.
- Produces: nothing new.

- [ ] **Step 1: Insert the gaps-first summary and wrap the full grid in a Disclosure**

Replace the section-title + card opening at lines 923–925:

```jsx
      {/* Requirement-level table */}
      <div className="section-title">Requirement-level scoring ({r.requirement_scores.length} requirements)</div>
      <div className="card">
```

with:

```jsx
      {/* Requirement-level table */}
      <div className="section-title">Requirement-level scoring ({r.requirement_scores.length} requirements)</div>
      <div className="card">
        {(()=>{const wtc=whatToCloseRows(r);return (
          <div style={{marginBottom:12}}>
            <b className="small">What to close ({wtc.length})</b>
            {wtc.length===0
              ? <p className="small muted" style={{marginTop:6}}>No unmet Musts, GAP/ROADMAP items, or low-quality (≤2) requirements.</p>
              : <ul className="small" style={{margin:"6px 0 0 16px",padding:0}}>
                  {wtc.slice(0,12).map(x=>(
                    <li key={x.rid}><b>{x.rid}</b> <span className="tag">{x.capability}</span> <span className={"met-"+String(x.met).replace("/","")}>{x.met}</span>
                      {x.code?<span className="tag" style={{marginLeft:4}}>{x.code}</span>:null} — {x.note}</li>
                  ))}
                  {wtc.length>12 && <li className="muted">…and {wtc.length-12} more (see full table below).</li>}
                </ul>}
          </div>
        );})()}
        <Disclosure label="Show all 422 requirements">
```

- [ ] **Step 2: Close the Disclosure after the table**

The existing requirement-controls + `.requirement-table-wrap` + table (lines 926–~972) now sit inside the Disclosure. After the table's closing `</table>` and its wrapper `</div>` (the `.requirement-table-wrap` close, ~line 973), add the Disclosure close so the structure is: `</table></div></Disclosure></div>`. Concretely, find:

```jsx
        </table>
        </div>
      </div>
```

and change the middle/last lines to:

```jsx
        </table>
        </div>
        </Disclosure>
      </div>
```

(The `Export requirements (CSV)` button at the top of `VendorDetail` — lines 770–773 — stays where it is, always visible.)

- [ ] **Step 3: Verify in browser**

Restart the server, open **Vendor detail → IFS**. Expected:
- A **"What to close (N)"** list showing unmet Musts / GAP / ROADMAP / low-quality rows (IFS shows the SCL/RLC/TPA unmet Musts and GAP items).
- A collapsed **"▸ Show all 422 requirements"** toggle; expanding it reveals the original filterable, sortable table with the cap filter, text filter, and "showing N" counter all working.
- CSV export button still present above.
- Check a passing vendor with few gaps still shows a sensible (possibly short) list; if any vendor truly has none, the positive empty state appears.

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): gaps-first requirement summary, full 422 table collapsed"
```

---

## Task 5: Methodology — identity card with expandable full doctrine

**Files:**
- Modify: `frontend/index.html` `Methodology` identity block (lines 1235–1244).

**Interfaces:**
- Consumes: `Disclosure`, classes `.measure`. Reads `kb.persona` fields: `weighting_doctrine.{principle,quote,implications[]}`, `agentic_future_doctrine.{summary,principles[],quote}`, `opco_diversity_doctrine.{summary,quotes[]}`, `scoring_method_doctrine.summary`.
- Produces: nothing new.

- [ ] **Step 1: Replace the identity card body**

Replace lines 1235–1244 (the `The agent — who it is` section-title through the closing `</div>` of that card) with:

```jsx
      <div className="section-title">The agent — who it is</div>
      <div className="card">
        <h3>{p.display_name}</h3>
        <p className="small measure">{p.one_line}</p>
        <p className="small muted">{p.provenance}</p>
        <p className="small"><b>Weighting:</b> {p.weighting_doctrine.principle}</p>
        <p className="small"><b>Agentic future:</b> {p.agentic_future_doctrine.summary}</p>
        <p className="small"><b>OpCo diversity:</b> {p.opco_diversity_doctrine.summary}</p>
        <p className="small"><b>How it scores:</b> {p.scoring_method_doctrine.summary}</p>
        <Disclosure label="Full methodology">
          <div className="small measure">
            {p.weighting_doctrine.quote && <p><i>"{p.weighting_doctrine.quote}"</i></p>}
            {Array.isArray(p.weighting_doctrine.implications) && p.weighting_doctrine.implications.length>0 && <div>
              <b>Weighting implications</b>
              <ul style={{margin:"4px 0 0 16px",padding:0}}>{p.weighting_doctrine.implications.map((x,i)=>(<li key={i}>{x}</li>))}</ul></div>}
            {Array.isArray(p.agentic_future_doctrine.principles) && p.agentic_future_doctrine.principles.length>0 && <div style={{marginTop:8}}>
              <b>Agentic-future principles</b>
              <ul style={{margin:"4px 0 0 16px",padding:0}}>{p.agentic_future_doctrine.principles.map((x,i)=>(<li key={i}>{x}</li>))}</ul></div>}
            {Array.isArray(p.opco_diversity_doctrine.quotes) && p.opco_diversity_doctrine.quotes.length>0 && <div style={{marginTop:8}}>
              <b>OpCo-diversity</b>
              <ul style={{margin:"4px 0 0 16px",padding:0}}>{p.opco_diversity_doctrine.quotes.map((x,i)=>(<li key={i}><i>"{x}"</i></li>))}</ul></div>}
          </div>
        </Disclosure>
      </div>
```

- [ ] **Step 2: Verify in browser**

Restart the server, open **Methodology & rubric**. Expected:
- Identity card: name, one-line, provenance, then four labeled one-liner doctrines (Weighting / Agentic future / OpCo diversity / How it scores).
- A **"▸ Full methodology"** toggle expands the weighting quote + implications list, agentic principles, and OpCo-diversity quotes.
- Rubric-weight and §30 tables below are unchanged.

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): methodology identity card with expandable full doctrine"
```

---

## Task 6: Methodology — tightened OpCo archetype cards

**Files:**
- Modify: `frontend/index.html` `Methodology` OpCo archetypes block (lines 1260–1270).

**Interfaces:**
- Consumes: `archetypePriorities`, `Disclosure`. Reads `kb.segments.archetypes[]`: `name`, `exemplars[]`, `characteristics`, `needs[]`, `fit_emphasis{}`.
- Produces: nothing new.

- [ ] **Step 1: Replace the archetype card map**

Replace lines 1262–1269 (the `seg.archetypes.map(...)` body) with:

```jsx
        {seg.archetypes.map(a=>(
          <div className="card small" key={a.id}>
            <h3 style={{fontSize:14}}>{a.name}</h3>
            <p className="muted" style={{margin:"2px 0"}}>{a.exemplars.join(", ")}</p>
            <p style={{margin:"6px 0"}}>{a.characteristics}</p>
            {archetypePriorities(a.fit_emphasis).length>0 &&
              <p className="muted" style={{margin:"6px 0 0"}}><b>Prioritizes:</b> {archetypePriorities(a.fit_emphasis).join(", ")}</p>}
            <Disclosure label={`Needs (${(a.needs||[]).length})`}>
              <ul className="small" style={{margin:"4px 0 0 16px",padding:0}}>{(a.needs||[]).map((n,i)=>(<li key={i}>{n}</li>))}</ul>
            </Disclosure>
          </div>
        ))}
```

- [ ] **Step 2: Verify in browser**

Restart the server, open **Methodology & rubric**. Expected:
- Six OpCo cards, each: name, exemplars, characteristics, a **"Prioritizes: PJE, W2C, RLC"**-style line (top emphasis codes), and a collapsed **"▸ Needs (N)"** toggle that expands the needs as a bullet list.
- Quality scale card below is unchanged.

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): tighten OpCo archetype cards with priorities + collapsible needs"
```

---

## Task 7: Rebuild standalone + full-app visual review

**Files:**
- Regenerate: `FSM_Evaluation_Agent_Standalone.html` (via script; do not hand-edit).

**Interfaces:** none.

- [ ] **Step 1: Rebuild the standalone single-file app**

```bash
cd backend && python3 build_static.py
```
Expected: writes `../FSM_Evaluation_Agent_Standalone.html` with no error.

- [ ] **Step 2: Verify the standalone opens offline**

Open `FSM_Evaluation_Agent_Standalone.html` directly in a browser (no server). Expected: app renders; Vendor detail and Methodology show the new layouts; no network calls needed for display.

- [ ] **Step 3: Full visual pass across ALL EIGHT tabs**

With the server running (or the standalone open), click through every tab and confirm none regressed from the `:root` token addition or the new components:
`Dashboard` · `Vendor detail` · `Compare` · `Batch evaluate` · `Methodology & rubric` · `Ask the agent` · `Committee scores` · `Account`.
Expected: every tab renders; header/nav/brand look unchanged; no blank panels; no console errors. Capture a screenshot of Vendor detail and Methodology for the record.

- [ ] **Step 4: Verify curated numbers byte-identical**

```bash
cd "$(git rev-parse --show-toplevel)" && git diff --stat HEAD~6 -- backend/data/sample_results.json
```
Expected: **no output** (the curated results file was never touched across the six feature commits).

- [ ] **Step 5: Commit the rebuilt standalone**

```bash
git add FSM_Evaluation_Agent_Standalone.html
git commit -m "chore(build): rebuild standalone after readability redesign"
```

---

## Self-Review notes

- **Spec coverage:** shared foundations → Task 1; vote lead+expand + dissent → Task 2; scoring tabs → Task 3; gaps-first 422 table → Task 4; methodology identity card → Task 5; OpCo cards → Task 6; standalone rebuild + all-eight-tab visual pass + numbers-unchanged → Task 7. Rubric/§30 tables intentionally untouched (spec §Methodology 2). Error/edge cases (short narrative → no expander via `leadAndRest`; empty "what to close" positive state; tabs default to first panel) are implemented in Tasks 1/2/4.
- **Type consistency:** `Disclosure`, `Tabs`, `leadAndRest`, `voteBottomLine`, `whatToCloseRows`, `archetypePriorities` are defined once in Task 1 and consumed with the same signatures in Tasks 2–6. Config field names verified against `persona.json` (`implications`/`principles`/`quotes` are lists; `scoring_method_doctrine` has only `summary`) and `segments.json` (`fit_emphasis` map, `needs` list).
