# Evaluator De-personalization + Debate Framing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reposition the agent from "a digital twin of Nick Kramer" to an evidence-first FSM evaluator built as a multi-analyst panel that debates to a verdict, scrub the name from active code and docs, drop "SSA" from the category labels, and make the existing two-analyst debate visible in the UI and the offline demo.

**Architecture:** Almost entirely string and JSON edits plus one hand-authored demo data block. The scoring engine, gating, rollups, and the persona's reasoning content (tenets, priorities, red flags, voice) are unchanged — only attribution and framing change. The persona system prompt builds from `display_name`, so renaming that field removes the name from live model calls automatically.

**Tech Stack:** Python 3.12 / Flask backend, React-18-via-CDN single-file frontend (no build toolchain), JSON knowledge base. No test suite — verification is JSON-parse + grep + manual server/standalone inspection.

## Global Constraints

- **Use `python3`** — there is no `python` alias in this environment.
- **API keys/secrets come from env only, never written to disk or logged.** No task touches this; do not regress it.
- **The offline "mock" engine must always work** — every change must leave the keyless demo functional.
- **Gating/recommendation stay deterministic** — do not move any gating logic into an LLM call.
- **Leave the Nick Kramer LOGIN account untouched:** `backend/auth.py:33`, `backend/tests/test_auth.py`, `backend/tests/test_auth_api.py`, `docs/LOGIN_INFO.md`. That is a user, not the persona.
- **Leave frozen history untouched:** `docs/superpowers/specs/*` and `docs/superpowers/plans/*` (including this file's siblings).
- **Keep "Service Logic"** everywhere — it is the client running the RFP.
- **SSA removal is category-labels-only** — do not touch the report footer "SSA & Company" or the `scorecard.json` note.
- **Demo data stays honestly labeled** `[demo]` — do not present synthetic numbers as real.
- After code changes, run `graphify update .` (AST-only, no API cost).

Commit message footer for every commit:
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E5dcoxCZ1QpgfcNZnbQ6h5
```

---

### Task 1: New persona identity + scoring-method doctrine

**Files:**
- Modify: `backend/config/persona.json:2-5` (id, display_name, one_line, provenance) and insert a new `scoring_method_doctrine` key after `provenance`.

**Interfaces:**
- Produces: a new persona key `scoring_method_doctrine.summary` (string), rendered by the frontend in Task 4. Existing keys (`weighting_doctrine.principle`, `agentic_future_doctrine.summary`, `opco_diversity_doctrine.summary`) are unchanged.

- [ ] **Step 1: Replace the four identity fields**

In `backend/config/persona.json`, replace lines 2-5 exactly.

Old:
```json
  "id": "nick_kramer_digital_twin_v1",
  "display_name": "The Evaluator — a digital twin of Nick Kramer (SSA & Company), with deep HVAC field-service domain experience",
  "one_line": "Reasons like Nick Kramer but carries 25+ years of hands-on HVAC/mechanical FSM implementation scar tissue.",
  "provenance": "Decision DNA mined from Service Logic engagement transcripts (Apr-Jun 2026) and the RFP Internal Memo / Vendor Scorecard. Domain depth is added on top to exceed Nick's own field exposure, per the build brief.",
```

New:
```json
  "id": "fsm_evaluator_panel_v1",
  "display_name": "The Evaluator — an evidence-first FSM evaluation agent, built as a multi-analyst panel that debates to a single verdict, with deep HVAC/mechanical field-service domain experience",
  "one_line": "Independent analysts score every requirement against the evidence, then reconcile their reads into one verdict — carrying 25+ years of hands-on HVAC/mechanical FSM implementation scar tissue.",
  "provenance": "Decision DNA mined from Service Logic engagement transcripts (Apr-Jun 2026) and the RFP Internal Memo / Vendor Scorecard, augmented with HVAC/mechanical field-service domain depth.",
  "scoring_method_doctrine": {
    "summary": "Two independent AI analysts score every requirement against the evidence, then a reconciliation pass debates their reads into one verdict and surfaces where they disagreed. The result is a panel decision, not a single model's opinion."
  },
```

- [ ] **Step 2: Verify the JSON still parses**

Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && python3 -c "import json; d=json.load(open('backend/config/persona.json')); print(d['id']); print(d['scoring_method_doctrine']['summary'][:40])"`
Expected: prints `fsm_evaluator_panel_v1` then `Two independent AI analysts score every `

- [ ] **Step 3: Verify the name is gone from this file**

Run: `grep -n "Nick\|digital twin\|digital_twin" backend/config/persona.json`
Expected: no output (exit 1).

- [ ] **Step 4: Commit**

```bash
git add backend/config/persona.json
git commit -m "feat(persona): multi-analyst panel identity; drop Nick-Kramer baseline

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E5dcoxCZ1QpgfcNZnbQ6h5"
```

---

### Task 2: Scrub the name from active code

**Files:**
- Modify: `backend/agent/vote.py:194` (runtime prompt string) and `:9` (comment)
- Modify: `backend/agent/schemas.py:107` (comment)
- Modify: `backend/agent/knowledge.py:66` (comment)
- Modify: `backend/agent/scoring.py:26` (comment)
- Modify: `backend/agent/__init__.py:2` (module docstring)

**Interfaces:**
- Produces: no signature changes. The only behavioral edit is the reconciliation prompt text; the system prompt already pulls the (now renamed) `display_name` from Task 1.

- [ ] **Step 1: Fix the reconciliation prompt string in `vote.py`**

Replace line 194 exactly.

Old:
```python
        f"rubric says {reco} ({band_reason}). Reconcile their votes into ONE final vote in Nick Kramer's "
```
New:
```python
        f"rubric says {reco} ({band_reason}). Reconcile their votes into ONE final vote in the panel's reconciled "
```
(Line 195 `f"voice, and surface where they materially disagreed.\n\n"` is unchanged; combined it reads "...in the panel's reconciled voice, and surface...".)

- [ ] **Step 2: Fix the `vote.py:9` comment**

Old:
```python
  * narrative      : the "lead with the verdict, then the why" rationale, in Nick's voice
```
New:
```python
  * narrative      : the "lead with the verdict, then the why" rationale, in the panel's reconciled voice
```

- [ ] **Step 3: Fix the `schemas.py:107` comment**

Old:
```python
    narrative: str                # in Nick's voice
```
New:
```python
    narrative: str                # in the panel's reconciled voice
```

- [ ] **Step 4: Fix the `knowledge.py:66` comment**

Old:
```python
        for every scoring / vote / chat call so each LLM interaction reasons "as Nick".
```
New:
```python
        for every scoring / vote / chat call so each LLM interaction reasons from the same evidence-first doctrine.
```

- [ ] **Step 5: Fix the `scoring.py:26` comment**

Old:
```python
  so the score reflects what actually matters — Nick's "weight by decision leverage".
```
New:
```python
  so the score reflects what actually matters — the "weight by decision leverage" doctrine.
```

- [ ] **Step 6: Fix the `__init__.py:2` module docstring**

Old:
```python
FSM RFP Evaluation Agent — a 'digital twin' of Nick Kramer (SSA & Company) with
deep HVAC field-service domain experience, used to score vendor RFP responses and
```
New:
```python
FSM RFP Evaluation Agent — an evidence-first, multi-analyst FSM evaluator with
deep HVAC field-service domain experience, used to score vendor RFP responses and
```

- [ ] **Step 7: Verify the name is gone from `backend/` (except the login account) and code imports cleanly**

Run: `grep -rIn "Nick Kramer\|digital twin\|Nick's\|as Nick\|of Nick" backend/agent backend/app.py`
Expected: no output (exit 1).

Run: `grep -rIn "Nick" backend/auth.py backend/tests | wc -l`
Expected: a non-zero count (the login account is intentionally preserved).

Run: `cd backend && python3 -c "import agent, agent.vote, agent.scoring, agent.knowledge, agent.schemas; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 8: Commit**

```bash
git add backend/agent/vote.py backend/agent/schemas.py backend/agent/knowledge.py backend/agent/scoring.py backend/agent/__init__.py
git commit -m "refactor: scrub Nick-Kramer name from agent code + reconcile prompt

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E5dcoxCZ1QpgfcNZnbQ6h5"
```

---

### Task 3: Scrub the name from docs

**Files:**
- Modify: `README.md:4`, `CLAUDE.md:10` and `:50`, `docs/DESIGN.md`, `docs/DEMO_GUIDE.md`, `docs/CHANGES_SUMMARY.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: `README.md:4`**

Old (line 4 begins): `an independent, well-reasoned **advisory vote** in vendor selection. It reasons like Nick Kramer`
Replace "It reasons like Nick Kramer" with "It reasons as an evidence-first multi-analyst panel" (keep the rest of the sentence/line intact). Verify the surrounding sentence still reads correctly after the edit.

- [ ] **Step 2: `CLAUDE.md`**

Line 10 old:
```
Nick Kramer (SSA & Company) — a "digital twin" persona encoded as JSON, not hard-coded logic — augmented with HVAC/mechanical field-service domain knowledge. The agent is **advisory**: it augments the human selection committee, shows its work, and is meant to be challenged.
```
Line 10 new:
```
an evidence-first FSM evaluator — a persona encoded as JSON, not hard-coded logic — built as a multi-analyst panel that scores independently and debates to one verdict, augmented with HVAC/mechanical field-service domain knowledge. The agent is **advisory**: it augments the human selection committee, shows its work, and is meant to be challenged.
```
(Read the line in context first; the sentence begins earlier on line 9-10. Preserve the lead-in so grammar holds.)

Line 50 old:
```
    persona.json      Nick Kramer digital twin: decision style, priorities, red flags, voice
```
Line 50 new:
```
    persona.json      The evaluator's character: decision style, priorities, red flags, voice
```

- [ ] **Step 3: `docs/DESIGN.md`**

Reword these so no "Nick" / "digital twin" remains, preserving meaning:
- Intro (~line 6): "built to reason like Nick Kramer (SSA), augmented with" → "built to reason as an evidence-first multi-analyst panel, augmented with".
- §2 heading (~line 34) "The 'character' — how the agent reasons like Nick" → "The 'character' — how the agent reasons".
- Table header (~line 41) "Source (Nick, verbatim)" → "Source (engagement transcripts, verbatim)".
- ~line 60 "(The 'digital twin'.)" → "(The evaluator's character.)".

After editing, run `grep -n "Nick\|digital twin" docs/DESIGN.md` and reword any remaining hit.

- [ ] **Step 4: `docs/DEMO_GUIDE.md`**

Reword these, preserving the explanatory intent (the point is "judgment lives in editable JSON, not code"):
- ~line 10 "scores it the way Nick Kramer would" → "scores it the way a seasoned FSM evaluator would".
- ~line 52 section heading "Why it's 'Nick in a box,' not a rules engine (the digital-twin angle)" → "Why it's a character in editable JSON, not a rules engine".
- ~lines 56-59 "a 'digital twin' of Nick's decision style ... If the committee says 'Nick would never weight financials that lightly,' we open" → "a character capturing an evidence-first decision style ... If the committee says 'this would never weight financials that lightly,' we open" (keep the rest of the sentence about opening the JSON).
- ~line 102 "It reasons in Nick's voice, which is a strength and a bias." → "It reasons in one consistent evaluator voice, which is a strength and a bias."

After editing, run `grep -n "Nick\|digital twin\|digital-twin" docs/DEMO_GUIDE.md` and reword any remaining hit.

- [ ] **Step 5: `docs/CHANGES_SUMMARY.md:9`**

Old (line 9): `Logic FSM platform RFP (all 422 requirements), reasons in Nick Kramer's "digital‑twin"`
New: `Logic FSM platform RFP (all 422 requirements), reasons as an evidence-first multi-analyst panel`
(Adjust the continuation onto the next line so the sentence still flows; read lines 8-11 first.)

- [ ] **Step 6: Verify docs are clean (login docs excepted)**

Run: `grep -rIn "Nick Kramer\|digital twin\|digital-twin\|Nick's\|reasons.*Nick\|as Nick" README.md CLAUDE.md docs/DESIGN.md docs/DEMO_GUIDE.md docs/CHANGES_SUMMARY.md`
Expected: no output (exit 1).

- [ ] **Step 7: Commit**

```bash
git add README.md CLAUDE.md docs/DESIGN.md docs/DEMO_GUIDE.md docs/CHANGES_SUMMARY.md
git commit -m "docs: reframe persona as evidence-first multi-analyst panel

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E5dcoxCZ1QpgfcNZnbQ6h5"
```

---

### Task 4: Frontend — SSA labels + surface the debate

**Files:**
- Modify: `frontend/index.html:813`, `:1083`, `:1204` (category labels), `:1199` (add doctrine line), `:792` (relabel dual block)

**Interfaces:**
- Consumes: `scoring_method_doctrine.summary` from Task 1 (persona object is `p` in the methodology component).

- [ ] **Step 1: Drop "SSA" from the three category labels**

`:813` and `:1083` — change `SSA scorecard categories` to `Scorecard categories` (two occurrences of the string `>SSA scorecard categories<`; update both).
`:1204` — change `Scoring rubric — SSA categories` to `Scoring rubric — categories`.

- [ ] **Step 2: Render the scoring-method doctrine in the persona panel**

After line 1199 (the OpCo-diversity doctrine line), inside the same `<div className="card">` that closes at 1200, add:
```jsx
        <p className="small"><b>How it scores:</b> {p.scoring_method_doctrine.summary}</p>
```

- [ ] **Step 3: Relabel the dual-vote block header**

Line 792 old:
```jsx
          <div className="section-title" style={{marginTop:0}}>Two-model read</div>
```
New:
```jsx
          <div className="section-title" style={{marginTop:0}}>How the panel debated this vendor</div>
```

- [ ] **Step 4: Verify the labels and the new line**

Run: `grep -n "SSA scorecard categories\|SSA categories\|How it scores\|How the panel debated\|Two-model read" frontend/index.html`
Expected: shows `How it scores`, `How the panel debated this vendor`, and `Scoring rubric — categories`; shows NO `SSA scorecard categories`, NO `SSA categories`, and NO `Two-model read`.

- [ ] **Step 5: Sanity-check the JSX parses (no syntax break)**

Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && npx --yes esbuild frontend/index.html --loader=text >/dev/null 2>&1 && echo "ok" || node -e "const s=require('fs').readFileSync('frontend/index.html','utf8'); const o=(s.match(/<div/g)||[]).length, c=(s.match(/<\/div>/g)||[]).length; console.log('open',o,'close',c)"`
Expected: prints `ok`, or balanced-ish div counts if esbuild is unavailable. If counts are wildly off vs. before, re-inspect the edit at 1199.

- [ ] **Step 6: Commit**

```bash
git add frontend/index.html
git commit -m "feat(ui): drop SSA from category labels; surface the analyst debate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E5dcoxCZ1QpgfcNZnbQ6h5"
```

---

### Task 5: Dual-mode example in the offline demo (IFS)

**Files:**
- Modify: `backend/data/sample_results.json` — the `vote` block of the vendor whose `"vendor"` is `"IFS"`.

**Interfaces:**
- Consumes: the `Vote` shape (`backend/agent/schemas.py:103-119`): `mode`, `raw_votes` (each `{provider, model, recommendation, narrative, dissent, top_risks}`), `disagreements` (each `{dimension, openai_position, anthropic_position, resolution}`).
- Consumes: real model ids from `models.json` dual_vote defaults — `gpt-5.5` (openai) and `claude-opus-4-8` (anthropic).

- [ ] **Step 1: Replace IFS's `vote` block with a dual-mode version**

Find the IFS object and replace its `vote` object. Keep `recommendation`, `confidence`, `narrative`, `dissent`, `top_risks`, and `evidence_to_close` exactly as they are now. Change `mode` to `"dual"`, leave `note` as `""`, and fill `raw_votes` and `disagreements`:

```json
  "mode": "dual",
  "note": "",
  "raw_votes": [
    {
      "provider": "openai",
      "model": "gpt-5.5",
      "recommendation": "Recommend",
      "narrative": "[demo] Recommend. IFS is a front-runner on breadth — strong on RLC, CXR, and SCL, passes the Must gate, no architectural flags. The composite (81.1/100 SSA-weighted) holds up. PJE at 3.0/5 is the soft spot, but it's configurable and shouldn't block advancing to demos.",
      "dissent": "The score rewards coverage. If references show shallow Work-to-Cash depth, the headline flatters the platform.",
      "top_risks": ["Project Execution & Financial Control weak at 3.0/5 (weight 15%)."]
    },
    {
      "provider": "anthropic",
      "model": "claude-opus-4-8",
      "recommendation": "Recommend",
      "narrative": "[demo] Recommend, with a caveat. The breadth is real and the gate is clean, so this advances. But PJE 3.0/5 on AIA/WIP/ASC-606 and certified-payroll is a genuine risk for the project-heavy OpCos, and offline mobile adoption is unproven in the response. Recommend on breadth; prove the depth before calling it the winner.",
      "dissent": "A narrower vendor that is deeper on Work-to-Cash and offline mobile could deliver more real value than this composite implies.",
      "top_risks": ["PJE depth on AIA/WIP/ASC-606 unproven for project-heavy OpCos.", "Offline mobile adoption not evidenced in the response."]
    }
  ],
  "disagreements": [
    {
      "dimension": "Project execution depth (PJE)",
      "openai_position": "A manageable, configurable gap that doesn't hold back a Recommend.",
      "anthropic_position": "A real risk for project-heavy OpCos that should temper confidence until proven.",
      "resolution": "Recommend stands. PJE depth (AIA/WIP/ASC-606, certified payroll) is the top item to prove in the Charlotte demo; confidence held High on breadth with PJE flagged."
    }
  ]
```

- [ ] **Step 2: Verify the file parses and IFS is now dual**

Run:
```bash
cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && python3 -c "
import json
d=json.load(open('backend/data/sample_results.json'))
items = d if isinstance(d,list) else d.get('results') or list(d.values())
ifs=[v for v in items if isinstance(v,dict) and v.get('vendor')=='IFS'][0]
vt=ifs['vote']
assert vt['mode']=='dual', vt['mode']
assert len(vt['raw_votes'])==2
assert {r['provider'] for r in vt['raw_votes']}=={'openai','anthropic'}
assert len(vt['disagreements'])==1
print('IFS dual ok; recommendation', vt['recommendation'])
"
```
Expected: `IFS dual ok; recommendation Recommend`

- [ ] **Step 3: Verify it renders in the live server (mock engine, no keys)**

Run: `cd backend && PORT=8000 python3 app.py & sleep 3 && curl -s http://127.0.0.1:8000/api/results | python3 -c "import sys,json; d=json.load(sys.stdin); ifs=[v for v in (d.get('results') or d.values() if isinstance(d,dict) else d) if isinstance(v,dict) and v.get('vendor')=='IFS'][0]; print('mode', ifs['vote']['mode'], '| disagreements', len(ifs['vote']['disagreements']))"; kill %1 2>/dev/null`
Expected: `mode dual | disagreements 1` (adjust the JSON shape access if `/api/results` wraps differently; the point is mode=dual reaches the API).
Note (WSL): if curl can't reach the server, skip this and rely on Step 2 plus the standalone check in Task 6.

- [ ] **Step 4: Commit**

```bash
git add backend/data/sample_results.json
git commit -m "feat(demo): dual-mode debate example for IFS in sample data

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E5dcoxCZ1QpgfcNZnbQ6h5"
```

---

### Task 6: Rebuild the standalone + refresh graphify

**Files:**
- Regenerate: `FSM_Evaluation_Agent_Standalone.html` (via `backend/build_static.py`)
- Update: `graphify-out/` (via `graphify update .`)

**Interfaces:** none.

- [ ] **Step 1: Rebuild the standalone**

Run: `cd backend && python3 build_static.py`
Expected: writes `../FSM_Evaluation_Agent_Standalone.html` with a success message.

- [ ] **Step 2: Verify the new framing and demo debate are baked into the standalone**

Run:
```bash
cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && \
grep -c "multi-analyst panel that debates" FSM_Evaluation_Agent_Standalone.html && \
grep -c "How the panel debated this vendor" FSM_Evaluation_Agent_Standalone.html && \
grep -c "Scoring rubric — categories" FSM_Evaluation_Agent_Standalone.html && \
{ grep -q "digital twin of Nick Kramer" FSM_Evaluation_Agent_Standalone.html && echo "FAIL: old persona still present" || echo "OK: old persona gone"; }
```
Expected: three counts ≥ 1, then `OK: old persona gone`.

- [ ] **Step 3: Refresh the knowledge graph**

Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && graphify update .`
Expected: completes (AST-only).

- [ ] **Step 4: Commit**

```bash
git add FSM_Evaluation_Agent_Standalone.html graphify-out
git commit -m "build: rebuild standalone + refresh graphify for new framing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E5dcoxCZ1QpgfcNZnbQ6h5"
```

---

## Final verification (run after all tasks)

- [ ] **Full scrub grep** (only the login account may remain):
  `grep -rIn "Nick Kramer\|digital twin\|Nick's\|as Nick" backend/ frontend/ README.md CLAUDE.md docs/DESIGN.md docs/DEMO_GUIDE.md docs/CHANGES_SUMMARY.md` → only `auth.py` / tests hits, nothing else.
- [ ] **Auth untouched:** `cd backend/tests && python3 -m unittest -q` → all green (login account intact).
- [ ] **Both JSON files parse:** persona.json and sample_results.json (covered in Tasks 1 & 5).
- [ ] **Manual server pass** (mock, no keys): persona panel shows the new headline + "How it scores" line, the three category labels read without "SSA", and IFS detail shows "How the panel debated this vendor" with two analyst reads and one disagreement.
- [ ] **Standalone pass:** open `FSM_Evaluation_Agent_Standalone.html` directly — same persona text and the IFS dual-mode debate render offline.

## Notes for the implementer

- This plan has no automated test suite; "tests" are the grep/parse/server checks shown inline. Run each before its commit.
- If any "Old:" string doesn't match exactly (whitespace, line drift), re-grep for the distinctive substring to find the current line, then apply the New: text. Do not skip an edit because the line number moved.
- The persona's voice quotes (e.g. "that's a fool's errand") intentionally stay — they are the now-unattributed house voice. Do not remove them.
