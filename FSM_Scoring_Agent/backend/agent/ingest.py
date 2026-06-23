"""
ingest.py — turn a vendor's proposal files into plain text the engine can score against.

Vendor proposals arrive (due July 2) as a mix of PDF, Word, Excel, and plain text.
This module extracts text from each, with graceful fallbacks if an optional parser
library is not installed. It also offers a light keyword-retrieval helper so the
scoring engine can pull the most relevant passages for a batch of requirements
instead of stuffing an entire 200-page proposal into every prompt.
"""
from __future__ import annotations
import os
import re
from typing import List, Optional, Tuple


def extract_text(path: str) -> str:
    """Dispatch on file extension. Returns extracted text (possibly empty)."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".txt", ".md"):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        if ext == ".pdf":
            return _pdf(path)
        if ext in (".docx",):
            return _docx(path)
        if ext in (".xlsx", ".xlsm"):
            return _xlsx(path)
    except ImportError as e:
        return (f"[parser not installed for {os.path.basename(path)} ({ext}); "
                f"install the matching library (pdfplumber/pypdf, python-docx, or openpyxl): {e}]")
    except Exception as e:
        return f"[ingest error for {os.path.basename(path)}: {type(e).__name__}: {e}]"
    return f"[unsupported file type: {ext}]"


def extract_many(paths: List[str]) -> str:
    """Concatenate text from several files with clear separators."""
    chunks = []
    for p in paths:
        chunks.append(f"\n\n===== FILE: {os.path.basename(p)} =====\n")
        chunks.append(extract_text(p))
    return "".join(chunks)


def fetch_url(url: str, timeout: int = 30) -> str:
    """
    Download a URL and extract its text. Handles documents served over HTTP
    (PDF/DOCX/XLSX/TXT/MD) by saving to a temp file and reusing extract_text(), and
    HTML pages by stripping tags. Used when a vendor posts its response on a portal
    or shared link rather than (or in addition to) attaching files.

    Note: this is the LOCALLY-RUN APP fetching a URL the operator explicitly supplied —
    it is the tool's own functionality, intended for vendor proposal links.
    """
    import urllib.request
    import tempfile
    import html
    from urllib.parse import urlparse

    if not url.lower().startswith(("http://", "https://")):
        return f"[invalid url (must start with http/https): {url}]"

    # SSRF guard: refuse private/loopback/link-local/reserved addresses
    import ipaddress, socket
    host = urlparse(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
        for fam, _, _, _, sockaddr in infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return f"[refused: {url} resolves to a non-public address ({ip})]"
    except Exception:
        return f"[refused: could not resolve host for {url}]"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FSM-RFP-Eval-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            max_bytes = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                return f"[refused: {url} exceeds the {max_bytes // (1024*1024)} MB limit]"
    except Exception as e:
        return f"[url fetch error for {url}: {type(e).__name__}: {e}]"

    path_ext = os.path.splitext(urlparse(url).path)[1].lower()
    doc_exts = (".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md")

    # Document by extension or content-type -> save to temp and reuse extract_text().
    is_doc = path_ext in doc_exts or any(
        k in ctype for k in ("pdf", "officedocument", "spreadsheet", "msword"))
    if is_doc:
        ext = path_ext if path_ext in doc_exts else (
            ".pdf" if "pdf" in ctype else
            ".xlsx" if "spreadsheet" in ctype else
            ".docx" if ("officedocument" in ctype or "msword" in ctype) else ".txt")
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
            tf.write(data)
            tmp = tf.name
        try:
            return extract_text(tmp)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # Otherwise treat as text/HTML: decode and strip tags.
    text = data.decode("utf-8", errors="ignore")
    if "html" in ctype or "<html" in text[:2000].lower() or "<body" in text[:4000].lower():
        text = re.sub(r"(?is)<(script|style|head|nav|footer)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)        # strip remaining tags
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_sources(paths: Optional[List[str]] = None,
                    urls: Optional[List[str]] = None) -> str:
    """
    Build a single proposal-text blob from any mix of uploaded files and URLs,
    each clearly delimited so retrieval can attribute passages back to a source.
    """
    parts = []
    for p in (paths or []):
        parts.append(f"\n\n===== FILE: {os.path.basename(p)} =====\n")
        parts.append(extract_text(p))
    for u in (urls or []):
        u = u.strip()
        if not u:
            continue
        parts.append(f"\n\n===== URL: {u} =====\n")
        parts.append(fetch_url(u))
    return "".join(parts).strip()


def _pdf(path: str) -> str:
    try:
        import pdfplumber  # preferred: better layout handling
        out = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                out.append(page.extract_text() or "")
        return "\n".join(out)
    except ImportError:
        from pypdf import PdfReader  # fallback
        reader = PdfReader(path)
        return "\n".join((pg.extract_text() or "") for pg in reader.pages)


def _docx(path: str) -> str:
    from docx import Document  # python-docx
    doc = Document(path)
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:                     # vendor responses often live in tables
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _xlsx(path: str) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"\n## Sheet: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Lightweight retrieval (no embeddings needed)                                #
# --------------------------------------------------------------------------- #
def chunk_text(text: str, target_chars: int = 1200) -> List[str]:
    """Split text into ~target_chars chunks on paragraph boundaries."""
    paras = re.split(r"\n\s*\n", text)
    chunks, cur = [], ""
    for para in paras:
        if len(cur) + len(para) > target_chars and cur:
            chunks.append(cur.strip())
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


RetrievalIndex = List[Tuple[str, str]]  # (original chunk, lowercase chunk)


def build_retrieval_index(text: str, target_chars: int = 1200) -> RetrievalIndex:
    """Pre-chunk/lowercase proposal text so repeated retrieval calls stay cheap."""
    return [(chunk, chunk.lower()) for chunk in chunk_text(text, target_chars)]


def relevant_passages(
    text: str,
    keywords: List[str],
    max_chunks: int = 6,
    index: Optional[RetrievalIndex] = None,
) -> str:
    """
    Return the chunks most relevant to a set of keywords (e.g. requirement terms),
    by simple term-overlap scoring. Good enough to localize a vendor's answer without
    a vector store; the engine can pass requirement keywords for a scoring batch.
    """
    entries = index if index is not None else build_retrieval_index(text)
    kw = [k.lower() for k in keywords if len(k) > 3]
    if not kw:
        return "\n\n".join(chunk for chunk, _ in entries[:max_chunks])
    scored = []
    for ch, low in entries:
        score = sum(low.count(k) for k in kw)
        if score:
            scored.append((score, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [c for _, c in scored[:max_chunks]]
    return "\n\n".join(top) if top else "\n\n".join(chunk for chunk, _ in entries[:max_chunks])
