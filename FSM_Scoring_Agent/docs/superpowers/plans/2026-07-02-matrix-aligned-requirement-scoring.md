# Matrix-Aligned Requirement Scoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Join the vendor's submitted requirements matrix to the 422 RFP RIDs so each requirement reaches the scorer with the vendor's actual response, instead of relying on term-overlap retrieval that misses most matrix rows.

**Architecture:** A new `ingest.extract_requirement_matrix()` parses any uploaded `.xlsx`/`.xlsm` into a `{rid: {code, response, source, sheet}}` map (RID-column join, requirement-text fallback). The map is plumbed `app._run_and_cache → evaluate_vendor → _score_requirements`. The live path injects each matched row as authoritative primary evidence in `_batch_prompt` (keeping the fuzzy excerpts as supplement); the mock path maps the vendor code → Met/Quality. An empty map reproduces today's behavior exactly.

**Tech Stack:** Python 3.12, Flask, `openpyxl` (already in requirements.txt), `unittest` run under `pytest` from `backend/`.

## Global Constraints

- Python 3.12; no new dependencies (`openpyxl` already present, optional at runtime).
- The offline "mock" engine must always work with zero API keys — never crash on a missing library.
- `openpyxl`/parse failures must degrade to `{}` (empty map), never raise into scoring.
- A run with an empty matrix map must be byte-for-byte the current scoring behavior (regression anchor).
- Persona-driven prompts: the live prompt still instructs judgment (a matrix code is a claim, not automatic full credit).
- Priority-weighted rollups and deterministic gating are unchanged — this plan only changes how per-requirement evidence is sourced.
- Tests run: `cd backend && python3 -m pytest tests/<file> -v`.
- Map shape (the interface every consumer relies on): `{ "<RID-UPPER>": {"code": str, "response": str, "source": str, "sheet": str} }`.

---

### Task 1: `extract_requirement_matrix` — RID-column join

**Files:**
- Modify: `backend/agent/ingest.py` (add function + helpers near the retrieval section, after `relevant_passages`)
- Test: `backend/tests/test_requirement_matrix.py` (create)

**Interfaces:**
- Consumes: nothing (leaf).
- Produces: `extract_requirement_matrix(paths: list[str], requirements: list[dict]) -> dict[str, dict]` returning the map-shape above; `_cell(row, idx) -> str`; `_find_rid_column(rows, known_rids) -> tuple[int|None, int|None]`; `_find_response_columns(rows, header_idx) -> tuple[int|None, int|None]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_requirement_matrix.py`:

```python
import os, tempfile, unittest
import openpyxl
from agent import ingest

def _make_xlsx(path, header, rows):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Requirements"
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)

REQS = [
    {"rid": "FSM-001", "requirement": "Ability to create work orders from inbound calls"},
    {"rid": "FSM-003", "requirement": "Ability to support configurable work order types"},
    {"rid": "PJM-050", "requirement": "Ability to flag projects as prevailing wage"},
]

class MatrixRidJoinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "resp.xlsx")

    def test_rid_column_join(self):
        header = ["Req ID", "Domain", "Requirement", "Priority", "Cap.",
                  "Vendor Response", "Vendor RFP Response"]
        rows = [
            ["Domain A: FSM", None, None, None, None, None, None],   # section row, ignored
            ["FSM-001", "A", "create work orders", "Must", "W2C", "OOB", "Generally available in base"],
            ["FSM-003", "A", "configurable types", "Must", "W2C", "CONFIG", "Supported via configuration"],
            ["ZZZ-999", "A", "not a real rid", "Must", "W2C", "OOB", "ignored"],  # unknown rid
        ]
        _make_xlsx(self.path, header, rows)
        m = ingest.extract_requirement_matrix([self.path], REQS)
        self.assertEqual(set(m), {"FSM-001", "FSM-003"})
        self.assertEqual(m["FSM-001"]["code"], "OOB")
        self.assertEqual(m["FSM-001"]["response"], "Generally available in base")
        self.assertEqual(m["FSM-003"]["code"], "CONFIG")
        self.assertEqual(m["FSM-001"]["source"], "resp.xlsx")
        self.assertEqual(m["FSM-001"]["sheet"], "Requirements")

    def test_no_matrix_returns_empty(self):
        _make_xlsx(self.path, ["Some", "Other", "Columns"], [["a", "b", "c"]])
        self.assertEqual(ingest.extract_requirement_matrix([self.path], REQS), {})

    def test_non_xlsx_and_empty_paths(self):
        self.assertEqual(ingest.extract_requirement_matrix([], REQS), {})
        txt = os.path.join(self.tmp, "x.txt"); open(txt, "w").write("hi")
        self.assertEqual(ingest.extract_requirement_matrix([txt], REQS), {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_requirement_matrix.py -v`
Expected: FAIL with `AttributeError: module 'agent.ingest' has no attribute 'extract_requirement_matrix'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/agent/ingest.py` (after `relevant_passages`, before the "Source segmentation" section). `re` and `os` are already imported; `_norm` already exists lower in the file and is used in Task 2.

```python
# --------------------------------------------------------------------------- #
# Requirements-matrix alignment (join vendor responses to RIDs)               #
# --------------------------------------------------------------------------- #
_RID_CELL_RE = re.compile(r"^[A-Z]{2,5}-\d{1,4}$")


def _cell(row, idx) -> str:
    if idx is None or idx >= len(row):
        return ""
    v = row[idx]
    return "" if v is None else str(v).strip()


def _find_rid_column(rows, known_rids):
    """(header_row_index, rid_col_index) or (None, None). Prefer a 'Req ID'/'RID'
    header; else the column whose values best match known RIDs."""
    for hi, row in enumerate(rows[:6]):
        for ci, cell in enumerate(row):
            name = re.sub(r"\s+", " ", str(cell or "")).strip().lower().rstrip(".")
            if name in ("req id", "rid", "requirement id", "req id#", "req. id"):
                return hi, ci
    best_col, best_hits = None, 0
    ncols = max((len(r) for r in rows), default=0)
    for ci in range(ncols):
        hits = sum(1 for r in rows if _cell(r, ci).upper() in known_rids)
        if hits > best_hits:
            best_col, best_hits = ci, hits
    if best_col is not None and best_hits >= 3:
        for hi, r in enumerate(rows):
            if _cell(r, best_col).upper() in known_rids:
                return max(0, hi - 1), best_col
    return None, None


def _find_response_columns(rows, header_idx):
    """(code_col, response_col). Prefer headers containing 'response' (shortest avg
    cell = code, longest = narrative); else the last two data-bearing columns."""
    header = rows[header_idx] if 0 <= header_idx < len(rows) else ()
    resp_cols = [ci for ci, c in enumerate(header) if "response" in str(c or "").lower()]
    data = rows[header_idx + 1:]

    def avg_len(ci):
        vals = [len(_cell(r, ci)) for r in data if _cell(r, ci)]
        return sum(vals) / len(vals) if vals else 0.0

    if len(resp_cols) >= 2:
        resp_cols.sort(key=avg_len)
        return resp_cols[0], resp_cols[-1]
    if len(resp_cols) == 1:
        return resp_cols[0], resp_cols[0]
    ncols = max((len(r) for r in rows), default=0)
    filled = [ci for ci in range(ncols) if any(_cell(r, ci) for r in data)]
    if len(filled) >= 2:
        return filled[-2], filled[-1]
    return (filled[-1], filled[-1]) if filled else (None, None)


def extract_requirement_matrix(paths, requirements):
    """Parse a submitted requirements matrix (.xlsx/.xlsm) into {rid: {code,
    response, source, sheet}} by joining on the RID column. Returns {} when no
    matrix is present or openpyxl is unavailable — callers then behave as before."""
    known = {str(r["rid"]).strip().upper() for r in (requirements or [])}
    out: dict = {}
    if not known:
        return out
    for p in (paths or []):
        if os.path.splitext(p)[1].lower() not in (".xlsx", ".xlsm"):
            continue
        try:
            import openpyxl
            wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        except Exception:
            continue
        fname = os.path.basename(p)
        try:
            for ws in wb.worksheets:
                rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
                if not rows:
                    continue
                hi, rid_col = _find_rid_column(rows, known)
                if rid_col is None:
                    continue
                code_col, resp_col = _find_response_columns(rows, hi)
                for row in rows[hi + 1:]:
                    rid = _cell(row, rid_col).upper()
                    if rid not in known or rid in out:
                        continue
                    code = _cell(row, code_col)
                    resp = _cell(row, resp_col)
                    if code_col == resp_col:      # single response column -> it's the narrative
                        code = ""
                    if not (code or resp):
                        continue
                    out[rid] = {"code": code, "response": resp, "source": fname, "sheet": ws.title}
        finally:
            try:
                wb.close()
            except Exception:
                pass
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_requirement_matrix.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/agent/ingest.py backend/tests/test_requirement_matrix.py
git commit -m "feat(ingest): extract_requirement_matrix — join vendor matrix to RIDs"
```

---

### Task 2: Requirement-text fallback join

**Files:**
- Modify: `backend/agent/ingest.py` (extend `extract_requirement_matrix`; add `_find_requirement_text_column`)
- Test: `backend/tests/test_requirement_matrix.py` (add a test)

**Interfaces:**
- Consumes: `extract_requirement_matrix`, `_cell`, `_norm` (existing) from Task 1.
- Produces: same `extract_requirement_matrix` signature, now also joining by normalized requirement text when no RID column exists.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_requirement_matrix.py`:

```python
class MatrixTextFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.path = os.path.join(self.tmp, "resp.xlsx")

    def test_text_fallback_when_no_rid_column(self):
        # No 'Req ID' column and values don't match RIDs -> join on requirement text.
        header = ["Requirement", "Vendor Response", "Vendor RFP Response"]
        rows = [
            ["Ability to create work orders from inbound calls", "OOB", "Available"],
            ["Ability to support configurable work order types", "CONFIG", "Configurable"],
        ]
        _make_xlsx(self.path, header, rows)
        m = ingest.extract_requirement_matrix([self.path], REQS)
        self.assertEqual(m["FSM-001"]["code"], "OOB")
        self.assertEqual(m["FSM-003"]["code"], "CONFIG")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_requirement_matrix.py::MatrixTextFallbackTests -v`
Expected: FAIL (KeyError 'FSM-001' — no RID column, text join not implemented)

- [ ] **Step 3: Write minimal implementation**

Add the helper to `backend/agent/ingest.py` (next to `_find_response_columns`):

```python
def _find_requirement_text_column(rows, header_idx, text_index):
    """Return the column index whose cell values best match known requirement
    texts (normalized), or None. Used only when no RID column is found."""
    data = rows[header_idx + 1:]
    ncols = max((len(r) for r in rows), default=0)
    best_col, best_hits = None, 0
    for ci in range(ncols):
        hits = sum(1 for r in data if _norm(_cell(r, ci)) in text_index)
        if hits > best_hits:
            best_col, best_hits = ci, hits
    return best_col if best_hits >= 3 else None
```

Then extend `extract_requirement_matrix`: build a text index and, when `rid_col is None`, join on text. Replace the `if rid_col is None: continue` block and the row loop with:

```python
                hi, rid_col = _find_rid_column(rows, known)
                text_index = {_norm(r["requirement"]): str(r["rid"]).strip().upper()
                              for r in requirements if r.get("requirement")}
                text_col = None
                if rid_col is None:
                    # header row for a text-only sheet is row 0 unless a match run starts lower
                    hi = 0
                    text_col = _find_requirement_text_column(rows, hi, text_index)
                    if text_col is None:
                        continue
                code_col, resp_col = _find_response_columns(rows, hi)
                for row in rows[hi + 1:]:
                    if rid_col is not None:
                        rid = _cell(row, rid_col).upper()
                    else:
                        rid = text_index.get(_norm(_cell(row, text_col)), "")
                    if rid not in known or rid in out:
                        continue
                    code = _cell(row, code_col)
                    resp = _cell(row, resp_col)
                    if code_col == resp_col:
                        code = ""
                    if not (code or resp):
                        continue
                    out[rid] = {"code": code, "response": resp, "source": fname, "sheet": ws.title}
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `cd backend && python3 -m pytest tests/test_requirement_matrix.py -v`
Expected: PASS (all Task 1 + Task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/agent/ingest.py backend/tests/test_requirement_matrix.py
git commit -m "feat(ingest): requirement-text fallback join for matrices without a Req ID column"
```

---

### Task 3: Mock path — map vendor code → Met/Quality

**Files:**
- Modify: `backend/agent/scoring.py` (add `_MATRIX_VERDICT` + `_matrix_verdict`; use them in `_mock_score_requirement`)
- Test: `backend/tests/test_matrix_scoring.py` (create)

**Interfaces:**
- Consumes: map shape from Task 1; `RequirementScore` (existing), `_mock_evidence` (existing).
- Produces: `_matrix_verdict(code: str) -> tuple[str, int]`; `_mock_score_requirement(..., requirement_matrix: dict | None = None)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_matrix_scoring.py`:

```python
import unittest
from agent import scoring

REQ = {"rid": "FSM-001", "domain": "A", "epic": "", "requirement": "create work orders",
       "priority": "Must", "capability": "W2C", "capability_raw": "W2C", "rfp_notes": ""}

class MatrixVerdictTests(unittest.TestCase):
    def test_code_mapping(self):
        self.assertEqual(scoring._matrix_verdict("OOB"), ("Yes", 4))
        self.assertEqual(scoring._matrix_verdict("CONFIG"), ("Yes", 3))
        self.assertEqual(scoring._matrix_verdict("EXTENSION"), ("Partial", 3))
        self.assertEqual(scoring._matrix_verdict("PARTNER"), ("Partial", 2))
        self.assertEqual(scoring._matrix_verdict("ROADMAP"), ("Partial", 2))
        self.assertEqual(scoring._matrix_verdict("CUSTOM"), ("Partial", 2))
        self.assertEqual(scoring._matrix_verdict("GAP"), ("No", 1))
        self.assertEqual(scoring._matrix_verdict(""), ("No", 1))
        self.assertEqual(scoring._matrix_verdict("wat"), ("Partial", 2))

    def test_mock_uses_matrix_when_present(self):
        m = {"FSM-001": {"code": "OOB", "response": "Available in base release",
                          "source": "resp.xlsx", "sheet": "Requirements"}}
        s = scoring._mock_score_requirement(REQ, "", {}, "", None, m)
        self.assertEqual(s.met, "Yes")
        self.assertEqual(s.quality, 4)
        self.assertEqual(s.vendor_code, "OOB")
        self.assertEqual(s.confidence, "High")
        self.assertEqual(s.evidence.get("locator"), "Requirements / FSM-001")

    def test_mock_falls_back_without_matrix(self):
        s = scoring._mock_score_requirement(REQ, "", {}, "", None, {})
        self.assertIn(s.met, ("Yes", "Partial", "No"))  # dossier path still works
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_matrix_scoring.py::MatrixVerdictTests -v`
Expected: FAIL (`AttributeError: ... has no attribute '_matrix_verdict'`)

- [ ] **Step 3: Write minimal implementation**

Add near the top of the mock-scoring section in `backend/agent/scoring.py` (above `_mock_score_requirement`):

```python
_MATRIX_VERDICT = {
    "OOB":       ("Yes", 4),
    "CONFIG":    ("Yes", 3),
    "EXTENSION": ("Partial", 3),
    "PARTNER":   ("Partial", 2),
    "ROADMAP":   ("Partial", 2),
    "CUSTOM":    ("Partial", 2),
    "GAP":       ("No", 1),
}


def _matrix_verdict(code):
    """Map a vendor response code to (met, quality) for the deterministic engine."""
    c = (code or "").strip().upper()
    if c in _MATRIX_VERDICT:
        return _MATRIX_VERDICT[c]
    if c in ("", "NO", "NONE", "N/A"):
        return ("No", 1)
    return ("Partial", 2)
```

Change the `_mock_score_requirement` signature to add the parameter:

```python
def _mock_score_requirement(r: Dict[str, Any], proposal_text: str,
                            strengths: Optional[Dict[str, float]] = None,
                            proposal_text_lower: Optional[str] = None,
                            segments=None,
                            requirement_matrix: Optional[Dict[str, Any]] = None) -> RequirementScore:
```

Insert this block immediately after the `if r["priority"] == "Won't":` early-return (before `cap = r["capability"]`):

```python
    mrow = (requirement_matrix or {}).get(r["rid"])
    if mrow:
        met, quality = _matrix_verdict(mrow.get("code"))
        code = (mrow.get("code") or "").strip().upper() or ("GAP" if met == "No" else "CONFIG")
        resp = (mrow.get("response") or "").strip()
        rationale = f"[matrix] Vendor response {code}" + (f" — {resp[:200]}" if resp else "")
        gap = "" if met == "Yes" else "Confirm depth in the Charlotte demo / references."
        ev = ({"quote": resp[:240], "source": mrow.get("source", ""),
               "locator": f"{mrow.get('sheet', 'Requirements')} / {r['rid']}"}
              if resp else _mock_evidence(r, segments))
        return RequirementScore(
            rid=r["rid"], domain=r["domain"], capability=r["capability"], priority=r["priority"],
            met=met, quality=quality, vendor_code=code, confidence="High",
            rationale=rationale[:400], evidence_gap=gap, evidence=ev)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_matrix_scoring.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/agent/scoring.py backend/tests/test_matrix_scoring.py
git commit -m "feat(scoring): mock engine maps vendor matrix code to Met/Quality"
```

---

### Task 4: Live path — inject the matched matrix row into `_batch_prompt`

**Files:**
- Modify: `backend/agent/scoring.py` (`_batch_prompt` adds a `requirement_matrix` param + block)
- Test: `backend/tests/test_matrix_scoring.py` (add a class)

**Interfaces:**
- Consumes: map shape from Task 1.
- Produces: `_batch_prompt(vendor, product, batch, context, requirement_matrix=None) -> str`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_matrix_scoring.py`:

```python
class BatchPromptTests(unittest.TestCase):
    BATCH = [REQ]

    def test_prompt_includes_matrix_block(self):
        m = {"FSM-001": {"code": "OOB", "response": "Available in base",
                          "source": "resp.xlsx", "sheet": "Requirements"}}
        p = scoring._batch_prompt("ServiceTitan", "", self.BATCH, "some excerpt", m)
        self.assertIn("VENDOR'S DIRECT ANSWERS", p)
        self.assertIn("[FSM-001]", p)
        self.assertIn("OOB", p)
        self.assertIn("Available in base", p)
        self.assertIn("some excerpt", p)   # fuzzy excerpts still present

    def test_prompt_omits_block_without_matrix(self):
        p = scoring._batch_prompt("ServiceTitan", "", self.BATCH, "some excerpt", {})
        self.assertNotIn("VENDOR'S DIRECT ANSWERS", p)
        self.assertIn("some excerpt", p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_matrix_scoring.py::BatchPromptTests -v`
Expected: FAIL (block not present / signature rejects the extra arg)

- [ ] **Step 3: Write minimal implementation**

Replace `_batch_prompt` in `backend/agent/scoring.py` with:

```python
def _batch_prompt(vendor, product, batch, context, requirement_matrix=None) -> str:
    m = requirement_matrix or {}
    reqs_json = [
        {"rid": r["rid"], "domain": r["domain"], "capability": r["capability"],
         "priority": r["priority"], "requirement": r["requirement"],
         "rfp_notes": r.get("rfp_notes", "")}
        for r in batch
    ]
    matrix_lines = []
    for r in batch:
        row = m.get(r["rid"])
        if row:
            resp = (row.get("response") or "").strip().replace("\n", " ")[:600]
            matrix_lines.append(f'[{r["rid"]}] code={row.get("code") or "?"}: {resp}')
    matrix_block = ""
    if matrix_lines:
        matrix_block = (
            "VENDOR'S DIRECT ANSWERS FROM ITS SUBMITTED REQUIREMENTS MATRIX "
            "(authoritative per-requirement response — treat as the vendor's own claim; "
            "still apply judgment: an OOB claim without demonstrated depth is not automatic "
            "full credit):\n" + "\n".join(matrix_lines) + "\n\n"
        )
    return (
        f"VENDOR: {vendor} — {product}\n\n"
        + matrix_block
        + f"RELEVANT EXCERPTS FROM THE VENDOR'S PROPOSAL (may be partial):\n"
        f"\"\"\"\n{context[:9000]}\n\"\"\"\n\n"
        f"Score EACH of the following requirements. For each, decide:\n"
        f"  - met: Yes | Partial | No | N/A\n"
        f"  - quality: integer 1-5 (0 if N/A)\n"
        f"  - vendor_code: OOB | CONFIG | EXTENSION | CUSTOM | PARTNER | ROADMAP | GAP\n"
        f"  - confidence: High | Medium | Low (Low if the proposal does not clearly evidence it)\n"
        f"  - rationale: one terse sentence in your voice (tie to outcomes/dollars where you can)\n"
        f"  - evidence_gap: what must still be proven in the Charlotte demo or references (\"\" if none)\n"
        f"  - evidence_quote: a SHORT verbatim quote (<=240 chars) copied EXACTLY from the matrix "
        f"answer or excerpts above that supports your call (\"\" if nothing addresses it)\n\n"
        f"If neither the matrix answer nor the excerpts address a requirement, do NOT invent a "
        f"capability — mark it Partial/No with Low confidence and name the gap.\n\n"
        f"REQUIREMENTS:\n{json.dumps(reqs_json, indent=0)}\n\n"
        f"Return ONLY a JSON object with a single key \"scores\" whose value is an array with "
        f"ONE object per requirement above (same count, same order), each object having keys: "
        f"rid, met, quality, vendor_code, confidence, rationale, evidence_gap, evidence_quote."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_matrix_scoring.py -v`
Expected: PASS (all Task 3 + Task 4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/agent/scoring.py backend/tests/test_matrix_scoring.py
git commit -m "feat(scoring): inject matched matrix row as primary evidence in live prompt"
```

---

### Task 5: Plumb `requirement_matrix` through scoring and the endpoints

**Files:**
- Modify: `backend/agent/scoring.py` (`evaluate_vendor`, `_score_requirements` accept + forward the map)
- Modify: `backend/app.py` (`_run_and_cache`, `_run_job`, `evaluate`, `evaluate_upload`)
- Test: `backend/tests/test_matrix_scoring.py` (add an end-to-end mock test)

**Interfaces:**
- Consumes: `ingest.extract_requirement_matrix` (Task 1/2); `_score_requirements`, `_mock_score_requirement`, `_batch_prompt` (Tasks 3/4).
- Produces: `evaluate_vendor(..., requirement_matrix: dict | None = None)`; `_score_requirements(..., requirement_matrix=None)`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_matrix_scoring.py`:

```python
class EndToEndMockTests(unittest.TestCase):
    def test_matrix_flows_into_mock_scores(self):
        from agent.knowledge import get_kb
        reqs = get_kb().requirement_list()
        rid = reqs[0]["rid"]
        matrix = {rid: {"code": "GAP", "response": "Not supported", "source": "r.xlsx",
                        "sheet": "Requirements"}}
        ev = scoring.evaluate_vendor("TestVendor", "", "proposal text",
                                     scoring_model="mock", requirement_sample=3,
                                     requirement_matrix=matrix)
        row = next(s for s in ev.requirement_scores if s.rid == rid)
        self.assertEqual(row.met, "No")
        self.assertEqual(row.vendor_code, "GAP")
        self.assertEqual(row.confidence, "High")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m pytest tests/test_matrix_scoring.py::EndToEndMockTests -v`
Expected: FAIL (`evaluate_vendor() got an unexpected keyword argument 'requirement_matrix'`)

- [ ] **Step 3: Write minimal implementation**

In `backend/agent/scoring.py`, add the parameter to `evaluate_vendor` (after `should_cancel`):

```python
    should_cancel: Optional[Callable[[], bool]] = None,
    requirement_matrix: Optional[Dict[str, Any]] = None,
) -> VendorEvaluation:
```

Forward it in the `_score_requirements` call inside `evaluate_vendor`:

```python
    req_scores, score_stats = _score_requirements(
        vendor, product, clean_text, reqs, scoring_model, _emit, should_cancel,
        segments, requirement_matrix)
```

Change `_score_requirements` signature to accept it:

```python
def _score_requirements(vendor, product, proposal_text, reqs, model_id, emit,
                        should_cancel=None, segments=None, requirement_matrix=None):
```

In the mock branch of `_score_requirements`, pass it through:

```python
        scores = [_mock_score_requirement(r, proposal_text, strengths, proposal_low,
                                          segments, requirement_matrix) for r in reqs]
```

In the live `score_batch` closure, pass it to `_batch_prompt`:

```python
        user = _batch_prompt(vendor, product, batch, context, requirement_matrix)
```

In `backend/app.py`, ensure these imports exist at module top (add if missing):

```python
from agent.ingest import extract_sources, extract_requirement_matrix
from agent.knowledge import get_kb
```

Change `_run_and_cache` to accept `file_paths` and build the map. Signature:

```python
def _run_and_cache(vendor, product, proposal_text, scoring_model, vote_model,
                   sample_n=None, vote_dual=None, progress=None, should_cancel=None,
                   file_paths=None):
```

Inside `_run_and_cache`, build the map and pass it to `evaluate_vendor` (replace the existing `ev = evaluate_vendor(...)` call):

```python
    requirement_matrix = (extract_requirement_matrix(file_paths, get_kb().requirement_list())
                          if file_paths else {})
    ev = evaluate_vendor(vendor, product, proposal_text,
                         scoring_model=scoring_model, requirement_sample=sample_n,
                         requirement_matrix=requirement_matrix,
                         progress=progress, should_cancel=should_cancel)
```

Add `file_paths=None` to `_run_job` and forward it:

```python
def _run_job(jid, **kw):
    ...
        result = _run_and_cache(progress=_job_progress(jid),
                                should_cancel=_job_should_cancel(jid), **kw)
```

(`_run_job` already forwards `**kw`, so passing `file_paths` in the thread kwargs is sufficient — no body change beyond accepting it via kw.)

In `evaluate()` (JSON endpoint), pass file paths into the thread kwargs:

```python
    threading.Thread(target=_run_job, kwargs=dict(
        jid=jid, vendor=vendor, product=product, proposal_text=proposal_text,
        scoring_model=scoring_model, vote_model=vote_model, sample_n=sample_n,
        vote_dual=vote_dual, file_paths=body.get("file_paths")), daemon=True).start()
```

In `evaluate_upload()`, pass the saved paths into its `_run_job` thread kwargs (find the `threading.Thread(target=_run_job, kwargs=dict(...))` call in this function and add `file_paths=saved_paths`):

```python
        ..., vote_dual=vote_dual, file_paths=saved_paths), daemon=True).start()
```

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `cd backend && python3 -m pytest tests/ -v`
Expected: PASS (matrix tests + the existing auth tests unaffected)

- [ ] **Step 5: Commit**

```bash
git add backend/agent/scoring.py backend/app.py backend/tests/test_matrix_scoring.py
git commit -m "feat: plumb requirement_matrix from uploads through scoring"
```

---

### Task 6: Regression guard + real-file sanity check

**Files:**
- Test: `backend/tests/test_matrix_scoring.py` (add a regression test)
- No production code changes expected (verification task).

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the regression test (empty map == today's behavior)**

Append to `backend/tests/test_matrix_scoring.py`:

```python
class RegressionTests(unittest.TestCase):
    def test_empty_matrix_matches_baseline_prompt(self):
        # With no matrix, _batch_prompt output must not contain the matrix block.
        p = scoring._batch_prompt("V", "", [REQ], "excerpt", None)
        self.assertNotIn("VENDOR'S DIRECT ANSWERS", p)

    def test_empty_matrix_mock_is_dossier_path(self):
        # No matrix -> mock uses the dossier path (rationale tagged [demo], not [matrix]).
        s = scoring._mock_score_requirement(REQ, "proposal", {}, "proposal", None, None)
        self.assertTrue(s.rationale.startswith("[demo]"))
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd backend && python3 -m pytest tests/test_matrix_scoring.py -v`
Expected: PASS

- [ ] **Step 3: Real-file sanity check (manual, mock engine)**

Run (adjust the path to the actual ServiceTitan upload):

```bash
cd backend && python3 - <<'PY'
from agent.ingest import extract_requirement_matrix
from agent.knowledge import get_kb
paths = ["/mnt/c/Users/chagood/Downloads/ServiceLogic RFP ServiceTitan Responses.xlsx"]
m = extract_requirement_matrix(paths, get_kb().requirement_list())
print("matched RIDs:", len(m), "/ 422")
from collections import Counter
print("codes:", Counter((v["code"] or "?").upper() for v in m.values()))
PY
```

Expected: matched RIDs is a large fraction of 422 (the vendor answered most rows), and the code distribution shows real OOB/CONFIG/etc. — not empty. This confirms the join works on the real submission.

- [ ] **Step 4: Full suite green**

Run: `cd backend && python3 -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_matrix_scoring.py
git commit -m "test: regression guards for empty-matrix (baseline) behavior"
```

---

## Self-Review

**Spec coverage:**
- §1 `extract_requirement_matrix` → Task 1 (RID join) + Task 2 (text fallback). ✓
- §2 join robustness (RID primary, text fallback, degrade to `{}`) → Tasks 1–2. ✓
- §3 plumbing (`app.py` → `evaluate_vendor` → `_score_requirements`) → Task 5. ✓
- §4 live-path injection → Task 4. ✓
- §5 mock-path code→Met mapping → Task 3. ✓
- §6 evidence attribution (matrix locator) → Task 3 (mock evidence sets `<sheet> / <RID>`); live evidence continues via existing `locate_quote` over the matrix text present in `proposal_text`. ✓
- §7 error handling (missing openpyxl / malformed → `{}`) → Task 1 (try/except around load + parse). ✓
- §8 testing (unit detection/join, mock mapping, live prompt, regression, real-file sanity) → Tasks 1–6. ✓

**Placeholder scan:** No TBD/TODO; every code and test step contains complete code and exact run commands. ✓

**Type consistency:** Map shape `{rid: {code, response, source, sheet}}` is produced in Task 1 and consumed identically in Tasks 3–5. `_matrix_verdict` returns `(met, quality)` used in Task 3. `_batch_prompt(..., requirement_matrix=None)` signature matches its call site in Task 5. `evaluate_vendor(..., requirement_matrix=None)` matches `_run_and_cache`'s call in Task 5 and the test in Task 5. RIDs are upper-cased consistently at both produce (Task 1) and lookup is by the requirement's own `r["rid"]` (matrix keys are upper; `requirements.json` RIDs are already upper like `FSM-001`, so `m.get(r["rid"])` matches). ✓

**One consistency note for the implementer:** matrix keys are upper-cased; `requirements.json` RIDs are already upper-case (`FSM-001`), so `requirement_matrix.get(r["rid"])` in `_mock_score_requirement`/`_batch_prompt` matches without re-casing. If any RID source is ever mixed-case, upper-case at lookup.
