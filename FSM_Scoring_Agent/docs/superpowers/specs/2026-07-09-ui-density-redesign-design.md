# Design: Reshaping the Vendor Detail & Methodology pages for readability

**Date:** 2026-07-09
**Status:** Approved for planning
**Scope:** Frontend layout/formatting only (`frontend/index.html` + standalone rebuild)

## Problem

Two pages of the FSM RFP Evaluation Agent carry genuinely useful insight but read as
walls of text:

- **Vendor detail** — the agent's vote is rendered as a single ~400-word paragraph
  (`<p>{r.vote.narrative}</p>`), followed by four parallel scoring deep-dives (Scorecard
  categories, RFP §30 capabilities, OpCo-segment fit, Agentic-future + External research)
  and a 422-row requirement table, all on one endless scroll.
- **Methodology & rubric** — four stacked doctrine paragraphs ("who it is") plus six OpCo
  archetype cards with long "Needs" lists.

The density hurts both the live-demo read (too much on screen) and self-serve scanning.

## Approach

**Formatting/layout only — progressive disclosure.** Keep a clean top-line always visible;
push depth behind expand/collapse and tabs. Do **not** change the LLM output schema, the
stored curated narrative text, or the curated committee numbers.

### Governing constraints

- **SSA brand preserved** — navy/teal header, logo, Avenir font stack, existing `.card`
  and badge system all stay.
- **Typography changes are app-wide.** Any adjustment to the type scale is made through
  `:root` tokens and therefore applies across all seven tabs, so the look and feel stays
  uniform. No page gets a bespoke font size.
- **Reversible** — additive CSS plus one small reusable disclosure component; no rewrite
  of the render tree.
- **Standalone parity** — `FSM_Evaluation_Agent_Standalone.html` is rebuilt via
  `python3 build_static.py` and must still run offline.
- **Curated results are byte-identical** after the change (they are git-authoritative,
  `curated:true`).

## Components

### 1. Shared foundations (built once, reused everywhere)

1. **Type/rhythm tokens in `:root`.** Add an explicit scale — e.g. `--fs-body`,
   `--fs-lead`, `--fs-label`, `--lh-prose`, and a reading-measure `--measure` (~68ch).
   Every prose block on both pages consumes these. Because they live in `:root`, the
   scale is uniform across the whole app (all eight tabs).
2. **A reusable `Disclosure` component** — a labeled expand/collapse: clean summary when
   closed, full content when open. Reused for the vote reasoning, the doctrine paragraphs,
   the OpCo card "Needs" lists, and the 422 table. One interaction pattern the reader
   learns once.
3. **Consistent section rhythm** — reuse existing `.section-title` / `.card`, standardize
   vertical spacing so sections breathe.

### 2. Vendor detail page

1. **Vote blob → lead + expand.**
   - Always-visible top strip: verdict badge (`r.vote.recommendation`, existing) +
     confidence + a one-line "bottom line" derived from existing fields (decision score,
     gate status). No new stored text — synthesized in the client from values already
     present.
   - First 2–3 sentences of `vote.narrative` shown; **"Read full reasoning"** expands the
     remainder in a `--measure`-width column.
   - **Top risks** and **evidence to close** keep their existing two-column list layout.
   - **Dissent** moves behind its own `Disclosure` (least-scanned, most verbose).
2. **Scoring deep-dives → tabs.**
   - Compact scores overview stays pinned on top (existing 61.4 / 55.1 / verdict / gate
     tiles).
   - The four parallel deep-dives move into a **tab strip** (chosen over accordion for a
     cleaner live-demo read — one panel on screen at a time): `Scorecard categories` |
     `RFP §30 capabilities` | `OpCo-segment fit` | `Agentic future & research`.
   - Default open tab: **Scorecard categories**.
3. **422 requirement table → collapsed, gaps-first.**
   - Default: a short **"What to close"** list built client-side from rows that matter
     (unmet Must, GAP/ROADMAP code, or quality ≤ 2).
   - **"Show all 422"** expands the existing filterable `.requirement-table` grid,
     unchanged.
   - CSV export stays visible in both states.

### 3. Methodology & rubric page

1. **Doctrine → identity card.** One-line "who it is" headline + the four doctrines
   (Weighting, Agentic-future, OpCo-diversity, How it scores) as **labeled one-liners**;
   full paragraphs behind a single "Full methodology" `Disclosure`.
2. **Rubric-weight + §30 capability tables** — unchanged (already clean and scannable).
3. **OpCo archetype cards → tightened.** Each card: headline + vendor examples + a compact
   **Strongest / Watch** line; the long "Needs" list collapses behind expand-on-click.

## What does NOT change

Curated scores, stored `vote.narrative` / `vote.dissent` text, gating logic, the two-lens
scoring model, API routes, auth, requirement data. Only the layout of existing values.

## Data flow

No backend change. All new behavior is client-side in `frontend/index.html`:

- The "bottom line" strip and the "What to close" list are **derived** from fields already
  present on `r` (`vote`, `gating`, `requirement_scores`). No new API fields, no
  recomputation of scores.
- Tabs and disclosures are local React state; no persistence.

## Error / edge handling

- If `vote.narrative` is short (≤ 3 sentences), show it fully with no "Read full reasoning"
  affordance (nothing to expand).
- If a vendor has zero qualifying "what to close" rows, the gaps-first list shows a
  positive empty state ("No unmet Musts or GAPs") rather than an empty box.
- Tabs degrade to stacked sections if JS state fails (the underlying sections still render).
- Long OpCo "Needs" lists that are already short stay inline without a redundant expander.

## Verification

- Offline mock engine still works (no keys, no network).
- `python3 build_static.py` rebuilds the standalone file; it opens and runs offline.
- **Visual pass across ALL eight tabs** (Dashboard, Vendor detail, Compare, Batch evaluate,
  Methodology & rubric, Ask the agent, Committee scores, Account) — because the `:root`
  type tokens touch every page, not only the two being restructured.
- Confirm curated numbers (IFS 61.4 / 55.1, etc.) are byte-identical to today.
- Confirm expand/collapse and tab switching work; confirm CSV export still fires.

## Out of scope (explicitly deferred)

- Changing the LLM output schema to emit structured verdict fields.
- Re-generating or re-curating any vendor's stored narrative.
- Mobile-specific layout (desktop-first; app is used on laptops in the committee setting).
