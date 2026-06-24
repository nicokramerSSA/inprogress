# 2-Vendor Compare View — Design

**Date:** 2026-06-24
**Roadmap item:** #3 (from `2026-06-23-dual-provider-vote-and-robustness-design.md` §9)
**Status:** Approved, ready for implementation plan

---

## 1. Problem

The selection committee's core question is "Vendor A vs Vendor B." Today the app
answers it indirectly: the Dashboard ranks all vendors in one table, and the
VendorDetail tab shows one vendor at a time. To compare two vendors a committee
member must hold one detail page in their head while opening the other. The
decision-relevant facts — who leads on which capability, whether one vendor is
disqualified, where their requirement coverage diverges — are never placed
directly next to each other.

This builds a **Compare** tab that puts two complete evaluations side by side,
flags every divergence, and leads with a single computed verdict line.

## 2. Goals / non-goals

**Goals**

- A new "Compare" tab: pick Vendor A and Vendor B, see them side by side across
  every scoring dimension the app already produces.
- A **deterministic, computed** one-line takeaway at the top ("who leads and
  why"). No LLM call.
- Divergences are visually obvious and colorblind-safe (arrows + sign, not color
  alone).
- Requirement-level comparison: a computed divergence summary **plus** an
  expandable, filterable 422-row side-by-side diff table.
- Works identically in the live server and the offline standalone HTML.

**Non-goals (this round)**

- **No LLM-generated head-to-head narrative.** The layout is built so a verdict
  panel can slot in later, but the prose read is deferred (it is partially served
  already by each vendor's vote narrative and by the chat assistant). YAGNI until
  there is a pull for it.
- No N-way (3+) comparison. Strictly two vendors.
- No new backend endpoint, no scoring-engine changes, no persistence changes.
- No export of the comparison (that is roadmap item #1, a separate cycle).
- No broad accessibility overhaul (roadmap item #8); this view does its own
  divergence cues right, nothing more.

## 3. Why deterministic / client-side (decision record)

All data needed is already serialized to the browser. `VendorEvaluation.to_dict()`
(see `backend/agent/schemas.py`) is delivered via `/api/results` and seeded into
`window.__BOOT__`, carrying for every vendor: `weighted_total`,
`capability_weighted_total`, `gating`, `categories[]`, `capabilities[]`,
`segment_fit[]`, `agentic_future`, `vote`, `external_research`, and all 422
`requirement_scores[]`.

Therefore the compare view is a **pure presentation layer**: it reshuffles data
the client already holds and computes deltas in JavaScript. Consequences:

- Zero API cost, instant, fully deterministic and auditable — consistent with the
  project ethos ("gating is deterministic and never LLM-overridable," "show your
  work").
- No mock/live divergence: the view behaves the same whether the underlying
  evaluations came from the live engine or the offline mock.
- Works offline in `FSM_Evaluation_Agent_Standalone.html` with no extra wiring,
  because it reads the same in-memory `results` array.

The rejected alternative ("Scan + LLM verdict") would add a backend endpoint, a
mock fallback, a per-compare Opus call, and would reopen the single/dual-provider
model-selection UX on a third surface — for a narrative that the vote tab and
chat assistant already largely provide.

## 4. Data shape (what the view consumes)

Per vendor, from the existing `results` array (no new fields):

| Field | Use |
|---|---|
| `vendor`, `product`, `model_used`, `is_demo`, `evaluated_at` | Picker labels + per-column header (demo badge preserved) |
| `weighted_total` (0–100) | Headline SSA-scorecard lens |
| `capability_weighted_total` (0–100) | Headline RFP §30 lens |
| `gating` `{disqualified, unmet_must_count, unmet_musts[{rid,capability,reason}], architectural_gate_flags, summary}` | Gating section + takeaway |
| `categories[]` `{id, name, weight, raw_1_5, weighted_points, confidence, ...}` | SSA categories section |
| `capabilities[]` `{code, name, weight, score_1_5, n_requirements, n_unmet_must, ...}` | §30 capability section + takeaway |
| `segment_fit[]` `{segment_id, segment_name, fit_1_5, ...}` | Segment-fit section |
| `agentic_future` `{score_1_5, openness_1_5, ai_capability_1_5, data_control_risk, ...}` | Agentic section |
| `vote` `{recommendation, confidence, narrative, ...}` | Vote section |
| `requirement_scores[]` `{rid, domain, capability, priority, met, quality, vendor_code, confidence, ...}` | Requirement divergence summary + diff table |

**Join key:** `rid`. Both vendors are scored against the same
`data/requirements.json`, so requirements line up one-to-one. If a `rid` is
present for one vendor and absent for the other (should not happen with the
current engine, which always scores all 422), render the missing side as "—" and
exclude that row from quality-delta counts.

## 5. Layout (top to bottom)

1. **Vendor pickers.** Two `<select>` controls (Vendor A, Vendor B), populated
   from `results`. Default: the top two vendors by `weighted_total` (A = highest,
   B = second). Guard: if the same vendor is selected for both, auto-shift B to
   the next distinct vendor and show an inline notice ("Pick two different
   vendors").

2. **Computed takeaway banner.** A single deterministic sentence. Priority order
   for what leads the sentence:
   1. **Gating divergence** — if exactly one vendor is disqualified, that leads:
      "{Loser} is disqualified ({n} unmet Must{s})." The other is named as the
      standing option.
   2. **Both disqualified** — say so plainly, then fall through to score
      comparison for "less bad" context.
   3. **Neither disqualified** — name the leader by the two headline lenses with
      margins, plus capability-leadership count.
   - Composed example: *"Aerion leads — higher on both lenses (SSA 78 vs 64, §30
     75 vs 61) and ahead on 6 of 8 capabilities; Brightfield is disqualified
     (1 unmet Must)."*
   - Ties: if headline lenses split (A higher on one, B on the other) or are
     within 1 point, say "evenly matched on headline scores" and rely on the
     capability count + gating to break it.

3. **Headline cards.** Two cards (or one two-column row) showing both lenses with
   a signed delta chip (e.g. `▲ +14` on the leader, neutral `–` on ties).

4. **§30 capability bars.** 8 paired rows. Each row: capability name, A bar +
   `score_1_5`, B bar + `score_1_5`, signed delta, and an "unmet Must" badge per
   side when `n_unmet_must > 0`.

5. **SSA categories.** 6 paired rows: `raw_1_5` (and `weighted_points`
   contribution) for A and B with deltas.

6. **Gating.** Side-by-side status (PASS / DISQUALIFIED). Under each, that side's
   `unmet_musts` listed (rid · capability · reason) and any
   `architectural_gate_flags`.

7. **Segment fit.** 6 OpCo rows: `fit_1_5` A vs B, marking which vendor fits each
   archetype better (arrow toward the better side).

8. **Agentic future.** Side by side: `score_1_5`, `openness_1_5`,
   `ai_capability_1_5`, `data_control_risk`.

9. **Vote.** `recommendation` + `confidence` side by side; each narrative behind a
   collapsible (show/hide) so the section stays scannable.

10. **Requirement divergence.**
    - **Computed summary:** Musts met by A-only and by B-only; counts of
      A-higher-quality / tie / B-higher-quality; top 5 requirements by absolute
      quality delta (RID + the two scores).
    - **Diff table (expandable):** 422 rows, columns `RID · domain · priority ·
      A · B · Δ`. Filters: "only where they differ" (toggle) and by priority
      (Must / Should / Could / Won't / All). Collapsed by default to keep the
      page light.

## 6. Deterministic definitions (stated for auditability)

- **"Meets a Must"** = `priority == "Must"` AND `met == "Yes"`. `Partial` does not
  count as met — consistent with how gating computes unmet Musts.
- **Quality delta** uses the `quality` field (1–5). Rows where either side is
  `quality == 0` / `met == "N/A"` are excluded from the higher/tie/lower quality
  counts (no meaningful quality to compare), but still appear in the diff table
  with "—".
- **Capability leadership count** = number of the 8 capabilities where
  `A.score_1_5 > B.score_1_5` (and vice versa); equal within a small epsilon
  (0.05) counts as a tie.
- **Headline "lead"** = strictly greater `weighted_total`; "within 1 point" is
  treated as a tie for the takeaway wording.

## 7. Visual / divergence cues

- Deltas shown as a signed number with a direction arrow (`▲ +14`, `▼ -3`,
  `– 0`). Color is a secondary cue only; the arrow + sign carries the meaning so
  the view is readable without color (colorblind-safe).
- Leader side of each row gets a subtle emphasis; ties get neutral styling.
- Reuse existing CSS tokens / table and `rowbar` styles already in
  `frontend/index.html` so the tab matches the rest of the app.

## 8. Components & files

- **`frontend/index.html`** (primary change):
  - New `Compare` React component (pickers + all sections + diff table + computed
    helpers for deltas/summary/takeaway).
  - New entry in the nav tab array and a `tab === "compare"` render branch in the
    App component, passing the existing `results` prop. No other component
    changes.
- **`FSM_Evaluation_Agent_Standalone.html`**: regenerated via
  `backend/build_static.py` so the offline demo includes the tab.
- **No backend files change.** (`/api/results` and `window.__BOOT__` already
  carry everything.)

## 9. Error handling & edge cases

- **Fewer than two evaluations available** → empty state: "Need at least two
  evaluated vendors to compare." (Pickers hidden or disabled.)
- **Same vendor in both pickers** → auto-shift B + inline notice (see §5.1).
- **Null sub-objects** (e.g. a `vote`, `agentic_future`, or `gating` is null on a
  partial/legacy result) → guarded render; that section shows "—" rather than
  throwing. A single bad field must not blank the React tree.
- **Demo results** → preserve the existing "demo" badge per column so a
  mock-engine evaluation is never mistaken for a live one.
- The view is read-only; it never mutates `results`.

## 10. Testing / verification

No automated test suite (project convention — verification is manual). Verify:

1. **Offline standalone** (`FSM_Evaluation_Agent_Standalone.html`) renders the new
   tab; headless Chrome screenshot confirms no blank page (Babel parse clean).
2. **Live server** (`python app.py`, mock engine): pickers populate, default to
   top two, same-vendor guard fires.
3. **Takeaway logic across cases:** one disqualified, both disqualified, neither
   (clear leader), and a near-tie — confirm the sentence is correct each time.
4. **Capability / category / segment / agentic / vote** sections show correct
   values and deltas for a known pair (cross-check against each vendor's detail
   tab).
5. **Requirement divergence:** summary counts reconcile with the diff table;
   "only where they differ" filter and priority filter work; 422 rows present
   when unfiltered.
6. **Empty state** with fewer than two results.

## 11. Risk & rollback

- Purely additive and client-side: a new component + two render hooks. No backend,
  scoring, schema, or persistence changes. Rollback = revert
  `frontend/index.html` (and rebuild the standalone). Existing tabs and cached
  results are untouched.
- Stacked on `feature/dual-provider-vote` (open PR #36) because both edit
  `frontend/index.html`; building on the current tip avoids merge conflicts. If
  #36 changes materially, rebase this branch onto the updated tip.

## 12. Verdict-panel readiness (future hook, not built)

Reserve a slot directly under the takeaway banner for a future LLM head-to-head
verdict. When/if built, it would call a new `/api/compare` endpoint (with a mock
fallback, mirroring the vote), render Nick-voice prose, and leave every
deterministic section in this spec untouched. Nothing in this round depends on it.
