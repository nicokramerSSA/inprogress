"""LLM-based requirement-matrix extraction from narrative proposals (PDF / DOCX).

When a vendor answers in prose — or exports its filled RFP matrix to a PDF whose
table cells wrap unpredictably — there is no clean spreadsheet for
``ingest.extract_requirement_matrix`` to parse. This module reads the extracted
proposal text in chunks and asks the scoring model to reconstruct each
requirement's response row ``{rid, code, response}``, producing the SAME
``{rid: {code, response, source, sheet}}`` map the xlsx path builds — so the
existing matrix-grounded scoring path consumes it with no further changes.

Live-model only. On the offline mock engine (or a missing key) it returns ``{}``
and scoring falls back to term-overlap retrieval exactly as before. It never
raises into the scoring pipeline: any chunk that fails is simply dropped.
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from .providers import client, is_mock, extract_json, MAX_CONCURRENCY

# The canonical response-code taxonomy (mirrors config/scorecard.json response_codes).
_VALID_CODES = ("EXTENSION", "PARTNER", "ROADMAP", "CONFIG", "CUSTOM", "OOB", "GAP")
_RID_RE = re.compile(r"^[A-Z]{2,4}-\d{1,4}$")

# ~4 chars/token, so 16k chars ≈ 4k tokens of proposal text per call — small enough
# that the JSON reply for the rows in that span fits comfortably under max_tokens.
_CHUNK_CHARS = 16000
_CHUNK_OVERLAP = 1500  # carry context across a split so a row cut at a boundary survives

_SYSTEM = (
    "You extract a software vendor's structured responses to RFP requirements from "
    "messy proposal text — often a PDF-rendered table whose cells have wrapped across "
    "lines. Be faithful to the vendor's own words; never invent a response."
)


def _normalize_code(raw: str) -> str:
    """Map a free-text code cell to one canonical response code, else ''.

    Tolerates PDF noise like 'OOB I L' or 'PARTNER SOLUTION' by matching the first
    recognized code token. EXTENSION/PARTNER/ROADMAP are checked before the shorter
    codes so 'CONFIG'/'OOB' substrings don't shadow them.
    """
    t = re.sub(r"[^A-Z]", " ", str(raw or "").upper())
    toks = t.split()
    for code in _VALID_CODES:
        if code in toks or t.startswith(code):
            return code
    return ""


def _chunks(text: str) -> List[str]:
    text = text or ""
    if not text.strip():
        return []
    if len(text) <= _CHUNK_CHARS:
        return [text]
    out, i = [], 0
    step = _CHUNK_CHARS - _CHUNK_OVERLAP
    while i < len(text):
        out.append(text[i:i + _CHUNK_CHARS])
        i += step
    return out


def _chunk_prompt(prefix_hint: str, chunk: str) -> str:
    return (
        "Below is text from a vendor's RFP response containing requirement rows. Each row "
        "has a Requirement ID (e.g. FSM-001, PJM-050), a response code, and a narrative "
        "comment. The response code is one of: OOB, CONFIG, EXTENSION, CUSTOM, PARTNER, "
        "ROADMAP, GAP. Cells may be split across lines (e.g. 'FSM-\\n032' means FSM-032).\n\n"
        "Extract every requirement row you can identify. Return ONLY JSON of the form:\n"
        '{"rows": [{"rid": "FSM-001", "code": "OOB", "response": "<vendor comment, '
        'trimmed to ~40 words>"}]}\n'
        'Use the exact uppercase rid. If a row shows no discernible code, use "". '
        "Skip rows whose rid you cannot read. Never invent a response.\n\n"
        f"Requirement-id prefixes in this RFP: {prefix_hint}.\n\n"
        "TEXT:\n" + chunk
    )


def extract_matrix(proposal_text: str, requirements: List[Dict[str, Any]],
                   model_id: str) -> Dict[str, Dict[str, str]]:
    """Reconstruct ``{rid: {code, response, source, sheet}}`` from narrative proposal
    text using the model. Returns ``{}`` on the mock engine, a missing key, empty
    input, or any failure — it never raises into the caller."""
    if is_mock(model_id):
        return {}
    known = {str(r["rid"]).strip().upper() for r in requirements if r.get("rid")}
    if not known:
        return {}
    chunks = _chunks(proposal_text)
    if not chunks:
        return {}
    hint = ", ".join(sorted({rid.split("-")[0] for rid in known}))

    def run_chunk(chunk: str) -> List[Any]:
        try:
            resp = client.generate(_SYSTEM, _chunk_prompt(hint, chunk), model_id,
                                   expect_json=True, max_tokens=8192, temperature=0.0)
            if not resp.get("ok"):
                return []
            parsed = extract_json(resp["text"])
            rows = parsed.get("rows") if isinstance(parsed, dict) else parsed
            return rows if isinstance(rows, list) else []
        except Exception:
            return []

    out: Dict[str, Dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as pool:
        futures = [pool.submit(run_chunk, c) for c in chunks]
        for fut in as_completed(futures):
            for row in fut.result():
                if not isinstance(row, dict):
                    continue
                rid = str(row.get("rid", "")).strip().upper()
                if not _RID_RE.match(rid) or rid not in known:
                    continue
                code = _normalize_code(row.get("code", ""))
                resp = str(row.get("response", "") or "").strip()
                # Overlapping chunks can surface the same rid twice; keep the first
                # entry that carries a code (richer), otherwise the first seen.
                if rid in out and (out[rid].get("code") or not code):
                    continue
                out[rid] = {"code": code, "response": resp,
                            "source": f"LLM-extracted ({model_id})",
                            "sheet": "LLM extraction"}
    return out
