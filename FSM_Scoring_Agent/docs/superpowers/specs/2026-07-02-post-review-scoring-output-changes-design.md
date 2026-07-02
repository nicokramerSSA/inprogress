# Design: Post-Review Scoring & Output Changes

**Date:** 2026-07-02
**Status:** Approved (brainstorming) — pending implementation plan
**Author:** Camp Hagood + Claude Code
**Source:** Review meeting 2026-07-02 (Camp Hagood, Jeff Brown, Nick Kramer), Krisp
transcript `019f2430df8b73bd91ce131109c8ef92`.

## Problem

The first live evaluations surfaced four changes the committee wants before the next
vendor (ServiceMax) is scored:

1. **CUSTOM disqualifies when it should not.** A `Must` requirement answered `CUSTOM`
   (delivered via custom development) is being treated as a disqualifying gap. The
   committee agreed CUSTOM *meets* the requirement — the capability is delivered — but
   heavy reliance on custom work is a **risk**, not a disqualification. `GAP` and
   `ROADMAP` on a Must remain disqualifying.
2. **Customization is not surfaced as a risk.** When a vendor meets Musts largely through
   custom development, that is "hard to evolve on" and must appear in the vendor's risk
   list.
3. **No clean disqualification report.** The committee needs a requirement-level,
   **commentary-free** report stating exactly why a vendor is disqualified — suitable to
   send to a vendor as documentation without biasing them with narrative.
4. **"SSA" leaks into vendor-facing output.** The dashboard shows "SSA weighted score"
   and "SSA total"; comparison and report views carry "SSA"-prefixed labels. A vendor
   reading these could infer SSA dictated the methodology. Strip SSA from vendor-facing
   scoring labels and generated report content.

### Root-cause finding for #1

The deterministic gate already passes CUSTOM: `_WEAK_CODES_FOR_MUST = {"ROADMAP", "GAP"}`
(`scoring.py:63`), and `_compute_gating` (`scoring.py:581`) only disqualifies a Must when
`met == "No"` or the code is a weak code with `met != "Yes"`. CUSTOM maps to
`("Partial", 2)` and is **not** a weak code, so it passes gating today.

The disqualification is driven by **config text fed to the scoring model**:
`scorecard.json` `moscow.Must` and `gating_rules.description` tell the model a Must
answered "CUSTOM without firm SOW" is "effectively unmet." The live model obeys this and
marks such requirements `met == "No"`, which then trips the deterministic `met == "No"`
gate. The fix is therefore primarily a **knowledge-base text change**, consistent with
the project convention that behavior lives in editable JSON, not hard-coded logic.

## Goals

- A `Must` answered `CUSTOM` does not disqualify a vendor; it scores Partial and is
  flagged as a customization risk. `GAP`/`ROADMAP` on a Must still disqualify.
- Vendors relying on custom development for Musts carry an explicit, ranked risk.
- A per-vendor, requirement-level, commentary-free disqualification report is available
  on demand and printable to PDF.
- No vendor-facing scoring label or generated report content references "SSA."
- Both the live-model path and the offline "mock" engine reflect the CUSTOM change.

## Non-goals (YAGNI)

- The "seven non-negotiables" second qualification layer. The committee agreed the list
  is no longer valid and that single-tenant/security is already a hard architectural
  gate. Out of scope.
- The segmentation workbook / revenue-by-business-line analysis — a separate workstream,
  not this web app.
- Server-side PDF generation (reportlab/weasyprint). Rejected: adds a dependency and
  breaks the offline standalone build.
- Removing SSA from the app's own login/chrome branding (logo, title, "Prepared by SSA &
  Company" app footer) or from internal code comments. The target is what a *vendor* sees
  in scores and reports, not the tool's identity to the internal committee.

## Components

### §1 CUSTOM meets the Must — knowledge change

**Files:** `backend/config/scorecard.json`; audit `backend/config/persona.json` and
`backend/agent/knowledge.py` prompt builders.

- `moscow.Must`: rewrite to state that **No, GAP, or ROADMAP** on a Must is a basis for
  disqualification, and that **CUSTOM meets a Must** (the capability is delivered via
  custom development), scoring Partial, with heavy custom reliance flagged as a risk.
- `gating_rules.custom_must_needs_firm_sow`: `true → false`.
- `gating_rules.description`: rewrite to: any Must marked No, GAP, or ROADMAP →
  disqualifying; a Must answered CUSTOM meets the requirement and does not disqualify,
  though it is surfaced as a customization risk; single-tenant deployment and
  union/non-union data isolation remain hard architectural gates.
- Sweep `persona.json` and `knowledge.py` for any text instructing the model to treat
  CUSTOM as unmet/disqualifying and align it with the above.
- **No change to `_compute_gating`** — it already passes CUSTOM and disqualifies
  GAP/ROADMAP. The mock/matrix verdict for CUSTOM (`("Partial", 2)`) is already correct
  and unchanged.

### §2 Customization as a top risk — deterministic

**File:** `backend/agent/vote.py` (`synthesize_vote`, risk block ~L97-109).

- Read `ev.requirement_scores` (already on `VendorEvaluation`). Count Musts with
  `vendor_code == "CUSTOM"`.
- When the count ≥ 1, append a risk line:
  `"Heavy customization: <N> Must requirement(s) met only via custom development —
  costly to maintain and evolve."`
- **Ranking:** the customization risk is treated as *material* (surfaced high, before the
  `risks[:5]` truncation could drop it) when `N >= 3`; below 3 it is still appended but
  ranked after the existing capability/segment/data-control risks.
- Guard: if `ev.requirement_scores` is empty, skip silently (no crash).

### §3 Disqualification report — client-side, print-to-PDF

**Files:** `frontend/index.html` (new report builder + button); rebuild
`FSM_Evaluation_Agent_Standalone.html`.

- A **"Disqualification Report"** action appears **only** for a disqualified vendor
  (`gating.disqualified === true`); hidden otherwise.
- Data source: the vendor's `requirement_scores`, already present client-side (serialized
  via `VendorEvaluation.to_dict()`). No backend change.
- Filter mirrors the gate exactly: include a row when `priority === "Must"` **and**
  (`met === "No"` **or** `vendor_code` is `"GAP"` or `"ROADMAP"`). Append any
  `gating.architectural_gate_flags` as additional rows/notes.
- Table columns (via existing `tableHTML`): **RID · Requirement · Priority · Response ·
  Reason**. The `Reason` is the factual failing reason (e.g. "Must requirement not met
  (GAP)") — **no** rationale/narrative/commentary column.
- Rendered through a **commentary-free** variant of `brandedDoc`:
  - Header: `"Disqualification Report — <Vendor>"`, generation date.
  - One factual statement line: `"Disqualified under RFP §8: <N> unmet Must
    requirement(s)."`
  - Neutral footer (generation date + factual descriptor); **no** advisory/analyst
    commentary and **no** SSA methodology attribution.
- Mechanism: open the print window with the built HTML (serves as the on-screen preview),
  browser print → save as PDF. Same pattern as the existing report export; zero new
  dependencies; works in the offline standalone build.

### §4 SSA stripped from vendor-facing output

**Files:** `frontend/index.html` (labels at ~L382, L421, L450, L456, L689, L745, L1052;
report footer ~L504); reconcile with the `feature/evaluator-depersonalization` branch.

Rename vendor-facing methodology labels to neutral equivalents:

| Current | New |
|---------|-----|
| "SSA score (0-100)" | "Weighted score (0-100)" |
| dashboard "SSA total" | "Total" |
| "/100 SSA weighted" | "/100 weighted" |
| "SSA weighted total" | "Weighted total" |
| "SSA category" | "Category" |
| comparison lens `SSA {..}` prefix | "Weighted {..}" |

Strip SSA methodology attribution from generated report content (the `brandedDoc`
footer's "Advisory evaluation" line is acceptable as neutral copy but must not attribute
the *methodology* to SSA). **Kept as-is:** login/app-chrome branding (logo, `<title>`,
app footer identity) and internal code comments. During planning, diff against
`feature/evaluator-depersonalization` (which already began dropping SSA from category
labels) so the renames do not collide — whichever branch merges first wins and the other
rebases onto it.

## Data flow

```
① scorecard.json / persona text  ──► scoring model no longer marks CUSTOM Musts "No"
                                       (deterministic gate already passes CUSTOM)
② evaluate_vendor ──► ev.requirement_scores ──► synthesize_vote counts CUSTOM Musts
                                                 ──► top_risks gains a customization line
③ ev.requirement_scores (already serialized) ──► frontend filter (Must + No/GAP/ROADMAP)
                                                 ──► brandedDoc (commentary-free) ──► print/PDF
④ frontend label rename (vendor-facing only) ──► standalone rebuild
```

## Error handling

- §1 is text-only; it cannot crash. GAP/ROADMAP gating is unchanged.
- §2 guards on empty `requirement_scores`; the risk is additive and never blocks a vote.
- §3 shows the button only for disqualified vendors; a vendor with no qualifying rows
  still produces a valid (empty-body) report rather than erroring. Pure client-side; no
  server round-trip.
- §4 is a label rename; no behavioral change.

## Testing

- **§1 (backend):** a Must scored `CUSTOM` (mock engine and matrix path) → evaluation is
  **not** disqualified; a Must scored `GAP` and a Must scored `ROADMAP` → **disqualified**.
- **§2 (backend):** a vendor with `N ≥ 1` CUSTOM Musts → `vote.top_risks` contains the
  customization line with the correct count; `N = 0` → the line is absent. `N ≥ 3` → the
  line survives the `top_risks[:5]` truncation.
- **§3 / §4 (manual — no JS test harness, per project convention):** rebuild the
  standalone, open a disqualified vendor's report and confirm columns, zero commentary,
  and clean print output; grep-confirm no vendor-facing "SSA" strings remain; visual pass
  on the dashboard and comparison views.
- **Post-§1:** vendors must be **re-scored** to reflect the new gating (matches the plan
  to re-score ServiceTitan; it should still disqualify, on real GAP/ROADMAP grounds).

## Success criteria

- A Must answered CUSTOM no longer disqualifies; GAP/ROADMAP still do.
- Vendors relying on custom development for Musts carry an explicit ranked risk.
- A disqualified vendor produces a clean, commentary-free, requirement-level PDF report.
- No vendor-facing scoring label or generated report references "SSA."
- The offline standalone build reflects §3 and §4 and still runs with no network/keys.

## Files touched

- `backend/config/scorecard.json` — moscow / gating_rules text (§1).
- `backend/config/persona.json`, `backend/agent/knowledge.py` — CUSTOM-language audit (§1).
- `backend/agent/vote.py` — customization risk in `synthesize_vote` (§2).
- `frontend/index.html` — DQ report builder + button (§3); vendor-facing SSA label
  renames (§4).
- `FSM_Evaluation_Agent_Standalone.html` — rebuild after §3/§4 (`python3 build_static.py`).
- `backend/tests/` — new tests for §1 gating and §2 risk.
