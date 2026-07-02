# Design: LLM Matrix Extraction for Narrative Proposals

**Date:** 2026-07-02
**Status:** Approved — implemented
**Author:** Camp Hagood + Claude Code

## Problem

Vendors that answer the RFP in prose or export their filled matrix to a **PDF**
(IFS) have no clean `.xlsx` for `ingest.extract_requirement_matrix` to parse, so they
fall through to term-overlap retrieval — the harsh, retrieval-miss scoring the matrix
feature exists to eliminate. IFS's PDF *does* contain the full matrix as a table, but
deterministic PDF-table parsing is unreliable (prototype: 138/422, garbled codes,
whole domains missing) because cells wrap unpredictably and the header itself wraps
differently page to page.

## Approach

Reconstruct the per-requirement matrix from the extracted proposal text with the
scoring model, producing the same `{rid: {code, response, source, sheet}}` map the
xlsx path builds — so the existing matrix-grounded scoring path consumes it unchanged.
This is robust to messy PDF tables and faithful to the vendor's own stated codes.

## Components

### `agent/matrix_llm.py` — `extract_matrix(proposal_text, requirements, model_id)`
- Chunks the proposal text (~16K chars, 1.5K overlap) and asks the model, per chunk,
  to emit JSON `{"rows":[{rid, code, response}]}` for any requirement rows it sees,
  reconstructing wrapped/garbled cells.
- Merges chunks, keeps only the known RIDs, normalizes each code to the canonical set
  (`OOB/CONFIG/EXTENSION/CUSTOM/PARTNER/ROADMAP/GAP`) — tolerating PDF noise like
  `OOB I L` — else blank (never invents). Dedupes across overlapping chunks, preferring
  a row that carries a code.
- Runs through the shared provider client + `MAX_CONCURRENCY` gate.
- **Live-model only.** Returns `{}` on the mock engine, a missing key, empty input, or
  any failure; never raises into scoring.

### Integration — `app._run_and_cache`
When the deterministic xlsx matrix is empty **and** there is proposal text **and** a
live model is selected, build the matrix via `extract_matrix` and pass it to
`evaluate_vendor`. xlsx uploads and the mock engine are byte-for-byte unchanged.

## Provenance / auditability

Matrix rows built this way carry `source = "LLM-extracted (<model>)"` and
`sheet = "LLM extraction"`, distinguishing them from a vendor-supplied spreadsheet.
**A vendor scored this way (IFS) had its response codes reconstructed by the model
from its PDF, not read from a submitted matrix** — the committee should weight the
per-requirement evidence accordingly.

## Non-goals

- Deterministic PDF-table parsing (rejected: brittle, per-document).
- Changing the mock/offline path (must stay matrix-free, zero-key).
- Retrofitting stored results (forward-only; re-run a vendor to apply).

## Testing

- Unit (`tests/test_matrix_llm.py`, mocked provider): known-RID filtering, code
  normalization, soft-fail on not-ok / exception, dedup, mock returns `{}` without an
  API call, empty text.
- Real IFS run is the end-to-end verification (report match count + code distribution),
  performed on the deployed server (which holds the keys).
