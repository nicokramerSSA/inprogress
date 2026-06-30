# Design: De-personalize the evaluator and foreground the debate

**Date:** 2026-06-30
**Branch:** `feature/evaluator-depersonalization`
**Status:** Spec — awaiting review

## Why

Feedback from the named individual the agent is currently modeled on. Three asks:

1. Take the reference to him being the baseline out.
2. Take the SSA reference out of the category list.
3. Add the multiple-scoring / debate concept instead of naming him.

The agent today headlines itself as "a digital twin of Nick Kramer (SSA & Company)."
That framing is what he wants removed. The work is a repositioning of how the agent
describes itself plus a small UI change to make an existing mechanism visible. The
scoring engine, gating, rollups, and the knowledge base's actual reasoning content do
not change — only the attribution and the framing.

## Decisions locked with the requester

- **Debate:** reframe the description *and* surface the existing two-analyst debate in the UI.
- **Name removal:** scrub "Nick Kramer" from active code and docs (deep, not display-only).
- **New identity:** combined framing — an evidence-first FSM evaluator built as a
  multi-analyst panel that debates to a verdict, with HVAC field-service depth.
- **SSA removal:** category-list labels only (not a broader SSA de-brand).
- **Offline demo:** hand-author a dual-mode vote for one sample vendor so the debate is
  visible offline and in the standalone build.
- **Headline wording:** use the proposed wording as written below.

## Critical distinction — two unrelated "Nick Kramer"s

There are two completely separate occurrences of the name. Only one is in scope.

- **In scope — the persona baseline:** `persona.json`, the reconciliation prompt string,
  code comments, and the docs. These get scrubbed.
- **Out of scope — his login account:** `backend/auth.py:33`
  (`nkramer@ssaandco.com`, "Nick Kramer", "SSA"), the auth tests
  (`test_auth.py`, `test_auth_api.py`), and `docs/LOGIN_INFO.md`. This is a *user*, not
  the persona. Touching it breaks his login. **Leave it untouched.**
- **Out of scope — frozen history:** `docs/superpowers/specs/*` and
  `docs/superpowers/plans/*` are dated design records of past work. Their "Nick,IFS,82"
  lines are sample CSV evaluator names, unrelated to the persona. Leave them.

"Service Logic" stays everywhere — it is the client running the RFP, not the persona and
not SSA.

## Changes

### 1. New identity — `backend/config/persona.json`

| Field | New value |
|---|---|
| `id` | `fsm_evaluator_panel_v1` |
| `display_name` | The Evaluator — an evidence-first FSM evaluation agent, built as a multi-analyst panel that debates to a single verdict, with deep HVAC/mechanical field-service domain experience |
| `one_line` | Independent analysts score every requirement against the evidence, then reconcile their reads into one verdict — carrying 25+ years of hands-on HVAC/mechanical FSM implementation scar tissue. |
| `provenance` | Decision DNA mined from Service Logic engagement transcripts (Apr–Jun 2026) and the RFP Internal Memo / Vendor Scorecard, augmented with HVAC/mechanical field-service domain depth. |

The `decision_style`, `priorities_ranked`, `red_flags`, `weighting_doctrine`,
`agentic_future_doctrine`, `opco_diversity_doctrine`, `process_lessons`, and `voice`
sections stay as written. They contain no literal "Nick Kramer" string and they are the
agent's actual reasoning DNA. They become unattributed, not deleted, so behavior and
output quality are unchanged.

New field for the debate framing (see change 4), rendered in the persona panel:

```json
"scoring_method_doctrine": {
  "summary": "Two independent AI analysts score every requirement against the evidence, then a reconciliation pass debates their reads into one verdict and surfaces where they disagreed. The result is a panel decision, not a single model's opinion."
}
```

### 2. Scrub the name from active code and docs

Reword, do not just delete — keep each sentence meaningful.

- `backend/agent/vote.py:194` — prompt string "Reconcile their votes into ONE final vote
  in Nick Kramer's voice" → "...into ONE final vote in the panel's reconciled voice".
  This is the only *runtime* string that injects the name into a model call. (The persona
  system prompt pulls the name from `display_name`, which change 1 already fixes.)
- Code comments, reword off the name: `vote.py:9`, `schemas.py:107`
  (`# in Nick's voice`), `knowledge.py:66` (`reasons "as Nick"`), `scoring.py:26`
  (`Nick's "weight by decision leverage"`), `backend/agent/__init__.py:2`
  (`'digital twin' of Nick Kramer`).
- Docs, reframe "reasons like Nick Kramer / digital twin" as the evidence-first
  multi-analyst panel: `README.md:4`, `CLAUDE.md:10` and `:50`, `docs/DESIGN.md`
  (intro line 6, the §2 heading "how the agent reasons like Nick", the "Source (Nick,
  verbatim)" table header at ~41, and ~60), `docs/DEMO_GUIDE.md` (line 10 and the whole
  "Why it's 'Nick in a box'" section at ~52–59, plus ~102), `docs/CHANGES_SUMMARY.md:9`.

Acceptance: `grep -rIn "Nick Kramer\|digital twin\|Nick's\|as Nick" backend/ README.md
CLAUDE.md docs/DESIGN.md docs/DEMO_GUIDE.md docs/CHANGES_SUMMARY.md` returns nothing,
**except** `auth.py`, the auth tests, and `LOGIN_INFO.md` (the login account).

### 3. SSA out of the category labels — `frontend/index.html`

- `:813` and `:1083` — "SSA scorecard categories" → "Scorecard categories"
- `:1204` — "Scoring rubric — SSA categories" → "Scoring rubric — categories"

The report footer "SSA & Company" (`:504`) and the internal note in `scorecard.json`
stay — category-labels-only scope.

### 4. Surface the debate in the UI — `frontend/index.html`

The debate already renders in vendor detail at `:788–805` (dissent, both analyst votes
with their models and dissents, and a disagreements list with
dimension / openai_position / anthropic_position / resolution). It only appears when the
vote `mode === "dual"`, which needs both API keys and the dual selector. Two small changes:

- Render the new `scoring_method_doctrine.summary` in the "who it is" panel (around
  `:1199`), next to the other doctrine lines, labeled e.g. **"How it scores:"**.
- Relabel the existing dual-vote block header (around `:791–793`) to
  **"How the panel debated this vendor"** so the section reads as the debate rather than
  a generic two-model dump.

No change to the default vote mode (still single — dual costs 3× the calls and needs
keys). No change to the detail rendering logic itself.

### 5. Dual-mode example in the offline demo — `backend/data/sample_results.json`

Pick one sample vendor (the top recommendation reads best for a demo) and replace its
single-mode `vote` block with a dual-mode one matching the `Vote` dataclass
(`schemas.py:103–119`):

```json
"vote": {
  "recommendation": "<unchanged>",
  "confidence": "<unchanged>",
  "narrative": "<unchanged or lightly edited reconciled narrative>",
  "dissent": "<unchanged>",
  "top_risks": [ ... unchanged ... ],
  "evidence_to_close": [ ... unchanged ... ],
  "mode": "dual",
  "note": "",
  "raw_votes": [
    {"provider": "openai", "model": "gpt-4o", "recommendation": "...",
     "narrative": "...", "dissent": "...", "top_risks": [ ... ]},
    {"provider": "anthropic", "model": "claude-sonnet-5", "recommendation": "...",
     "narrative": "...", "dissent": "...", "top_risks": [ ... ]}
  ],
  "disagreements": [
    {"dimension": "...", "openai_position": "...", "anthropic_position": "...",
     "resolution": "..."}
  ]
}
```

Content must be consistent with that vendor's existing scores and the persona voice
(no name attribution, house style from `persona.json` `voice`). The two analyst reads
should genuinely differ on at least one dimension so the disagreements list is real, not
decorative. Keep the demo label honest — these remain `[demo]` synthetic numbers.

### 6. Rebuild the standalone

After the frontend and sample-data changes, rebuild the single-file demo:
`cd backend && python3 build_static.py` → writes
`../FSM_Evaluation_Agent_Standalone.html`. Then `graphify update .`.

## Out of scope

- Changing the scoring engine, gating, rollups, or capability lens.
- Changing the default vote mode or adding scoring passes (debate is surfaced, not expanded).
- Broader SSA de-branding (footer, scorecard note, logos).
- The Nick Kramer login account and auth.
- Per-user data partitioning (still a shared result store).

## Verification

No test suite exists; verification is manual plus targeted greps.

1. `python3 -c "import json; json.load(open('backend/config/persona.json'))"` and the same
   for `sample_results.json` — both parse.
2. The scrub grep in change 2 returns only the allowed auth/login hits.
3. Run the server (`python3 app.py`, mock engine, no keys), open the persona panel:
   new headline, no "Nick Kramer", the "How it scores" debate line present.
4. Category labels read "Scorecard categories" / "Scoring rubric — categories"; no "SSA"
   in those three spots.
5. Open the chosen demo vendor's detail: the "How the panel debated this vendor" block
   shows two analyst reads and a real disagreement, with no keys set.
6. Re-run the existing auth tests (`python3 -m unittest` in `backend/tests`) — still green
   (confirms the login account was not disturbed).
7. Open the rebuilt `FSM_Evaluation_Agent_Standalone.html` directly — same persona text
   and the dual-mode debate render offline.
