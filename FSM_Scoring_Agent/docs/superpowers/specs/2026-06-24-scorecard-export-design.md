# Scorecard Export — Design

**Date:** 2026-06-24
**Status:** Approved (brainstorming), pending implementation plan
**Roadmap item:** #1 — "Export — PDF / PPTX / CSV of a vendor scorecard + vote (committee handoff)"
(from `2026-06-23-dual-provider-vote-and-robustness-design.md` §9). The 2-vendor compare
spec explicitly deferred its export to this cycle.

---

## 1. Problem

The selection committee can read the agent's evaluations in the app, but cannot take them
out of it. To run a real committee meeting they need artifacts they can drop into a
deck, a spreadsheet, or a packet: a ranked summary across vendors, a head-to-head
comparison, and the auditable per-requirement detail. Today there is no way to get any of
that out of the browser.

## 2. Scope (decided)

In, this cycle:

- **CSV** — three exports:
  - **All-vendor ranking** (the Dashboard's head-to-head ranking).
  - **Head-to-head compare** (the 2-vendor Compare diff).
  - **Per-vendor requirements** — the 422 requirement scores (the audit backbone).
- **PDF** — two committee-brief artifacts, **client-side print-to-PDF**, **SSA-branded**:
  - **All-vendor ranking brief**.
  - **Head-to-head compare brief**.

Out, this cycle (explicit YAGNI):

- **PPTX.** Roadmap mentions it; not requested this cycle. The existing `outputs/*.pptx`
  is a separate one-off artifact, untouched.
- **Single-vendor PDF brief.** The per-vendor artifact this cycle is the 422-row CSV.
  (A per-vendor PDF can be a later cycle if the committee wants it.)
- **weasyprint / server-side PDF.** Rejected — heavy system deps (cairo/pango), awkward on
  Render, against the project's light-deps ethos.
- Any backend runtime change, new endpoint, or new Python dependency.

## 3. Key constraints (why the design is what it is)

- **The offline standalone file must keep working.** `FSM_Evaluation_Agent_Standalone.html`
  runs from `file://` with no server. Every export must work there too. → all exports are
  **client-side**; nothing fetches from the network at export time.
- **The offline mock engine must stay untouched.** No export path touches scoring/vote.
- **No new dependency, no new endpoint.** The data is already fully in the browser
  (`window.__BOOT__` seed + `/api/results`). → zero backend runtime change.
- **API keys never touched.** Export is pure presentation of already-computed results.
- **Honest by construction.** Evidence that is `(unlocated)` or empty is exported as-is;
  the export never fabricates a page/quote (consistent with evidence-drill-down, PR #39).

## 4. Architecture

One new self-contained helper object, `exports`, in `frontend/index.html`, plus contextual
buttons on three existing tabs. No backend runtime change. One build-script asset addition.

```
Dashboard tab ──"Export ranking (CSV / PDF)"──┐
Compare tab  ──"Export comparison (CSV / PDF)"─┼─▶ exports.* (pure builders)
Vendor detail──"Export requirements (CSV)"────┘        │
                                                        ├─ toCSV(rows, headers) → string
                                                        ├─ downloadBlob(name,mime,text)  [DOM side-effect]
                                                        └─ printDoc(title, bodyHTML)      [new window + print]
```

### 4.1 The `exports` helper (pure functions + two side-effects)

- `toCSV(rows, headers)` → RFC-4180 CSV string. `headers` is an ordered list of
  `{key, label}`. Fields containing comma, double-quote, CR or LF are wrapped in double
  quotes with `"` doubled to `""`. Line terminator `\r\n`. UTF-8. A leading column-label
  row. Pure; unit-testable without a DOM.
- `downloadBlob(filename, mime, text)` → the one file side-effect. `new Blob([text],{type})`
  → `URL.createObjectURL` → a synthetic `<a download=filename>` appended, clicked, removed
  → `URL.revokeObjectURL`. Works on `file://` and `http://`.
- `printDoc(title, bodyHTML)` → opens `window.open("","_blank")`, writes a **self-contained**
  HTML document (doctype + inlined `<style>` + branded header/footer + `bodyHTML`), waits
  for load, calls `print()`. The new window is fully decoupled from the SPA's DOM and CSS,
  so app layout/scroll/print-media rules never interfere. On popup-blocked (`window.open`
  returns null), falls back to the hidden-container print path (§6.3).

### 4.2 Builder functions (data → rows/HTML)

Each builder reads from the already-loaded results array (the same objects the tabs
render). No new data fetch.

- `rankingExport(results)` → `{csvRows, csvHeaders, pdfBodyHTML}` for the all-vendor scope.
- `compareExport(a, b)` → `{csvRows, csvHeaders, pdfBodyHTML}` for the two selected vendors.
- `requirementsExport(vendorEval)` → `{csvRows, csvHeaders}` (CSV only) for one vendor.

Builders are pure: same input → same output, so output is deterministic and testable.

### 4.3 The one build-script touch

`build_static.py` currently embeds only the **white** long logo into `BOOT.logo` (for the
app's dark header). The PDF prints on **white paper** and needs the **color** long logo.
Add `BOOT.logo_dark` from `frontend/ssa_logo_long_b64.txt` so SSA branding works in the
standalone build too. On the server path the print function fetches `/ssa_logo_long_b64.txt`
on demand (it is already a served static asset). This is a build-time/asset change, not a
backend runtime change.

## 5. CSV column specifications

Filenames are deterministic and dated: `fsm-ranking-YYYY-MM-DD.csv`,
`fsm-compare-<A>-vs-<B>-YYYY-MM-DD.csv`, `fsm-requirements-<vendor>-YYYY-MM-DD.csv`
(vendor slugged: lowercased, non-alphanumerics → `-`).

### 5.1 All-vendor ranking (Dashboard)

One row per evaluated vendor, in the same sort order the Dashboard shows.

| Column | Source |
|---|---|
| Rank | 1-based position in the dashboard's sort |
| Vendor | `vendor` |
| Product | `product` |
| SSA score (0–100) | `weighted_total` |
| §30 capability score (0–100) | `capability_weighted_total` |
| Gate | `DISQUALIFIED` if `gating.disqualified` else `PASS` |
| Vote | `vote.recommendation` |
| Vote confidence | `vote.confidence` |
| Model | `model_used` |
| Demo? | `is_demo` → `yes`/`no` |

### 5.2 Head-to-head compare (Compare)

One row per comparable line item; two value columns + a numeric delta (A−B). Non-numeric
rows (gate, vote) leave delta blank. Sections, in order:

- **Headline:** SSA score, §30 capability score.
- **Gate:** PASS/DISQUALIFIED (delta blank).
- **§30 capabilities:** one row per the eight capability codes (`score_1_5`).
- **SSA categories:** one row per the six categories (`raw_1_5`).
- **Segment fit:** one row per OpCo segment (`fit_1_5`).
- **Agentic future:** overall `score_1_5` (and openness/ai/data-control as rows).
- **Vote:** recommendation (delta blank).

Columns: `Section, Metric, <VendorA name>, <VendorB name>, Delta (A−B)`.

### 5.3 Per-vendor requirements (Vendor detail)

The 422-row audit backbone, canonical RID order.

| Column | Source (`RequirementScore`) |
|---|---|
| RID | `rid` |
| Domain | `domain` |
| Capability | `capability` |
| Priority | `priority` |
| Met | `met` |
| Quality (1–5) | `quality` |
| Response code | `vendor_code` |
| Confidence | `confidence` |
| Rationale | `rationale` |
| Evidence quote | `evidence.quote` or empty |
| Evidence source | `evidence.source` or empty |
| Evidence locator | `evidence.locator` or `(unlocated)` per existing convention |

## 6. PDF specification (SSA-branded, client-side print-to-PDF)

### 6.1 Branding (reuses existing assets, nothing invented)

- **Header band on every page:** color SSA long logo (data-URI) left; artifact title +
  generation date right; a `--ssa-blue (#003399)` rule line under it.
- **Palette (same hues as the app):** `--ssa-blue #003399` headings/accents,
  `--ssa-teal #336179` subheads, `--ink #0f1b33` body, `--line #E0E4EA` table borders,
  semantic `--good #1f7a4d / --warn #D97706 / --bad #b3261e` for gate/vote chips.
- **Type:** `'Avenir Next LT Pro','Avenir','Segoe UI',system-ui,sans-serif`.
- **Footer on every page:** `SSA & Company · Advisory evaluation · Generated <date>` and
  `page X` via CSS paged counters; plus a one-line "Advisory — augments the human
  committee" disclaimer matching the app's framing.
- **Page setup:** `@page { size: A4; margin: 18mm }`; `thead { display: table-header-group }`
  (repeat headers across page breaks); `tr { break-inside: avoid }`.

### 6.2 The two PDF artifacts

1. **All-vendor ranking brief** (Dashboard): branded title block; a context line
   ("N vendors evaluated · scored by `<model>` · `<date>`"); the ranked table (same columns
   as §5.1) with gate/vote rendered as colored chips.
2. **Head-to-head compare brief** (Compare): branded title block naming both vendors; the
   **computed one-line takeaway** the Compare tab already renders; the side-by-side rollup
   table with the colorblind-safe delta chips (arrow + sign, matching the app — not color
   alone).

### 6.3 Fallbacks (the button never silently no-ops)

- **Logo unavailable:** header degrades to an "SSA & Company" wordmark set in `--ssa-blue`.
- **Popup blocked** (`window.open` returns null): fall back to rendering the same
  `bodyHTML` into a hidden in-page container toggled visible only under a temporary
  `@media print` stylesheet, call `window.print()`, then tear the container down. So the
  hosted/Render case still prints even if popups are blocked.

## 7. Data flow

```
results array (already in React state from BOOT seed + /api/results)
        │
        ├─ Dashboard "Export CSV"  → rankingExport().csv  → toCSV → downloadBlob(.csv)
        ├─ Dashboard "Export PDF"  → rankingExport().pdf  → printDoc(branded)
        ├─ Compare "Export CSV"    → compareExport(a,b).csv → toCSV → downloadBlob(.csv)
        ├─ Compare "Export PDF"    → compareExport(a,b).pdf → printDoc(branded)
        └─ Vendor detail "Export CSV" → requirementsExport(v).csv → toCSV → downloadBlob(.csv)
```

No network call at export time. No backend involvement.

## 8. Error handling & edge cases

- **No evaluations / single vendor:** ranking export with 0 or 1 rows still produces a
  valid file (header row + whatever exists). Compare PDF/CSV buttons are disabled until two
  distinct vendors are selected (Compare tab already enforces a two-vendor selection).
- **Disqualified vendors:** appear normally; `Gate=DISQUALIFIED`, vote already
  `Disqualified`. No special-casing.
- **Demo results:** `is_demo` surfaced in the ranking CSV ("Demo?" column) and noted in the
  PDF context line, so a committee member never mistakes a demo run for a real one.
- **CSV injection:** values are CSV-quoted; not a concern for spreadsheet *formula*
  injection here because this is an internal advisory artifact, but leading `=,+,-,@` could
  be prefixed with a guard if desired — **decision: not in scope** (internal tool, trusted
  data, would corrupt rationale text). Noted, deliberately skipped.
- **Long rationale text** with commas/quotes/newlines: handled by RFC-4180 quoting.
- **Unicode** (smart quotes etc. in rationale): UTF-8 Blob; no BOM by default. (If Excel
  mangles UTF-8, a `﻿` BOM can be prepended — noted as a one-line tweak if it comes up.)

## 9. Testing / verification (project convention: manual + focused harness)

- **`toCSV` unit harness** (Node-free, in-browser or a tiny `python3`-mirrored check):
  fields with comma/quote/newline round-trip correctly; CRLF endings; header row present.
- **Builder determinism:** `rankingExport`/`compareExport`/`requirementsExport` on the
  bundled sample results produce stable, expected row counts (422 for requirements; N for
  ranking; fixed line-item count for compare).
- **Headless render check:** the app still mounts (the smart-quote-as-delimiter hazard —
  verify via headless `--dump-dom` → exactly one `>Dashboard<`).
- **Manual:** click each of the five buttons; confirm CSV opens cleanly in a spreadsheet;
  confirm the PDF print preview shows the SSA header/footer, repeats table headers across
  pages, and the chips/colors render.
- **Standalone parity:** rebuild `FSM_Evaluation_Agent_Standalone.html` via
  `python3 build_static.py`; confirm all five exports work from `file://` (logo via
  `BOOT.logo_dark`).
- **Re-run `graphify update .`** after the change.

## 10. Risk & rollback

- **Fully additive and client-side.** No backend, no endpoint, no dependency, mock and
  scoring untouched. Rollback = revert `frontend/index.html` (and the one `build_static.py`
  asset line) and rebuild the standalone.
- **Only real risk** is the in-browser-Babel hazard (a non-ASCII quote used as a JS string
  delimiter blanks the page); mitigated by the headless mount check in §9.
