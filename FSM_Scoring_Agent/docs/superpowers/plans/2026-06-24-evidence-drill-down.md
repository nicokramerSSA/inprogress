# Evidence-Source Drill-Down Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each scored requirement carries a verbatim supporting quote, its source document, and a within-document locator (PDF page / XLSX sheet / DOCX section), surfaced as an expandable affordance on the per-vendor requirement table.

**Architecture:** Ingestion embeds `===== LOC: … =====` markers in the flat proposal blob. `evaluate_vendor` splits them back out *once* — `parse_segments` builds `(source, locator, text)` segments for quote-mapping, `strip_loc_markers` yields a `clean_text` that every existing consumer uses (so scoring is unperturbed). The scorer returns a verbatim `evidence_quote` per requirement; `locate_quote` maps it to a `{source, locator}`. The new `evidence` field is additive on `RequirementScore`. This branch never touches `app.py`/`store.py` (the parallel persistence branch's files), so the two run in parallel.

**Tech Stack:** Python 3.12 (invoked as `python3`), Flask, React 18 via CDN with in-browser Babel (ASCII-only JS string delimiters), stdlib `re`. No new dependencies. No automated test suite — pure-function and engine verification use standalone `python3` heredoc harnesses; UI is verified with headless Chrome.

## Global Constraints

- **`clean_text` preserves scoring (regression anchor).** `strip_loc_markers` removes only `LOC` lines; on the text/markdown/PDF/URL/sample paths `clean_text` is byte-identical to today's blob, so totals/gating/per-requirement met+quality do not move. The one intentional exception is XLSX (`## Sheet:` → `LOC`).
- **Never fabricate a locator.** A quote not found verbatim → `{source:"", locator:"(unlocated)"}`.
- **The offline mock engine must always work and must emit demo evidence** (best-effort, clearly `[demo]`-prefixed) so the feature is visible offline.
- **Additive schema.** `RequirementScore.evidence` defaults to `{}`; old/persisted results without it must still render.
- **ASCII-only JS string delimiters** (in-browser Babel — a single curly quote as a delimiter blanks the page). Unicode in JSX *text* is fine (the file already uses it).
- **No XSS.** Quote text renders as React children (escaped). No `dangerouslySetInnerHTML`, no href injection.
- **Gating stays deterministic and unchanged.** Evidence is presentation/provenance only.
- **`python3`, never `python`.** This WSL env has no `python` alias.
- **Do NOT touch** `backend/app.py` or `backend/store.py` — those belong to the parallel persistence branch (#2). Evidence travels inside the existing flat `proposal_text`, so no API-layer signatures change.

---

### Task 1: `ingest.py` — LOC markers + segmentation/locator helpers

**Files:**
- Modify: `backend/agent/ingest.py` (`_pdf` ~L139-150; `_docx` ~L153-160; `_xlsx` ~L163-173; add a new "Source segmentation" section)

**Interfaces:**
- Consumes: nothing new (stdlib `re`, already imported).
- Produces:
  - `parse_segments(blob: str) -> List[dict]` — segments `{source, locator, text, _norm}`; a blob with no `FILE:`/`URL:` headers → one `{source:"", locator:"(document)", ...}` segment.
  - `strip_loc_markers(blob: str) -> str` — removes only `===== LOC: … =====` lines.
  - `locate_quote(quote: str, segments: List[dict], min_len: int = 12) -> dict` — `{source, locator}`; `(unlocated)` when too short / not found.
  - Extractors `_pdf`/`_docx`/`_xlsx` now emit `===== LOC: … =====` markers (PDF `p.N`, DOCX heading text, XLSX `Sheet 'name'`).

- [ ] **Step 1: Add the segmentation/locator helpers**

Append a new section to `backend/agent/ingest.py` (after the retrieval section, end of file):

```python
# --------------------------------------------------------------------------- #
# Source segmentation & evidence locators                                     #
# --------------------------------------------------------------------------- #
_SRC_RE = re.compile(r"^=====\s+(?:FILE|URL):\s+(.*?)\s+=====$")
_LOC_RE = re.compile(r"^=====\s+LOC:\s+(.*?)\s+=====$")


def _norm(s: str) -> str:
    """Lowercase, collapse whitespace, strip surrounding quotes — for tolerant
    quote-to-segment matching."""
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s.strip("\"'“”‘’").lower()  # ASCII + curly quotes


def parse_segments(blob: str) -> List[dict]:
    """Reconstruct (source, locator, text) segments from a blob carrying
    ===== FILE/URL: ... ===== source headers and ===== LOC: ... ===== markers.
    A blob with no headers yields a single (source='', locator='(document)')
    segment. Each segment also caches its normalized text under '_norm' for fast
    locate_quote()."""
    segments: List[dict] = []
    source, locator = "", "(document)"
    buf: List[str] = []

    def flush():
        text = "\n".join(buf).strip()
        if text:
            segments.append({"source": source, "locator": locator,
                             "text": text, "_norm": _norm(text)})
        buf.clear()

    for line in (blob or "").split("\n"):
        m = _SRC_RE.match(line)
        if m:
            flush()
            source = m.group(1)
            locator = "(document)"      # reset locator when the source changes
            continue
        m = _LOC_RE.match(line)
        if m:
            flush()
            locator = m.group(1)
            continue
        buf.append(line)
    flush()
    return segments


def strip_loc_markers(blob: str) -> str:
    """Remove only ===== LOC: ... ===== lines, leaving FILE/URL headers and text.
    On the text/markdown/PDF/URL/sample paths this reproduces the pre-evidence
    blob byte-for-byte, so scoring is provably unperturbed (the regression
    anchor). XLSX differs only by the intentional '## Sheet:' -> LOC swap."""
    return "\n".join(line for line in (blob or "").split("\n")
                     if not _LOC_RE.match(line))


def locate_quote(quote: str, segments: List[dict], min_len: int = 12) -> dict:
    """Map a verbatim quote back to the segment that contains it (normalized
    substring). Returns {source, locator}; {source:'', locator:'(unlocated)'}
    when the quote is too short or not found — never fabricates a locator."""
    nq = _norm(quote)
    if len(nq) < min_len:
        return {"source": "", "locator": "(unlocated)"}
    for seg in segments:
        seg_norm = seg.get("_norm")
        if seg_norm is None:
            seg_norm = _norm(seg["text"])
        if nq in seg_norm:
            return {"source": seg["source"], "locator": seg["locator"]}
    return {"source": "", "locator": "(unlocated)"}
```

- [ ] **Step 2: Emit LOC markers in the file extractors**

Replace `_pdf` (~L139-150) with (a LOC marker per page; both the pdfplumber and pypdf branches; after stripping markers the output equals the old `"\n".join(pages)` exactly):

```python
def _pdf(path: str) -> str:
    try:
        import pdfplumber  # preferred: better layout handling
        out = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                out.append(f"===== LOC: p.{i + 1} =====")
                out.append(page.extract_text() or "")
        return "\n".join(out)
    except ImportError:
        from pypdf import PdfReader  # fallback
        reader = PdfReader(path)
        out = []
        for i, pg in enumerate(reader.pages):
            out.append(f"===== LOC: p.{i + 1} =====")
            out.append(pg.extract_text() or "")
        return "\n".join(out)
```

Replace `_docx` (~L153-160) with (a LOC marker at each Heading-styled paragraph; the heading text is still emitted as a paragraph, so stripping markers reproduces the old output):

```python
def _docx(path: str) -> str:
    from docx import Document  # python-docx
    parts = []
    doc = Document(path)
    for p in doc.paragraphs:
        style = (p.style.name if p.style else "") or ""
        if style.lower().startswith("heading") and p.text.strip():
            parts.append(f"===== LOC: {p.text.strip()} =====")
        parts.append(p.text)
    for table in doc.tables:                     # vendor responses often live in tables
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)
```

Replace `_xlsx` (~L163-173) with (the `## Sheet:` line becomes a LOC marker — the one intentional clean_text change):

```python
def _xlsx(path: str) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"===== LOC: Sheet '{ws.title}' =====")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)
```

- [ ] **Step 3: Run the acceptance harness**

Run from `backend/` (run before implementing to see it fail, then after to see it pass):

```bash
cd backend && python3 - <<'PY'
from agent.ingest import parse_segments, strip_loc_markers, locate_quote

blob = (
 "===== FILE: Acme.pdf =====\n"
 "===== LOC: p.1 =====\n"
 "Intro text about the platform.\n"
 "===== LOC: p.2 =====\n"
 "We support AIA G702 and G703 progress billing out of the box.\n"
 "===== URL: https://x.example/spec =====\n"
 "Open REST API and webhooks for data export."
)
segs = parse_segments(blob)
assert [(s["source"], s["locator"]) for s in segs] == [
    ("Acme.pdf", "p.1"), ("Acme.pdf", "p.2"), ("https://x.example/spec", "(document)")
], segs

stripped = strip_loc_markers(blob)
assert "===== LOC:" not in stripped
assert "===== FILE: Acme.pdf =====" in stripped and "===== URL:" in stripped

assert locate_quote("we support aia g702 and g703 progress billing", segs) == \
    {"source": "Acme.pdf", "locator": "p.2"}
loc2 = locate_quote("open REST API and webhooks for data export", segs)
assert loc2["source"] == "https://x.example/spec" and loc2["locator"] == "(document)"
assert locate_quote("a phrase that does not occur anywhere", segs)["locator"] == "(unlocated)"
assert locate_quote("api", segs)["locator"] == "(unlocated)"   # too short

solo = parse_segments("just some text\nmore text")
assert len(solo) == 1 and solo[0]["locator"] == "(document)" and solo[0]["source"] == ""
print("INGEST PURE OK")

# XLSX marker emission (only if openpyxl is installed)
try:
    import openpyxl, tempfile, os
    from agent.ingest import extract_text
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Pricing"
    ws["A1"] = "Year 1"; ws["B1"] = "$100k"
    p = tempfile.mktemp(suffix=".xlsx"); wb.save(p)
    t = extract_text(p)
    assert "===== LOC: Sheet 'Pricing' =====" in t, t
    os.unlink(p); print("XLSX MARKER OK")
except ImportError:
    print("XLSX skipped (openpyxl not installed)")
PY
```

Expected: `INGEST PURE OK` and either `XLSX MARKER OK` or `XLSX skipped`.

- [ ] **Step 4: Commit**

```bash
cd backend && git add agent/ingest.py && git commit -m "feat(evidence): LOC markers + segment/locator helpers in ingest

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

### Task 2: `schemas.py` evidence field + `scoring.py` capture (LLM + mock)

**Files:**
- Modify: `backend/agent/schemas.py` (`RequirementScore` ~L13-28)
- Modify: `backend/agent/scoring.py` (import L40; `evaluate_vendor` L101/104/119; `_score_requirements` L152-196; `_batch_prompt` L215-238; `_row_to_score` L241-260; `_mock_score_requirement` L314-373; add `_mock_evidence`)

**Interfaces:**
- Consumes: `parse_segments`, `strip_loc_markers`, `locate_quote` from Task 1.
- Produces: `RequirementScore.evidence: dict` (`{quote, source, locator}` or `{}`), populated by both the LLM and mock paths.

- [ ] **Step 1: Add the `evidence` field to `RequirementScore`**

In `backend/agent/schemas.py`, in `RequirementScore`, replace:

```python
    rationale: str                # short justification in the agent's voice
    evidence_gap: str = ""        # what still must be proven (demo / references)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

with:

```python
    rationale: str                # short justification in the agent's voice
    evidence_gap: str = ""        # what still must be proven (demo / references)
    evidence: Dict[str, Any] = field(default_factory=dict)  # {quote, source, locator}; {} if none

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

(`field`, `asdict`, `Dict`, `Any` are already imported at the top of the file.)

- [ ] **Step 2: Import the ingest helpers in `scoring.py`**

In `backend/agent/scoring.py`, replace the import (L40):

```python
from .ingest import build_retrieval_index, relevant_passages
```

with:

```python
from .ingest import (build_retrieval_index, relevant_passages,
                     parse_segments, strip_loc_markers, locate_quote)
```

- [ ] **Step 3: Build segments + clean_text once in `evaluate_vendor`**

In `evaluate_vendor`, immediately after the `requirement_sample` slice block (after `reqs = reqs[:requirement_sample]`, ~L92), add:

```python
    # Split structural markers out of the flat blob ONCE: segments carry source +
    # locator for quote-mapping; clean_text drives every existing consumer so
    # scoring is unperturbed (markers stripped).
    segments = parse_segments(proposal_text)
    clean_text = strip_loc_markers(proposal_text)
```

Then change the three consumer calls to pass `clean_text` (and `segments` to scoring):

- L101: `req_scores = _score_requirements(vendor, product, proposal_text, reqs, scoring_model, _emit, should_cancel)`
  → `req_scores = _score_requirements(vendor, product, clean_text, reqs, scoring_model, _emit, should_cancel, segments)`
- L104: `gating = _compute_gating(req_scores, proposal_text)`
  → `gating = _compute_gating(req_scores, clean_text)`
- L119: `agentic = _agentic_future(vendor, product, proposal_text, scoring_model)`
  → `agentic = _agentic_future(vendor, product, clean_text, scoring_model)`

- [ ] **Step 4: Thread `segments` through `_score_requirements`**

Change the signature (L152):

```python
def _score_requirements(vendor, product, proposal_text, reqs, model_id, emit, should_cancel=None, segments=None) -> List[RequirementScore]:
```

In the mock branch (L156), pass segments:

```python
    if is_mock(model_id):
        return [_mock_score_requirement(r, proposal_text, strengths, proposal_low, segments) for r in reqs]
```

In the LLM loop, change the row conversion (L188) and the fallback (L192):

```python
        for r in batch:
            row = by_rid.get(r["rid"])
            if row:
                out.append(_row_to_score(r, row, segments))
            else:
                out.append(_mock_score_requirement(r, proposal_text, strengths, proposal_low, segments))
```

- [ ] **Step 5: Ask for `evidence_quote` in the batch prompt**

In `_batch_prompt`, after the `evidence_gap` bullet line, insert an `evidence_quote` bullet, and add the key to the final return-keys line. Replace:

```python
        f"  - evidence_gap: what must still be proven in the Charlotte demo or references (\"\" if none)\n\n"
```

with:

```python
        f"  - evidence_gap: what must still be proven in the Charlotte demo or references (\"\" if none)\n"
        f"  - evidence_quote: a SHORT verbatim quote (<=240 chars) copied EXACTLY from the excerpts "
        f"above that supports your call (\"\" if the excerpts do not address it)\n\n"
```

and replace:

```python
        f"Return ONLY a JSON array, one object per requirement, keys: "
        f"rid, met, quality, vendor_code, confidence, rationale, evidence_gap."
```

with:

```python
        f"Return ONLY a JSON array, one object per requirement, keys: "
        f"rid, met, quality, vendor_code, confidence, rationale, evidence_gap, evidence_quote."
```

- [ ] **Step 6: Map the quote to a locator in `_row_to_score`**

Change the signature (L241) and add evidence capture before the return. Replace:

```python
def _row_to_score(r: Dict[str, Any], row: Dict[str, Any]) -> RequirementScore:
```

with:

```python
def _row_to_score(r: Dict[str, Any], row: Dict[str, Any], segments=None) -> RequirementScore:
```

and replace the return (L255-260):

```python
    return RequirementScore(
        rid=r["rid"], domain=r["domain"], capability=r["capability"],
        priority=r["priority"], met=met, quality=quality, vendor_code=code,
        confidence=conf, rationale=str(row.get("rationale", "")).strip()[:400],
        evidence_gap=str(row.get("evidence_gap", "")).strip()[:300],
    )
```

with:

```python
    quote = str(row.get("evidence_quote", "")).strip()[:240]
    evidence = {}
    if quote:
        loc = locate_quote(quote, segments or [])
        evidence = {"quote": quote, "source": loc["source"], "locator": loc["locator"]}
    return RequirementScore(
        rid=r["rid"], domain=r["domain"], capability=r["capability"],
        priority=r["priority"], met=met, quality=quality, vendor_code=code,
        confidence=conf, rationale=str(row.get("rationale", "")).strip()[:400],
        evidence_gap=str(row.get("evidence_gap", "")).strip()[:300],
        evidence=evidence,
    )
```

- [ ] **Step 7: Best-effort demo evidence in the mock engine**

Change the `_mock_score_requirement` signature (L314-316):

```python
def _mock_score_requirement(r: Dict[str, Any], proposal_text: str,
                            strengths: Optional[Dict[str, float]] = None,
                            proposal_text_lower: Optional[str] = None,
                            segments=None) -> RequirementScore:
```

Replace the main return (L369-373):

```python
    return RequirementScore(
        rid=r["rid"], domain=r["domain"], capability=cap, priority=r["priority"],
        met=met, quality=quality, vendor_code=code, confidence=conf,
        rationale=rationale, evidence_gap=gap,
    )
```

with:

```python
    return RequirementScore(
        rid=r["rid"], domain=r["domain"], capability=cap, priority=r["priority"],
        met=met, quality=quality, vendor_code=code, confidence=conf,
        rationale=rationale, evidence_gap=gap, evidence=_mock_evidence(r, segments),
    )
```

(The `Won't` early return at L324-326 stays as is — `evidence` defaults to `{}`.)

Then add the helper immediately after `_mock_score_requirement`:

```python
def _mock_evidence(r: Dict[str, Any], segments) -> Dict[str, Any]:
    """Best-effort demo evidence: pick the segment with the most requirement-term
    hits and snip a short window around the first hit, clearly prefixed [demo].
    Returns {} with no segments or no term hits (honest — never fabricates)."""
    if not segments:
        return {}
    terms = [w.strip(".,()/").lower() for w in r["requirement"].split() if len(w) > 5]
    if not terms:
        return {}
    best, best_hits, best_pos = None, 0, 0
    for seg in segments:
        low = seg["text"].lower()
        hits = sum(low.count(t) for t in terms)
        if hits > best_hits:
            positions = [low.find(t) for t in terms if t in low]
            best, best_hits, best_pos = seg, hits, (min(positions) if positions else 0)
    if not best:
        return {}
    start = max(0, best_pos - 60)
    snippet = " ".join(best["text"][start:start + 200].split())
    return {"quote": ("[demo] " + snippet)[:240],
            "source": best["source"], "locator": best["locator"]}
```

- [ ] **Step 8: Run the regression-anchor + evidence harness**

Run from `backend/`:

```bash
cd backend && python3 - <<'PY'
from agent.scoring import evaluate_vendor
from agent.sample import sample_proposal_text
from agent.ingest import strip_loc_markers

plain = sample_proposal_text("IFS")
lines = plain.split("\n"); mid = len(lines) // 2
marked = ("===== LOC: p.1 =====\n" + "\n".join(lines[:mid]) +
          "\n===== LOC: p.2 =====\n" + "\n".join(lines[mid:]))
# stripping the markers must reconstruct the plain text byte-for-byte
assert strip_loc_markers(marked) == plain, "strip must reconstruct plain exactly"

N = 60
a = evaluate_vendor("IFS", "", plain,  scoring_model="mock", requirement_sample=N)
b = evaluate_vendor("IFS", "", marked, scoring_model="mock", requirement_sample=N)

# Regression anchor: markers must NOT change any score or total.
assert a.weighted_total == b.weighted_total, (a.weighted_total, b.weighted_total)
assert a.capability_weighted_total == b.capability_weighted_total
assert a.gating.disqualified == b.gating.disqualified
assert a.gating.unmet_must_count == b.gating.unmet_must_count
assert [(s.rid, s.met, s.quality) for s in a.requirement_scores] == \
       [(s.rid, s.met, s.quality) for s in b.requirement_scores]
print("REGRESSION ANCHOR OK")

# Evidence is populated on the marked run and points at a real locator.
with_ev = [s for s in b.requirement_scores if s.evidence.get("quote")]
assert with_ev, "mock should populate some evidence from the marked segments"
sample = with_ev[0].evidence
assert sample["quote"].startswith("[demo]") and sample["locator"] in ("p.1", "p.2", "(document)")
print("EVIDENCE OK; rows with evidence:", len(with_ev), "/", N)
PY
```

Expected: `REGRESSION ANCHOR OK` and `EVIDENCE OK; rows with evidence: <n> / 60` with `n > 0`.

- [ ] **Step 9: Commit**

```bash
cd backend && git add agent/schemas.py agent/scoring.py && git commit -m "feat(evidence): capture per-requirement quote+source+locator (LLM + mock)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

### Task 3: Frontend evidence drill-down on the requirement table

**Files:**
- Modify: `frontend/index.html` (requirement-table row cell ~L583; `<style>` block)

**Interfaces:**
- Consumes: `x.evidence` (`{quote, source, locator}`) on each requirement-score row.
- Produces: an expandable `<details className="evidence">` per row when `x.evidence.quote` is present.

- [ ] **Step 1: Add the drill-down to the rationale cell**

In `frontend/index.html`, replace the requirement-table rationale cell (~L583):

```jsx
              <td>{x.rationale}{x.evidence_gap && <div className="muted" style={{marginTop:2}}>⤷ {x.evidence_gap}</div>}</td>
```

with:

```jsx
              <td>{x.rationale}
                {x.evidence_gap && <div className="muted" style={{marginTop:2}}>⤷ {x.evidence_gap}</div>}
                {x.evidence && x.evidence.quote && (
                  <details className="evidence">
                    <summary>evidence</summary>
                    <blockquote>{x.evidence.quote}</blockquote>
                    <div className="small muted">
                      {x.evidence.locator === "(unlocated)"
                        ? "location not pinned"
                        : (x.evidence.source ? x.evidence.source + ", " : "") + x.evidence.locator}
                    </div>
                  </details>
                )}
              </td>
```

(All JS string literals use ASCII double quotes. The `⤷` is pre-existing JSX text, untouched.)

- [ ] **Step 2: Add CSS for the evidence block**

In `frontend/index.html`, inside the existing `<style>` element (place it just before `</style>`), add:

```css
.requirement-table details.evidence{margin-top:4px}
.requirement-table details.evidence>summary{cursor:pointer;color:var(--ssa-blue);font-size:12px}
.requirement-table details.evidence blockquote{margin:4px 0;padding:4px 8px;border-left:3px solid var(--ssa-blue);background:rgba(0,0,0,.03);font-style:italic;font-size:12px}
```

- [ ] **Step 3: Verify Babel compiles and the app mounts (no blank page)**

The requirement table lives on the per-vendor detail view and current `sample_results.json` has no evidence yet (Task 4 regenerates it), so this step only proves the JSX compiles and the app still mounts — a single curly quote in a JS delimiter would blank the whole page.

```bash
cd backend && python3 app.py >/tmp/ev_app.log 2>&1 &
APP=$!; sleep 2
google-chrome --headless --disable-gpu --no-sandbox --dump-dom http://localhost:8000/ 2>/dev/null | grep -c ">Dashboard<"
kill $APP
```

Expected: `1` (Babel compiled and React mounted). `0` means a parse error blanked the page — fix before committing. If `google-chrome` is unavailable, substitute `chromium`/`chromium-browser`.

- [ ] **Step 4: Commit**

```bash
cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && git add frontend/index.html && git commit -m "feat(evidence): expandable quote+source+locator on the requirement table

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

### Task 4: Regenerate demo data + rebuild the standalone (end-to-end visibility)

**Files:**
- Modify: `backend/data/sample_results.json` (regenerated)
- Modify: `FSM_Evaluation_Agent_Standalone.html` (rebuilt)

**Interfaces:**
- Consumes: the mock engine (now emitting demo evidence) and `frontend/index.html` (now rendering it).
- Produces: a demo seed carrying evidence, visible in both the live server and the offline standalone.

- [ ] **Step 1: Regenerate `sample_results.json` from the current mock engine**

Run from `backend/`:

```bash
cd backend && python3 - <<'PY'
import json
from agent.scoring import evaluate_vendor
from agent.vote import synthesize_vote
from agent.sample import sample_proposal_text
from agent.knowledge import get_kb

vendors = [(v["vendor"], v.get("product", "")) for v in get_kb().vendor_research["vendors"]]
out = []
for vendor, product in vendors:
    ev = evaluate_vendor(vendor, product, sample_proposal_text(vendor), scoring_model="mock")
    ev.vote = synthesize_vote(ev, model_id="mock")
    out.append(ev.to_dict())
with open("data/sample_results.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

n_ev = sum(1 for r in out for x in r["requirement_scores"] if x.get("evidence", {}).get("quote"))
print("wrote", len(out), "vendors;", n_ev, "requirement rows carry evidence")
for r in out:
    print(" ", r["vendor"], "SSA", r["weighted_total"], "cap", r["capability_weighted_total"])
PY
```

Expected: `wrote 5 vendors; <n> requirement rows carry evidence` with `n > 0`. Note: these are regenerated from the *current* mock engine, so headline totals may differ slightly from the previously committed demo numbers if the engine evolved since the file was last generated. Sanity-check the printed SSA/cap totals are in a believable band (roughly 40–85); flag any large drift to the controller before committing.

- [ ] **Step 2: Rebuild the standalone**

```bash
cd backend && python3 build_static.py && ls -la ../FSM_Evaluation_Agent_Standalone.html
```

Expected: rebuilds without error.

- [ ] **Step 3: Verify evidence is visible end-to-end**

```bash
cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent"
# (a) The regenerated seed carries evidence objects.
python3 -c '
import json
d = json.load(open("backend/data/sample_results.json"))
ev = [x for r in d for x in r["requirement_scores"] if x.get("evidence",{}).get("quote")]
print("seed rows with evidence:", len(ev))
print("sample:", ev[0]["evidence"] if ev else "NONE")
assert ev, "regenerated seed has no evidence"
'
# (b) The standalone bundles that data, so the demo quotes are present in the file.
grep -c "\[demo\]" FSM_Evaluation_Agent_Standalone.html
# (c) The standalone still renders (Babel clean).
google-chrome --headless --disable-gpu --no-sandbox --dump-dom "file://$(pwd)/FSM_Evaluation_Agent_Standalone.html" 2>/dev/null | grep -c ">Dashboard<"
```

Expected: `seed rows with evidence: <n>` (`n>0`) with a `{quote, source, locator}` sample; the `[demo]` grep count `> 0`; the render grep `1`.

- [ ] **Step 4: Commit**

```bash
cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && git add backend/data/sample_results.json FSM_Evaluation_Agent_Standalone.html && git commit -m "build(evidence): regenerate demo seed with evidence + rebuild standalone

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019qDE6a8ib6kdPJZ5ASnGmx"
```

---

## Notes for the executor

- Tasks are sequential: Task 2 imports Task 1's helpers; Task 4 needs Task 2 (engine emits evidence) and Task 3 (UI renders it).
- This plan touches only `ingest.py`, `scoring.py`, `schemas.py`, `frontend/index.html`, `data/sample_results.json`, and the rebuilt standalone. It must not touch `app.py` or `store.py` (parallel persistence branch).
- After all tasks, run `graphify update .` to refresh the knowledge graph.
