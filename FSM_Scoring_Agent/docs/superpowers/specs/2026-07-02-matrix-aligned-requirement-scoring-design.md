# Design: Matrix-Aligned Requirement Scoring

**Date:** 2026-07-02
**Status:** Approved (brainstorming) — pending implementation plan
**Author:** Camp Hagood + Claude Code

## Problem

The first live evaluation (ServiceTitan, Claude Sonnet 4.6 scoring) marked **213 of 422
requirements "No" and 182 "Partial," with only 25 "Yes"** — and 86% of all verdicts at
**Low confidence**. Auditing the exported per-requirement CSV showed the harshness is an
**ingest artifact, not a vendor deficiency**:

- 304/422 rows carry no evidence quote; 325/422 have no locator.
- **95% of "No" verdicts (204/213) cite no evidence** and are Low confidence — their
  rationales say "not mentioned anywhere in the excerpts."
- Every "Yes" (25/25) cites an evidence quote. The High-confidence "No" verdicts are
  well-reasoned and evidence-backed (e.g. CBA resolution answered as `CUSTOM`, ~3–4
  developer-months — correctly failed as an unmet Must).

Root cause: the vendor answered on a **structured requirements matrix** — the RFP's own
spreadsheet with responses filled in. `ingest._xlsx()` flattens that matrix into
`cell | cell | cell` text lines, and `scoring._score_requirements()` retrieves context via
term-overlap over ~1200-char chunks, returning only the **top 8 chunks per 12-requirement
batch**. A 422-row matrix cannot be covered that way, so most requirements' answer rows
never reach the model and default to GAP / No / Low.

The vendor's `Requirements` sheet has a **`Req ID` column** (`FSM-001`, …) that matches our
422 RIDs exactly, plus response-code and narrative columns. So the fix is a **direct join on
`Req ID`**, not better fuzzy retrieval.

## Goals

- Every RID the vendor answered in its matrix reaches the scorer with that answer.
- Re-running ServiceTitan converts retrieval-miss GAPs into real, evidence-backed verdicts;
  MoSCoW/Must gating reflects genuine gaps, not retrieval coverage.
- Both the live-model path and the offline "mock" engine consume the matrix.
- Runs with no matrix (URL-only, narrative-only PDFs/decks) behave **exactly as today**.

## Non-goals (YAGNI)

- Parsing a requirements matrix embedded in a `.docx` table (v1 is `.xlsx`/`.xlsm` only —
  that is the SSA-issued template format). Revisit only if a vendor submits one.
- Changing the existing term-overlap retrieval itself. It stays as the fallback and as the
  supplementary-evidence source alongside matched matrix rows.
- Embeddings / vector store. Out of scope.

## Approach (selected: A — structured map + primary evidence)

Parse the submitted matrix into a `{rid: vendor_response}` map, plumb it through scoring, and
inject each requirement's matched row as **authoritative primary evidence** while **keeping**
the fuzzy narrative passages as supplement (the `.docx` elaboration produced the sharpest
verdicts, so it must not be dropped). Alternatives B (force matrix into retrieval) and C
(replace retrieval with the matrix row) were rejected — B bolts structured data onto a fuzzy
interface and doesn't serve the mock path; C discards the narrative evidence.

## Components

### §1 `ingest.extract_requirement_matrix(paths, known_rids) -> Dict[str, dict]`

New function in `backend/agent/ingest.py`.

- Iterates `.xlsx`/`.xlsm` files in `paths`. For each worksheet:
  - **Header detection:** find the header row — the first row whose cells include a
    `Req ID`/`RID`-like header, or (fallback) the row above a run of cells matching the RID
    regex `^[A-Z]{2,4}-\d+$`.
  - **Column identification:**
    - `rid_col`: header matches `/req\s*id|^rid$/i`, else the column whose values best match
      `known_rids`.
    - Response columns: headers containing "response" (case-insensitive). When two match, the
      shorter-valued column is the **code** (`OOB`/`CONFIG`/…), the longer is the **narrative**.
      If headers are unclear, take the 1–2 columns to the right of the standard RFP columns
      (`Req ID, Domain, Epic, User Story, Requirement, Priority, Cap., RFP Notes`).
  - Emit `{rid: {"code": <str>, "response": <str>, "source": <filename>, "sheet": <title>}}`
    for each data row whose `rid_col` value matches a known RID (normalized, exact).
- **Fallback join:** if no `rid_col` is found but a requirement-text column exists,
  normalized-match each row's requirement text to `requirements.json` requirement text;
  accept only unambiguous high-confidence matches.
- Returns `{}` when no matrix is detected, when `openpyxl` is missing, or on any parse error.
  Blank/section-header rows (the sheet has ~1000 rows for 422 requirements) are ignored because
  only rows with a matched RID are emitted.

### §2 Plumbing

- `backend/app.py` (`_run_and_cache`, where `file_paths` are known): build
  `matrix = ingest.extract_requirement_matrix(file_paths, kb_known_rids)` and pass
  `requirement_matrix=matrix` into `evaluate_vendor()`.
- `scoring.evaluate_vendor(..., requirement_matrix=None)` forwards it to
  `_score_requirements(..., requirement_matrix=None)`.
- Optional argument, default `None`/`{}` — URL-only and narrative-only runs are unchanged.

### §3 Live path — `scoring._batch_prompt()`

For each batched requirement with `requirement_matrix.get(rid)`, prepend an authoritative block:

```
VENDOR RESPONSE MATRIX [FSM-014]: code=OOB
response: "<vendor narrative cell>"
```

The existing fuzzy `context` passages are still appended as "supporting proposal excerpts."
Prompt instruction: treat the matrix row as the vendor's direct answer to this requirement and
the excerpts as elaboration; a matrix code still requires judgment (an `OOB` claim without
demonstrated depth is not automatically full credit — preserving the current skeptical stance).

### §4 Mock path — `scoring._mock_score_requirement()`

When `requirement_matrix.get(rid)` exists, map the vendor code → Met/Quality deterministically,
grounded in `config/scorecard.json`'s response-code taxonomy:

| Vendor code | Met | Quality | Confidence |
|-------------|-----|---------|-----------|
| `OOB`       | Yes     | 4 | High |
| `CONFIG`    | Yes     | 3 | High |
| `PARTNER`   | Partial | 2 | High |
| `ROADMAP`   | Partial | 2 | High |
| `CUSTOM`    | Partial | 2 | High |
| `GAP` / blank / "No" | No | 1 | High |
| unrecognized | Partial | 2 | Medium (pass code through in rationale) |

Confidence is High because it is the vendor's own stated answer. Rationale and evidence cite
the matrix. When no row exists, fall back to today's dossier cap-strength logic unchanged.

### §5 Evidence attribution

Matrix-sourced verdicts set `evidence = {source: <xlsx filename>, locator: "Requirements / <RID>"}`
instead of `(unlocated)`. The row text is already present in `proposal_text` (from `_xlsx`), so
`locate_quote` remains consistent; matrix verdicts simply get a deterministic, correct locator.

## Data flow

```
upload files ──► app._run_and_cache
                   ├─ ingest.extract_sources(paths, urls) ──► proposal_text (unchanged)
                   └─ ingest.extract_requirement_matrix(paths, known_rids) ──► {rid: response}
                          │
                          ▼
        scoring.evaluate_vendor(..., requirement_matrix)
                          │
                          ▼
        scoring._score_requirements(..., requirement_matrix)
             ├─ live:  _batch_prompt injects matched row + fuzzy excerpts
             └─ mock:  _mock_score_requirement maps code → Met/Quality
```

## Error handling

The matrix is **purely additive**; it never crashes or blocks scoring.

- Missing `openpyxl` → `extract_requirement_matrix` returns `{}` (mirrors `extract_text`).
- Malformed sheet, no RID column, no response columns → skip that file, try the rest; `{}` if none.
- Unrecognized response code → live: pass the raw code through to the model; mock: Partial/Medium
  with the code noted.
- A run with an empty map is byte-for-byte the current behavior.

## Testing

No test suite exists today; add targeted tests under `backend/tests/`.

- **Unit — `extract_requirement_matrix`:** on a synthetic ServiceTitan-shaped fixture
  (header row + section/blank rows + data rows, response columns named `<Vendor> Response`):
  detects the `Req ID` column and response columns; builds the correct `{rid: {...}}`; ignores
  blank/section rows (1000-row-for-422 case); text-fallback join when the RID column is absent;
  returns `{}` when no matrix / no `openpyxl`.
- **Unit — mock mapping:** the code→Met/Quality table above.
- **Integration — live prompt:** `_batch_prompt` includes the `VENDOR RESPONSE MATRIX [RID]`
  block when a row exists and omits it otherwise (string assertions; no live API call).
- **Regression:** a no-matrix run produces the same scoring context as today (the retrieval path
  is untouched when the map is empty).
- **End-to-end sanity:** re-run the real ServiceTitan file on the mock engine and confirm
  evidence-free "No" / Low-confidence GAP counts collapse and OOB/CONFIG rows become Yes/Partial.

## Success criteria

- Every RID present in the vendor matrix reaches the scorer with the vendor's response.
- Re-running ServiceTitan sharply reduces evidence-free "No" and Low-confidence GAP verdicts;
  unmet-Must gating reflects real gaps rather than retrieval misses.
- No-matrix runs are unchanged.

## Files touched

- `backend/agent/ingest.py` — new `extract_requirement_matrix()` (+ helpers).
- `backend/agent/scoring.py` — `evaluate_vendor`, `_score_requirements`, `_batch_prompt`,
  `_mock_score_requirement` accept and use `requirement_matrix`.
- `backend/app.py` — build the map from `file_paths`; pass into `evaluate_vendor`.
- `backend/tests/` — new tests (per Testing).
- Standalone rebuild not required (backend-only change).
