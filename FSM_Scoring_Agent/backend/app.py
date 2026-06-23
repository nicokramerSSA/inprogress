"""
app.py — Flask API server + static host for the React front-end.

Endpoints
---------
  GET  /                      -> serves the React single-page app (frontend/index.html)
  GET  /api/health            -> liveness + whether any real model keys are present
  GET  /api/models            -> the model/provider registry (for the per-call selector)
  GET  /api/knowledge         -> persona, scorecard, capabilities, segments (for the UI)
  GET  /api/vendors           -> the five RFP vendors + research dossiers
  GET  /api/results           -> all cached evaluations (loads sample_results.json on boot)
  POST /api/evaluate          -> evaluate one vendor {vendor, product, proposal_text|use_sample,
                                 scoring_model, vote_model, requirement_sample?}
  POST /api/chat              -> {question, model_id, history?} grounded over KB + results

Design
------
* Results are kept in an in-memory store, seeded from data/sample_results.json so the
  UI has content the moment it loads (offline demo). Re-evaluating a vendor replaces it.
* Every LLM-touching endpoint takes an explicit model id, so the model is chosen
  per interaction (scoring, vote, and chat can each use a different model).
* The server NEVER reads or stores API keys; providers.py reads them from the env at
  call time. With no keys, everything still runs via the 'mock' engine.
"""
from __future__ import annotations

import os
import re
import json
import threading
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_from_directory

from agent.knowledge import get_kb
from agent.providers import available_models, resolve_model
from agent.scoring import evaluate_vendor
from agent.vote import synthesize_vote
from agent.chat import answer as chat_answer
from agent.ingest import extract_sources
from agent.sample import sample_proposal_text

_HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(_HERE), "frontend")
DATA_DIR = os.path.join(_HERE, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SAMPLE_RESULTS = os.path.join(DATA_DIR, "sample_results.json")

# Accept all the proposal file types the ingester understands.
ALLOWED_EXTS = {".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md"}


def _split_urls(raw: str) -> list[str]:
    """Split a textarea of URLs on newlines/commas/whitespace; keep http(s) only."""
    if not raw:
        return []
    parts = re.split(r"[\s,]+", raw.strip())
    return [u for u in parts if u.lower().startswith(("http://", "https://"))]


def _validate_models(*ids):
    """Return an error string if any non-mock model id is unknown, else None."""
    for mid in ids:
        if mid and mid != "mock":
            try:
                resolve_model(mid)
            except ValueError as e:
                return str(e)
    return None


def _run_and_cache(vendor, product, proposal_text, scoring_model, vote_model, sample_n=None):
    """Shared evaluate -> vote -> cache path used by both evaluate endpoints."""
    ev = evaluate_vendor(vendor, product, proposal_text,
                         scoring_model=scoring_model, requirement_sample=sample_n)
    ev.vote = synthesize_vote(ev, model_id=vote_model)
    result = ev.to_dict()
    with _RESULTS_LOCK:
        _RESULTS[vendor] = result
    return result

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")

# In-memory results store: vendor name -> evaluation dict. Seeded from disk on boot.
_RESULTS: dict[str, dict] = {}
_RESULTS_LOCK = threading.Lock()


def _seed_results():
    if os.path.exists(SAMPLE_RESULTS):
        try:
            with open(SAMPLE_RESULTS, "r", encoding="utf-8") as f:
                for ev in json.load(f):
                    _RESULTS[ev["vendor"]] = ev
        except Exception as e:
            app.logger.warning("Could not seed sample results: %s", e)


# --------------------------------------------------------------------------- #
# Static                                                                      #
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# --------------------------------------------------------------------------- #
# Read endpoints                                                              #
# --------------------------------------------------------------------------- #
@app.route("/api/health")
def health():
    models = available_models()
    any_key = any(p["key_present"] and p["id"] != "mock" for p in models["providers"])
    return jsonify({"ok": True, "live_models_available": any_key,
                    "n_results": len(_RESULTS)})


@app.route("/api/models")
def models():
    return jsonify(available_models())


@app.route("/api/knowledge")
def knowledge():
    kb = get_kb()
    return jsonify({
        "persona": kb.persona,
        "scorecard": kb.scorecard,
        "capabilities": kb.capabilities,
        "segments": kb.segments,
    })


@app.route("/api/vendors")
def vendors():
    kb = get_kb()
    return jsonify(kb.vendor_research)


@app.route("/api/results")
def results():
    with _RESULTS_LOCK:
        return jsonify(list(_RESULTS.values()))


# --------------------------------------------------------------------------- #
# Action endpoints                                                            #
# --------------------------------------------------------------------------- #
@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    """
    Evaluate one vendor from a JSON body. Proposal source (in priority order):
      use_sample -> proposal_text -> file_paths (+ urls) -> urls -> sample fallback.
    """
    body = request.get_json(force=True) or {}
    vendor = (body.get("vendor") or "").strip()
    if not vendor:
        return jsonify({"error": "vendor is required"}), 400
    product = (body.get("product") or "").strip()
    scoring_model = body.get("scoring_model", "mock")
    vote_model = body.get("vote_model", scoring_model)
    sample_n = body.get("requirement_sample")

    err = _validate_models(scoring_model, vote_model)
    if err:
        return jsonify({"error": err}), 400

    urls = body.get("urls") or []
    if isinstance(urls, str):
        urls = _split_urls(urls)

    if body.get("use_sample"):
        proposal_text = sample_proposal_text(vendor)
    elif body.get("proposal_text"):
        proposal_text = body["proposal_text"]
    elif body.get("file_paths") or urls:
        proposal_text = extract_sources(body.get("file_paths"), urls)
    else:
        proposal_text = sample_proposal_text(vendor)  # default so the demo always works

    if not (proposal_text or "").strip():
        return jsonify({"error": "No proposal content could be extracted from the provided sources."}), 400

    return jsonify(_run_and_cache(vendor, product, proposal_text, scoring_model, vote_model, sample_n))


@app.route("/api/evaluate_upload", methods=["POST"])
def evaluate_upload():
    """
    Evaluate one vendor from UPLOADED FILES and/or URLs (multipart/form-data).

    Form fields: vendor, product, scoring_model, vote_model, urls (newline/comma list),
    requirement_sample (optional int). Files come in the 'files' field (repeatable).
    Uploaded files are saved under data/uploads/<vendor>/ and parsed; URLs are fetched.
    """
    vendor = (request.form.get("vendor") or "").strip()
    if not vendor:
        return jsonify({"error": "vendor is required"}), 400
    product = (request.form.get("product") or "").strip()
    scoring_model = request.form.get("scoring_model", "mock")
    vote_model = request.form.get("vote_model", scoring_model)
    sample_n = request.form.get("requirement_sample", type=int)
    urls = _split_urls(request.form.get("urls", ""))

    err = _validate_models(scoring_model, vote_model)
    if err:
        return jsonify({"error": err}), 400

    # Save uploaded files (validated by extension) into a per-vendor folder.
    saved_paths, rejected = [], []
    vdir = os.path.join(UPLOAD_DIR, secure_filename(vendor) or "vendor")
    os.makedirs(vdir, exist_ok=True)
    for f in request.files.getlist("files"):
        if not f or not f.filename:
            continue
        name = secure_filename(f.filename)
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_EXTS:
            rejected.append(f.filename)
            continue
        dest = os.path.join(vdir, name)
        f.save(dest)
        saved_paths.append(dest)

    if not saved_paths and not urls:
        msg = "Provide at least one file (.pdf/.docx/.xlsx/.txt/.md) or a URL."
        if rejected:
            msg += f" Rejected unsupported file(s): {', '.join(rejected)}."
        return jsonify({"error": msg}), 400

    proposal_text = extract_sources(saved_paths, urls)
    if not (proposal_text or "").strip():
        return jsonify({"error": "No readable text could be extracted from the uploads/URLs."}), 400

    result = _run_and_cache(vendor, product, proposal_text, scoring_model, vote_model, sample_n)
    result["_ingest"] = {
        "files": [os.path.basename(p) for p in saved_paths],
        "urls": urls,
        "rejected": rejected,
        "chars_extracted": len(proposal_text),
    }
    return jsonify(result)


@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    model_id = body.get("model_id", "mock")
    history = body.get("history", [])
    with _RESULTS_LOCK:
        snapshot = list(_RESULTS.values())
    return jsonify(chat_answer(question, results=snapshot, model_id=model_id, history=history))


if __name__ == "__main__":
    _seed_results()
    port = int(os.environ.get("PORT", "8000"))
    print(f"\n  FSM RFP Evaluation Agent  →  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
