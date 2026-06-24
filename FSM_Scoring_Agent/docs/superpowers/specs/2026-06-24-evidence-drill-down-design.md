# Evidence-Source Drill-Down — Design

**Date:** 2026-06-24
**Roadmap item:** #4 (from `2026-06-23-dual-provider-vote-and-robustness-design.md` §9)
**Status:** Approved, ready for implementation plan
**Parallel sibling:** Disk persistence (#2) — specced separately
(`2026-06-24-disk-persistence-design.md`). The two touch disjoint files and run
as parallel branches. **#4 deliberately does not touch `app.py` or `store.py`**;
#2 deliberately does not touch `ingest.py`, `scoring.py`, `schemas.py`, or
`frontend/index.html`.

---

## 1. Problem

A requirement score today carries a `rationale` and an `evidence_gap`, but no
pointer to *where in the proposal* the score came from. The selection committee
is asked to trust a 1–5 quality and a Met/Partial/No call with no way to jump to
the vendor's own words. The project ethos is "show your work"; the scores don't.

This adds evidence drill-down: each scored requirement carries a verbatim
supporting quote, the source document, and a within-document locator (PDF page,
XLSX sheet, DOCX section), surfaced in the UI as an expandable affordance on the
requirement row.

## 2. Goals / non-goals

**Goals**

- Per requirement: a **verbatim quote** the score relied on, the **source**
  (file or URL), and a **locator** within that source (PDF `p.N`, XLSX
  `Sheet 'Name'`, DOCX section/heading).
- Honest degradation: when a quote cannot be located verbatim, say
  `(unlocated)` — **never fabricate a page**.
- Works in both the live engine and the offline mock (the mock emits a
  best-effort, clearly-demo quote so the feature is visible offline).
- Additive schema: old/persisted results lacking evidence still render.
- **Identical scores/totals** to pre-#4 for the same vendor + proposal (the
  marker mechanism must not perturb scoring) — a built-in regression check.

**Non-goals (this round)**

- **No change to `app.py` or `store.py`** (those are persistence #2's files).
  Evidence travels inside the existing flat `proposal_text` via markers, so no
  call signatures across the API layer change.
- **No evidence in the Compare diff table** — drill-down lives on the per-vendor
  requirement table only.
- **No stored surrounding-context window** — the quote + locator is the
  evidence; the committee opens their own copy of the document to read more. A
  context window would add per-requirement storage for marginal value (deferred).
- No embeddings / vector retrieval. The existing term-overlap retrieval is
  unchanged; quote→locator mapping is independent of retrieval.
- No row-level locator for XLSX (sheet-level is the honest "where"); no
  character-precise highlighting.

## 3. Decision record

- **Markers in the flat blob, split out once (not new call signatures).**
  `evaluate_vendor` receives only `proposal_text`. Threading structured segments
  through would ripple into `app.py` (both evaluate endpoints), `_run_and_cache`,
  and the sample path — colliding with persistence #2's `app.py` edits. Instead,
  ingestion embeds `===== LOC: … =====` markers in the blob, and
  `evaluate_vendor` reconstructs segments and a clean (marker-free) text once at
  entry. `app.py` is untouched, so #2 and #4 stay parallel.
- **Quote-mapping over LLM-reported page.** Asking the model for a page number
  invites hallucination. Instead the model returns the verbatim quote (which it
  can copy faithfully), and we map the quote back to its segment deterministically
  to derive the locator. Unfound quote → `(unlocated)`.
- **Sheet-level (not row-level) XLSX locator.** Rows produce many tiny segments;
  the sheet is the honest, useful "where" and keeps the segment list small.

## 4. Architecture

```
ingestion (ingest.py):
  extract_text/_pdf/_docx/_xlsx ──emit LOC markers──▶ extract_sources(blob with markers)
                                                         │
scoring (scoring.py) evaluate_vendor(proposal_text):     │
  segments  = parse_segments(proposal_text)   ◀──────────┘   (provenance)
  clean_text = strip_loc_markers(proposal_text)              (everything semantic uses this)
  _score_requirements(clean_text, segments, …)
     LLM/mock returns evidence_quote ──locate_quote(quote, segments)──▶ {source, locator}
        ──▶ RequirementScore.evidence = {quote, source, locator}

frontend (index.html):
  requirement row ──expand──▶ blockquote(quote) + "— source, locator"
```

`clean_text` is semantically identical to today's `proposal_text` (markers
stripped), so gating, rollups, mock coverage, and agentic assessment are
unchanged — this is the regression anchor.

## 5. Component changes

### 5.1 `ingest.py` (extraction + new pure helpers)

**Marker format.** Reuse the existing `===== … =====` convention so the parser
keys on one shape. Source headers (`===== FILE: name =====`, `===== URL: u =====`)
already exist; add within-source locator lines `===== LOC: <locator> =====`.

- `_pdf`: emit `===== LOC: p.N =====` before each page's text (pdfplumber and the
  pypdf fallback both expose page order; N is 1-based).
- `_xlsx`: emit `===== LOC: Sheet 'Name' =====` before each sheet (replaces the
  current `## Sheet:` line).
- `_docx`: emit `===== LOC: <heading text> =====` at each Heading-styled
  paragraph; text before the first heading → `===== LOC: (document) =====`.
- `.txt`/`.md`/HTML/URL: a single `===== LOC: (document) =====`.
- `extract_sources`: unchanged structure (it concatenates per-source text under
  the `FILE:`/`URL:` headers); the per-source text now contains `LOC:` markers
  from the extractors.

**New pure functions:**

- `Segment = Dict[str, str]` with keys `source`, `locator`, `text`.
- `parse_segments(blob: str) -> List[Segment]` — walk lines; a line matching the
  `===== FILE: … =====`/`===== URL: … =====` shape sets the current source; a
  `===== LOC: … =====` line sets the current locator; other lines accumulate into
  the current segment's text. A blob with no headers → one segment
  `{source:"", locator:"(document)", text:blob}`.
- `strip_loc_markers(blob: str) -> str` — remove **only** the new
  `===== LOC: … =====` lines, leaving the `FILE:`/`URL:` headers in place (those
  were already present in the pre-#4 blob). On the text/markdown/PDF/URL/sample
  paths this makes `clean_text` byte-identical to the pre-#4 `proposal_text`, so
  scoring is provably unperturbed (the regression anchor). The one intentional
  exception is XLSX: its current `## Sheet: <title>` line is replaced by a
  `===== LOC: Sheet '<title>' =====` marker, so XLSX `clean_text` loses that one
  header line per sheet — a deliberate, immaterial formatting change, not a
  scoring perturbation. Source attribution is preserved in `segments`, never
  needed from `clean_text`.
- `locate_quote(quote: str, segments: List[Segment]) -> Dict[str, str]` —
  normalize (lowercase, collapse whitespace, strip surrounding quotes) both the
  quote and each segment's text; return the first segment whose normalized text
  contains the normalized quote as `{source, locator}`. Quote shorter than a
  minimum (e.g. 12 normalized chars) or no match → `{source:"", locator:"(unlocated)"}`.

### 5.2 `scoring.py`

- `evaluate_vendor`: at entry, build `segments = parse_segments(proposal_text)`
  and `clean_text = strip_loc_markers(proposal_text)`. Pass `clean_text` to
  `_score_requirements`, `_compute_gating`, and `_agentic_future` in place of
  `proposal_text`; pass `segments` to `_score_requirements`.
- `_score_requirements(vendor, product, clean_text, reqs, model_id, emit,
  should_cancel, segments)`:
  - Retrieval/index built on `clean_text` (unchanged behavior). The excerpts sent
    to the model are marker-free (they come from `clean_text`).
  - LLM batch prompt (`_batch_prompt`): add an `evidence_quote` field to the
    per-requirement instructions and to the "Return ONLY JSON … keys:" list —
    "a SHORT verbatim quote (≤ ~240 chars) copied exactly from the excerpts that
    supports your call; \"\" if the excerpts do not address it."
  - `_row_to_score(r, row, segments)`: read `evidence_quote` (truncate ~240),
    `loc = locate_quote(quote, segments)`, set
    `evidence = {"quote": quote, "source": loc["source"], "locator": loc["locator"]}`
    when a non-empty quote is present, else `evidence = {}`.
- `_mock_score_requirement(r, clean_text, strengths, clean_text_lower, segments)`:
  best-effort demo evidence — choose the segment with the most requirement-term
  hits, extract a short window around the first hit as the quote (prefixed
  `[demo]`), set `evidence = {quote, source, locator}` from that segment; no hit
  → `evidence = {}`.

### 5.3 `schemas.py`

`RequirementScore` gains `evidence: Dict[str, Any] = field(default_factory=dict)`
(`{quote, source, locator}`; `{}` when none). `asdict` serializes it for free;
absent on older records → `{}`.

### 5.4 `frontend/index.html`

On the per-vendor requirement table, when a row's `evidence.quote` is truthy,
render an expandable affordance (a small "evidence"/source toggle). Expanded:
the quote as a `<blockquote>` and a citation line `— {source}{, locator}`. If
`locator === "(unlocated)"`, show the quote with "location not pinned" and omit a
fake page. No evidence → render nothing for that row. ASCII-only JS string
delimiters (in-browser Babel). Quote text rendered as React children (escaped) —
no `dangerouslySetInnerHTML`, no href injection.

## 6. Demo data + build

- Regenerate `data/sample_results.json` by running the mock engine for the five
  vendors so the bundled demo carries evidence (it currently has none). Document
  the exact command in the plan.
- Rebuild `FSM_Evaluation_Agent_Standalone.html` via `python3 build_static.py`
  so the offline demo shows drill-down.

## 7. Error handling & edge cases

- **Quote not found / paraphrased / hallucinated** → `(unlocated)`; UI shows the
  quote with "location not pinned." Never fabricate a locator.
- **Empty quote** → `evidence = {}`; no drill-down on that row.
- **DOCX with no headings** → `(document)` locator.
- **Oversized quote** → truncated to ~240 chars (as `rationale`/`evidence_gap`
  already are).
- **A vendor line literally matching `===== LOC: … =====`** → astronomically
  unlikely; `parse_segments` only treats exact line-shaped matches as markers.
  Accepted residual risk, noted.
- **Old / persisted results without `evidence`** → guarded in the UI; this is the
  seam with persistence #2 (the store persists whatever `to_dict` holds; evidence
  is additive).
- The mock sample path (`sample_proposal_text`, no `FILE:` header) → one
  `(document)` segment with empty source; demo evidence still renders.

## 8. Testing / verification

No automated test suite (project convention — verification is manual). Verify:

1. **Regression anchor:** evaluate a vendor on the mock engine (sample proposal,
   no files) before and after the marker changes; `weighted_total`,
   `capability_weighted_total`, gating, and every requirement's met/quality are
   unchanged — on this path `clean_text` is byte-identical to the pre-#4 blob.
   (XLSX inputs differ only by the intentional `## Sheet:`→`LOC` swap; not part of
   the sample-path anchor.)
2. **Mock evidence:** a mock evaluation populates `evidence` on most rows; the UI
   expand shows the demo quote + source + locator.
3. **Live evidence** (if a key is set): spot-check several requirements — the
   quote is verbatim from the proposal and the locator points to the right
   page/sheet/section.
4. **Unlocated path:** force a quote that is not in the text (or inspect a
   paraphrased one) → `(unlocated)` renders gracefully.
5. **No leakage:** markers never appear in the model prompt or in the rendered
   UI (inspect a built prompt and the DOM).
6. **Standalone:** regenerated `sample_results.json` + rebuilt standalone render
   the drill-down offline; headless check confirms Babel compiles (no blank page).
7. **ASCII-only:** no curly quotes in JS string delimiters.

## 9. Risk & rollback

Additive and contained to `ingest.py`, `scoring.py`, `schemas.py`,
`frontend/index.html`, plus regenerated demo data and the standalone rebuild.
The marker mechanism is internal to ingestion+scoring; `clean_text` preserves
existing semantics (regression anchor). Rollback = revert those files and
regenerate `sample_results.json`/standalone from the prior engine. No backend
API, persistence, or scoring-rule changes. Evidence persists automatically once
persistence #2 lands, because the store is content-agnostic over `to_dict`.
