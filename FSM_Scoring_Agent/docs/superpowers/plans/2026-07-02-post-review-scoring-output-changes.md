# Post-Review Scoring & Output Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the four changes from the 2026-07-02 review meeting — CUSTOM stops disqualifying a Must, customization becomes a visible risk, a commentary-free disqualification report ships, and SSA is stripped from vendor-facing scoring output.

**Architecture:** Behavior changes live in editable JSON knowledge where possible (persona/scorecard), not hard-coded prompts. The deterministic gate already passes CUSTOM, so §1 is a knowledge-text change plus a contract test. The customization risk is computed deterministically in `vote.py`. The disqualification report is built entirely client-side from the (newly enriched) `gating.unmet_musts`, rendered through the existing `brandedDoc` + browser print-to-PDF pipeline — zero new dependencies, works in the offline standalone. The SSA sweep is label-string edits in the frontend.

**Tech Stack:** Python 3.12 / Flask backend, React-18-via-CDN frontend (in-browser Babel, no build toolchain), `unittest`/`pytest` tests, `openpyxl` (already present). No new dependencies.

## Global Constraints

- Persona/behavior changes go in JSON knowledge (`config/*.json`), not hard-coded prompt strings, wherever possible.
- Gating is deterministic and never LLM-overridable. After this change: a Must marked **No, GAP, or ROADMAP** disqualifies; a Must answered **CUSTOM meets** the requirement (no disqualification) and is flagged as a risk. Single-tenant and union/non-union isolation remain hard architectural gates.
- The offline "mock" engine must always work with no network/keys. CUSTOM already maps to `("Partial", 2)` in both the mock and matrix paths — do not change that mapping.
- API keys are read from the environment only, never written to disk or logged.
- No new runtime dependencies. The disqualification report is client-side print-to-PDF and must work in the standalone single-file build.
- Vendor-facing scoring output must not reference "SSA." App chrome/login branding (logo, `<title>`, app footer identity, `--ssa-*` CSS token names) is KEPT.
- Tests are `unittest`-style under `backend/tests/`, run from `backend/` with `python3 -m pytest tests/ -q`. The suite currently has 34 passing tests.
- After any `frontend/index.html` change, rebuild the standalone: `cd backend && python3 build_static.py` (writes `../FSM_Evaluation_Agent_Standalone.html`).
- Every commit ends with the trailer:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01S6uvj42YbY4UwmGXYgb6Qx
  ```
- After §1, vendors must be **re-scored** for the new gating to take effect on stored results (out-of-band; not a plan task).

---

### Task 1: CUSTOM meets the Must — knowledge change + gating contract test

**Files:**
- Modify: `backend/config/scorecard.json` (`moscow.Must`, `gating_rules`)
- Modify: `backend/config/persona.json` (the ROADMAP/CUSTOM red-flag entry)
- Test: `backend/tests/test_gating.py` (create)

**Interfaces:**
- Consumes: `scoring._compute_gating(scores, proposal_text)` (current signature), `schemas.RequirementScore`, `schemas.GatingResult`.
- Produces: nothing new for later tasks (knowledge + test only). Confirms the gating contract Task 3 will extend.

**Context:** The deterministic gate (`backend/agent/scoring.py:581` `_compute_gating`) already passes CUSTOM — `_WEAK_CODES_FOR_MUST = {"ROADMAP", "GAP"}` (`scoring.py:63`) and CUSTOM maps to `met="Partial"`. What disqualifies CUSTOM today is the config text fed to the live model: `scorecard.json` and `persona.json` instruct it to treat "CUSTOM without firm SOW" as not-met, so it returns `met="No"`. This task fixes that text and locks the intended contract with a test.

- [ ] **Step 1: Write the gating contract test**

Create `backend/tests/test_gating.py`:

```python
import unittest
from agent import scoring
from agent.schemas import RequirementScore


def _score(rid, priority, met, quality, code):
    return RequirementScore(
        rid=rid, domain="A", capability="W2C", priority=priority,
        met=met, quality=quality, vendor_code=code, confidence="High",
        rationale="t",
    )


class GatingContractTests(unittest.TestCase):
    def test_custom_must_does_not_disqualify(self):
        # CUSTOM on a Must scores Partial and must NOT disqualify.
        scores = [_score("FSM-001", "Must", "Partial", 2, "CUSTOM")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertFalse(g.disqualified)
        self.assertEqual(g.unmet_must_count, 0)

    def test_gap_must_disqualifies(self):
        scores = [_score("FSM-002", "Must", "No", 1, "GAP")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertTrue(g.disqualified)

    def test_roadmap_must_disqualifies(self):
        # ROADMAP on a Must (not answered Yes) is still disqualifying.
        scores = [_score("FSM-003", "Must", "Partial", 2, "ROADMAP")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertTrue(g.disqualified)

    def test_no_must_disqualifies_regardless_of_code(self):
        scores = [_score("FSM-004", "Must", "No", 1, "CONFIG")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertTrue(g.disqualified)

    def test_should_gap_does_not_gate(self):
        # Only Musts gate; a GAP on a Should does not disqualify.
        scores = [_score("FSM-005", "Should", "No", 1, "GAP")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertFalse(g.disqualified)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to confirm the current gate already honors the contract**

Run: `cd backend && python3 -m pytest tests/test_gating.py -v`
Expected: PASS (5/5). This confirms the deterministic gate is already correct — the fix is in the knowledge text (Steps 3-4). If any test FAILS, the gate has an unexpected behavior; fix `_compute_gating` to satisfy the contract before proceeding.

- [ ] **Step 3: Update `scorecard.json` gating text**

In `backend/config/scorecard.json`, replace the `moscow.Must` string:

```
"Non-negotiable. A 'No' (or unsupported ROADMAP/CUSTOM without firm SOW) on any Must is a basis for disqualification."
```

with:

```
"Non-negotiable. A 'No', GAP, or ROADMAP on any Must is a basis for disqualification. A Must answered CUSTOM meets the requirement (delivered via custom development) — it does not disqualify, but heavy reliance on custom work is a risk to flag."
```

Then in `gating_rules`, set `"custom_must_needs_firm_sow": false` (was `true`), and replace the `description`:

```
"Any Must marked No -> disqualifying. A Must answered ROADMAP, GAP, or CUSTOM-without-SOW is treated as effectively unmet for gating. Single-tenant deployment and absolute entity-level union/non-union data isolation are hard architectural gates."
```

with:

```
"Any Must marked No, GAP, or ROADMAP -> disqualifying. A Must answered CUSTOM meets the requirement (delivered via custom development) and does NOT disqualify, though it is surfaced as a customization risk. Single-tenant deployment and absolute entity-level union/non-union data isolation are hard architectural gates."
```

- [ ] **Step 4: Update `persona.json` red-flag text**

In `backend/config/persona.json`, find the red-flag entry:

```json
{"flag": "Vaporware / roadmap promises in place of GA capability", "trigger": "ROADMAP or CUSTOM used to answer Must requirements without a firm SOW/GA date.", "penalty": "Treat as not-met for gating; heavy quality penalty."},
```

Replace it with two entries (ROADMAP still gates; CUSTOM becomes a non-gating risk):

```json
{"flag": "Vaporware / roadmap promises in place of GA capability", "trigger": "ROADMAP used to answer a Must requirement (not generally available).", "penalty": "Treat as not-met for gating; heavy quality penalty."},
{"flag": "Heavy customization to meet Musts", "trigger": "CUSTOM used to answer Must requirements — the capability requires custom development.", "penalty": "Meets the requirement (NOT disqualifying); score Partial and flag as a maintainability / evolution risk."},
```

Leave the existing quality-preference guidance ("Reward OOB/CONFIG over CUSTOM/ROADMAP", persona line ~44, and `knowledge.py` line ~98) unchanged — that governs quality scoring, not gating.

- [ ] **Step 5: Verify JSON parses and the test still passes**

Run:
```
cd backend && python3 -c "import json; json.load(open('config/scorecard.json')); json.load(open('config/persona.json')); print('JSON OK')" && python3 -m pytest tests/test_gating.py -q
```
Expected: `JSON OK` then 5 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/config/scorecard.json backend/config/persona.json backend/tests/test_gating.py
git commit -m "feat(gating): CUSTOM meets a Must (no disqualification); GAP/ROADMAP still gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01S6uvj42YbY4UwmGXYgb6Qx"
```

---

### Task 2: Customization as a top risk (deterministic, in vote.py)

**Files:**
- Modify: `backend/agent/vote.py` (add `_customization_risk` helper; wire into `synthesize_vote`, the risk block at ~L97-109)
- Test: `backend/tests/test_vote_risks.py` (create)

**Interfaces:**
- Consumes: `VendorEvaluation.requirement_scores` (`List[RequirementScore]`, already populated before `synthesize_vote` runs), each with `.priority` and `.vendor_code`.
- Produces: `vote._customization_risk(scores) -> tuple[int, str | None]` — `(count_of_CUSTOM_Musts, message_or_None)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_vote_risks.py`:

```python
import unittest
from agent import vote
from agent.schemas import RequirementScore


def _score(rid, priority, code):
    return RequirementScore(
        rid=rid, domain="A", capability="W2C", priority=priority,
        met="Partial", quality=2, vendor_code=code, confidence="High",
        rationale="t",
    )


class CustomizationRiskTests(unittest.TestCase):
    def test_none_when_no_custom_musts(self):
        scores = [_score("FSM-001", "Must", "OOB"), _score("FSM-002", "Should", "CUSTOM")]
        n, msg = vote._customization_risk(scores)
        self.assertEqual(n, 0)
        self.assertIsNone(msg)

    def test_counts_only_custom_musts(self):
        scores = [
            _score("FSM-001", "Must", "CUSTOM"),
            _score("FSM-002", "Must", "CUSTOM"),
            _score("FSM-003", "Must", "OOB"),
            _score("FSM-004", "Should", "CUSTOM"),  # not a Must -> not counted
        ]
        n, msg = vote._customization_risk(scores)
        self.assertEqual(n, 2)
        self.assertIn("2 Must requirement", msg)
        self.assertIn("custom", msg.lower())

    def test_empty_scores_safe(self):
        n, msg = vote._customization_risk([])
        self.assertEqual(n, 0)
        self.assertIsNone(msg)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_vote_risks.py -v`
Expected: FAIL with `AttributeError: module 'agent.vote' has no attribute '_customization_risk'`.

- [ ] **Step 3: Add the helper and wire it into `synthesize_vote`**

In `backend/agent/vote.py`, add the helper above `synthesize_vote` (before line ~83):

```python
def _customization_risk(scores):
    """Deterministic risk when Musts are met only via custom development.
    Returns (count_of_CUSTOM_Musts, message) or (0, None) when none."""
    n = sum(1 for s in scores if s.priority == "Must" and s.vendor_code == "CUSTOM")
    if n == 0:
        return 0, None
    return n, (f"Heavy customization: {n} Must requirement(s) met only via custom "
               f"development — costly to maintain and evolve.")
```

Then in `synthesize_vote`, replace the risk block (currently lines ~97-109):

```python
    # Top risks = weakest high-weight capabilities + data-control risk + worst segment.
    risks: List[str] = []
    if ev.gating and ev.gating.disqualified:
        risks.append(f"Disqualifying: {ev.gating.unmet_must_count} unmet Must requirement(s).")
    for c in sorted(ev.capabilities, key=lambda c: c.score_1_5)[:2]:
        if c.score_1_5 < 3.5:
            risks.append(f"{c.name} weak at {c.score_1_5}/5 (weight {int(c.weight*100)}%).")
    if ev.agentic_future and ev.agentic_future.data_control_risk == "High":
        risks.append("High data-control risk — the OpCos may not control their own AI destiny.")
    worst_seg = min(ev.segment_fit, key=lambda s: s.fit_1_5, default=None)
    if worst_seg and worst_seg.fit_1_5 < 3.0:
        risks.append(f"Poor fit for {worst_seg.segment_name} ({worst_seg.fit_1_5}/5).")
    risks = risks[:5] or ["No dominant risk; close the evidence gaps in the demo."]
```

with:

```python
    # Top risks = weakest high-weight capabilities + data-control risk + worst segment,
    # plus a deterministic customization risk (Musts met only via custom development).
    cust_n, cust_msg = _customization_risk(ev.requirement_scores)
    risks: List[str] = []
    if ev.gating and ev.gating.disqualified:
        risks.append(f"Disqualifying: {ev.gating.unmet_must_count} unmet Must requirement(s).")
    if cust_msg and cust_n >= 3:
        risks.append(cust_msg)   # material reliance on custom work -> ranked high
    for c in sorted(ev.capabilities, key=lambda c: c.score_1_5)[:2]:
        if c.score_1_5 < 3.5:
            risks.append(f"{c.name} weak at {c.score_1_5}/5 (weight {int(c.weight*100)}%).")
    if ev.agentic_future and ev.agentic_future.data_control_risk == "High":
        risks.append("High data-control risk — the OpCos may not control their own AI destiny.")
    worst_seg = min(ev.segment_fit, key=lambda s: s.fit_1_5, default=None)
    if worst_seg and worst_seg.fit_1_5 < 3.0:
        risks.append(f"Poor fit for {worst_seg.segment_name} ({worst_seg.fit_1_5}/5).")
    if cust_msg and cust_n < 3:
        risks.append(cust_msg)   # some custom work -> lower priority
    risks = risks[:5] or ["No dominant risk; close the evidence gaps in the demo."]
```

- [ ] **Step 4: Run the unit test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_vote_risks.py -v`
Expected: PASS (3/3).

- [ ] **Step 5: Add an integration assertion (risk surfaces through a real vote)**

Append to `backend/tests/test_vote_risks.py`:

```python
class CustomizationRiskIntegrationTests(unittest.TestCase):
    def test_custom_musts_surface_in_vote(self):
        from agent import scoring
        from agent.knowledge import get_kb
        reqs = get_kb().requirement_list()
        must_rids = [r["rid"] for r in reqs if r["priority"] == "Must"][:4]
        self.assertGreaterEqual(len(must_rids), 3, "fixture needs >=3 Must requirements")
        matrix = {rid: {"code": "CUSTOM", "response": "Custom build required",
                        "source": "r.xlsx", "sheet": "Requirements"} for rid in must_rids}
        ev = scoring.evaluate_vendor("TestVendor", "", "proposal text",
                                     scoring_model="mock", requirement_sample=None,
                                     requirement_matrix=matrix)
        ev.vote = vote.synthesize_vote(ev, model_id="mock")
        self.assertTrue(any("Heavy customization" in r for r in ev.vote.top_risks),
                        f"customization risk missing from {ev.vote.top_risks}")
```

- [ ] **Step 6: Run both classes**

Run: `cd backend && python3 -m pytest tests/test_vote_risks.py -q`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/agent/vote.py backend/tests/test_vote_risks.py
git commit -m "feat(vote): surface heavy customization on Musts as a ranked risk

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01S6uvj42YbY4UwmGXYgb6Qx"
```

---

### Task 3: Enrich `unmet_musts` with requirement detail (backend data for the report)

**Files:**
- Modify: `backend/agent/scoring.py` (`_compute_gating` signature + unmet entry fields + remove the `[:50]` cap; `evaluate_vendor` passes a `{rid: requirement}` map)
- Test: `backend/tests/test_gating.py` (append a class)

**Interfaces:**
- Consumes: `reqs = kb.requirement_list()` items, each a dict with `["rid"]` and `["requirement"]` (text).
- Produces: `_compute_gating(scores, proposal_text, req_text=None)` where `req_text` is `{rid: requirement_text}`. Each `GatingResult.unmet_musts` entry now carries `{rid, capability, requirement, domain, priority, vendor_code, met, reason}`. `unmet_musts` is no longer truncated. This is what Task 4's report consumes.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_gating.py`:

```python
class UnmetMustEnrichmentTests(unittest.TestCase):
    def test_unmet_entry_includes_requirement_detail(self):
        scores = [_score("FSM-002", "Must", "No", 1, "GAP")]
        req_text = {"FSM-002": "Support prevailing-wage certified payroll."}
        g = scoring._compute_gating(scores, "proposal text", req_text)
        self.assertEqual(len(g.unmet_musts), 1)
        entry = g.unmet_musts[0]
        self.assertEqual(entry["rid"], "FSM-002")
        self.assertEqual(entry["requirement"], "Support prevailing-wage certified payroll.")
        self.assertEqual(entry["priority"], "Must")
        self.assertEqual(entry["vendor_code"], "GAP")
        self.assertEqual(entry["met"], "No")

    def test_missing_req_text_defaults_empty(self):
        scores = [_score("FSM-002", "Must", "No", 1, "GAP")]
        g = scoring._compute_gating(scores, "proposal text")  # no req_text
        self.assertEqual(g.unmet_musts[0]["requirement"], "")

    def test_unmet_list_not_truncated(self):
        scores = [_score(f"FSM-{i:03d}", "Must", "No", 1, "GAP") for i in range(60)]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertEqual(len(g.unmet_musts), 60)
        self.assertEqual(g.unmet_must_count, 60)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_gating.py::UnmetMustEnrichmentTests -v`
Expected: FAIL — `KeyError: 'requirement'` (entry lacks the new fields) and the truncation test fails at 50.

- [ ] **Step 3: Enrich `_compute_gating`**

In `backend/agent/scoring.py`, change the `_compute_gating` signature and the unmet-append block (lines ~581-591). Replace:

```python
def _compute_gating(scores: List[RequirementScore], proposal_text: str) -> GatingResult:
    unmet = []
    for s in scores:
        if s.priority != "Must":
            continue
        # A Must answered ROADMAP/GAP (and not 'Yes') is effectively unmet for gating.
        if s.met == "No" or (s.vendor_code in _WEAK_CODES_FOR_MUST and s.met != "Yes"):
            unmet.append({
                "rid": s.rid, "capability": s.capability,
                "reason": f"Must requirement is {s.met} via {s.vendor_code}",
            })
```

with:

```python
def _compute_gating(scores: List[RequirementScore], proposal_text: str,
                    req_text: Optional[Dict[str, str]] = None) -> GatingResult:
    req_text = req_text or {}
    unmet = []
    for s in scores:
        if s.priority != "Must":
            continue
        # A Must answered ROADMAP/GAP (and not 'Yes') is effectively unmet for gating.
        if s.met == "No" or (s.vendor_code in _WEAK_CODES_FOR_MUST and s.met != "Yes"):
            unmet.append({
                "rid": s.rid, "capability": s.capability,
                "requirement": req_text.get(s.rid, ""),
                "domain": s.domain, "priority": s.priority,
                "vendor_code": s.vendor_code, "met": s.met,
                "reason": f"Must requirement is {s.met} via {s.vendor_code}",
            })
```

Then change the `GatingResult(...)` return so `unmet_musts` is no longer truncated. Replace:

```python
        unmet_musts=unmet[:50], architectural_gate_flags=flags, summary=summary,
```

with:

```python
        unmet_musts=unmet, architectural_gate_flags=flags, summary=summary,
```

(`Optional` and `Dict` are already imported at the top of `scoring.py`.)

- [ ] **Step 4: Pass the requirement-text map from `evaluate_vendor`**

In `backend/agent/scoring.py`, at the gating call (line ~115), replace:

```python
    gating = _compute_gating(req_scores, clean_text)
```

with:

```python
    gating = _compute_gating(req_scores, clean_text,
                             {r["rid"]: r.get("requirement", "") for r in reqs})
```

- [ ] **Step 5: Run the enrichment test and the full suite**

Run: `cd backend && python3 -m pytest tests/test_gating.py -q && python3 -m pytest tests/ -q`
Expected: `test_gating.py` all pass; full suite passes (now 34 + new tests).

- [ ] **Step 6: Commit**

```bash
git add backend/agent/scoring.py backend/tests/test_gating.py
git commit -m "feat(gating): enrich unmet_musts with requirement text/priority/code; drop 50-cap

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01S6uvj42YbY4UwmGXYgb6Qx"
```

---

### Task 4: Disqualification report — client-side print-to-PDF

**Files:**
- Modify: `frontend/index.html` (add `disqualificationRows` builder + `DQ_CODE_REASON` constant near the export helpers; parameterize `brandedDoc`/`printBranded` with `footerText`; add the report button in `VendorDetail`)
- Modify: `FSM_Evaluation_Agent_Standalone.html` (regenerated by build)

**Interfaces:**
- Consumes: `data.gating.unmet_musts` (enriched by Task 3), `data.gating.architectural_gate_flags`, `data.gating.disqualified`, `data.gating.unmet_must_count`; existing `tableHTML(rows, headers)` and `printBranded(title, parts)`.
- Produces: no backend interface. New global `disqualificationRows(data) -> {rows, headers}`.

**Context:** There is no JS test harness (project convention = manual verification). The existing print pipeline is `printBranded(title, {contextLine, takeaway, tableHTML, footerText?})` → `brandedDoc` → `window.open` + `print()`, with an iframe fallback. The "Export requirements (CSV)" button in `VendorDetail` (line ~736) is the pattern to mirror for placement.

- [ ] **Step 1: Add the `footerText` parameter to `brandedDoc`**

In `frontend/index.html`, in `brandedDoc(o)` (line ~479), replace the footer line:

```javascript
    + '<footer>SSA &amp; Company · Advisory evaluation — augments the human committee · Generated '+htmlEsc(o.dateStr)+'</footer>'
```

with:

```javascript
    + '<footer>'+(o.footerText
        ? htmlEsc(o.footerText)
        : 'SSA &amp; Company · Advisory evaluation — augments the human committee · Generated '+htmlEsc(o.dateStr))+'</footer>'
```

- [ ] **Step 2: Forward `footerText` through `printBranded`**

In `printBranded(title, parts)` (line ~537), replace the `brandedDoc({...})` call:

```javascript
  const docHTML = brandedDoc({title, dateStr, logoSrc,
    contextLine:parts.contextLine||"", takeaway:parts.takeaway||"", tableHTML:parts.tableHTML||""});
```

with:

```javascript
  const docHTML = brandedDoc({title, dateStr, logoSrc,
    contextLine:parts.contextLine||"", takeaway:parts.takeaway||"", tableHTML:parts.tableHTML||"",
    footerText:parts.footerText||""});
```

- [ ] **Step 3: Add the report row builder and reason map**

In `frontend/index.html`, immediately after the `downloadCSV` function (ends ~line 516) and before `resolvePrintLogo`, add:

```javascript
// Plain-language reason per response code for the disqualification report.
// Factual, no commentary. CUSTOM no longer disqualifies, so it should not appear.
const DQ_CODE_REASON = {
  GAP: "Not supported; no published roadmap.",
  ROADMAP: "Planned only; not generally available.",
  "": "Requirement not addressed.",
};
function disqualificationRows(data){
  const g = (data && data.gating) || {};
  const um = g.unmet_musts || [];
  const rows = um.map(u => ({
    rid: u.rid,
    requirement: u.requirement || ("(see RFP requirement " + u.rid + ")"),
    priority: u.priority || "Must",
    response: u.vendor_code || "",
    reason: DQ_CODE_REASON[u.vendor_code] || u.reason || "Does not meet the Must requirement.",
  }));
  (g.architectural_gate_flags || []).forEach(f => rows.push({
    rid: "—", requirement: f, priority: "Must",
    response: "GATE", reason: "Architectural gate not satisfied.",
  }));
  const headers = [
    {key:"rid", label:"RID"},
    {key:"requirement", label:"Requirement"},
    {key:"priority", label:"Priority"},
    {key:"response", label:"Response"},
    {key:"reason", label:"Reason not met"},
  ];
  return {rows, headers};
}
```

- [ ] **Step 4: Add the report button in `VendorDetail`**

In `frontend/index.html`, in `VendorDetail`, right after the "Export requirements (CSV)" button (closes at line ~739), add:

```javascript
      {data.gating && data.gating.disqualified &&
        <button className="btn small" style={{marginBottom:10, marginLeft:8}} onClick={()=>{
          const {rows,headers}=disqualificationRows(data);
          printBranded("Disqualification Report — "+data.vendor, {
            contextLine: "Disqualified under RFP §8: "+data.gating.unmet_must_count+" unmet Must requirement(s).",
            tableHTML: tableHTML(rows, headers),
            footerText: "Disqualification detail — requirement level. Generated "+new Date().toISOString().slice(0,10)+".",
          });
        }}>Disqualification report (PDF)</button>}
```

- [ ] **Step 5: Rebuild the standalone**

Run: `cd backend && python3 build_static.py`
Expected: prints the standalone path with no error; `../FSM_Evaluation_Agent_Standalone.html` is regenerated.

- [ ] **Step 6: Manual verification (no JS test harness)**

Open `FSM_Evaluation_Agent_Standalone.html` in a browser (the seeded demo has disqualified vendors). Verify:
- The "Disqualification report (PDF)" button appears only on a **disqualified** vendor's detail view; absent on a passing vendor.
- Clicking it opens a print view titled "Disqualification Report — <Vendor>" with the factual context line, a table of **RID · Requirement · Priority · Response · Reason not met**, and a neutral footer.
- There is **no** narrative/commentary column and **no** "Advisory evaluation" footer on this report.
- The browser Print dialog can save it as PDF.

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html FSM_Evaluation_Agent_Standalone.html
git commit -m "feat(ui): commentary-free disqualification report (client-side print-to-PDF)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01S6uvj42YbY4UwmGXYgb6Qx"
```

---

### Task 5: Strip SSA from vendor-facing scoring labels

**Files:**
- Modify: `frontend/index.html` (7 label edits at lines ~382, 421, 450, 456, 689, 745, 1052)
- Modify: `FSM_Evaluation_Agent_Standalone.html` (regenerated by build)

**Interfaces:** none. Text-label changes only. App chrome (title, logo alt, wordmark, login, `--ssa-*` CSS tokens, JS comments, the internal export report footer at line ~504) is KEPT.

**Context:** PR #51 already removed the "SSA scorecard categories" section titles; these seven are the remaining vendor-facing *score* labels Nick flagged. `key:"ssa"` at line 421 is an internal object key referenced elsewhere — change only its `label`, not the key.

- [ ] **Step 1: Edit the seven labels**

In `frontend/index.html`, make these exact replacements:

1. Line ~382 (comparison summary lens):
   - From: `` const lens = `SSA ${_cr1(a.weighted_total)} vs ${_cr1(b.weighted_total)}, §30 ${_cr1(a.capability_weighted_total)} vs ${_cr1(b.capability_weighted_total)}`; ``
   - To: `` const lens = `Weighted ${_cr1(a.weighted_total)} vs ${_cr1(b.weighted_total)}, §30 ${_cr1(a.capability_weighted_total)} vs ${_cr1(b.capability_weighted_total)}`; ``

2. Line ~421 (export/compare header; change label only, keep `key:"ssa"`):
   - From: `{key:"ssa",label:"SSA score (0-100)"},`
   - To: `{key:"ssa",label:"Weighted score (0-100)"},`

3. Line ~450:
   - From: `num("Headline","SSA score (0-100)", a.weighted_total, b.weighted_total);`
   - To: `num("Headline","Weighted score (0-100)", a.weighted_total, b.weighted_total);`

4. Line ~456:
   - From: `(a.categories||[]).forEach(ca => num("SSA category", ca.name, ca.raw_1_5, (bcat[ca.name]||{}).raw_1_5||0));`
   - To: `(a.categories||[]).forEach(ca => num("Category", ca.name, ca.raw_1_5, (bcat[ca.name]||{}).raw_1_5||0));`

5. Line ~689 (dashboard table header):
   - From: `<th>#</th><th>Vendor</th><th>SSA total</th><th>Capability</th>`
   - To: `<th>#</th><th>Vendor</th><th>Total</th><th>Capability</th>`

6. Line ~745 (detail score tile):
   - From: `<div className="den">/100 SSA weighted</div>`
   - To: `<div className="den">/100 weighted</div>`

7. Line ~1052 (comparison row):
   - From: `<CmpRow label="SSA weighted total" a={A.weighted_total} b={B.weighted_total} max={100}/>`
   - To: `<CmpRow label="Weighted total" a={A.weighted_total} b={B.weighted_total} max={100}/>`

- [ ] **Step 2: Verify no vendor-facing SSA label remains**

Run: `cd "$(git rev-parse --show-toplevel)" && grep -n "SSA total\|SSA weighted\|SSA score\|SSA category" FSM_Scoring_Agent/frontend/index.html`
Expected: no matches (exit status 1, no output). The remaining `SSA` hits are app chrome (title, logo alt, wordmark, login, CSS comment, JS comment, internal export footer) — those are intentionally kept.

- [ ] **Step 3: Rebuild the standalone**

Run: `cd backend && python3 build_static.py`
Expected: prints the standalone path with no error.

- [ ] **Step 4: Manual verification**

Open `FSM_Evaluation_Agent_Standalone.html`. Confirm the dashboard column reads "Total", the detail tile reads "/100 weighted", and the comparison view shows "Weighted total" / "Weighted score (0-100)" / "Category" — with no "SSA" prefix on any score label. The login screen and header logo still show SSA branding (intended).

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html FSM_Evaluation_Agent_Standalone.html
git commit -m "feat(ui): drop SSA prefix from vendor-facing score labels

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01S6uvj42YbY4UwmGXYgb6Qx"
```

---

## Final verification (after all tasks)

- [ ] `cd backend && python3 -m pytest tests/ -q` — full suite green.
- [ ] `python3 -c "import ast; ast.parse(open('backend/agent/scoring.py').read()); ast.parse(open('backend/agent/vote.py').read()); print('py OK')"` from repo/FSM_Scoring_Agent root.
- [ ] Offline standalone opens, DQ report works on a disqualified vendor, no vendor-facing "SSA" score labels.
- [ ] `graphify update .` to refresh the knowledge graph.
