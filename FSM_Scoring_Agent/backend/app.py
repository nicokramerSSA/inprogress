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
import uuid
from datetime import timedelta
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_from_directory


def _load_dotenv():
    """Load backend/.env into os.environ if present. Uses python-dotenv when available,
    else a tiny built-in parser. Never overwrites a variable already set in the real
    environment (real env wins). Keys are read from env at call time by providers.py —
    this only makes a local .env convenient; the app never writes keys to disk."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
        return
    except Exception:
        pass
    # Fallback parser (no python-dotenv installed)
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_dotenv()  # must run before the agent imports below so provider keys are set at import time

from agent.knowledge import get_kb
from agent.providers import available_models, resolve_model
from agent.scoring import evaluate_vendor, EvaluationCancelled
from agent.vote import synthesize_vote, synthesize_vote_dual
from agent.chat import answer as chat_answer
from agent.ingest import extract_sources
from agent.sample import sample_proposal_text
from agent.committee import parse_committee_file, aggregate_committee

import store  # app-layer disk persistence for runtime evaluations (sibling module)
import auth   # authentication: user store, sessions, require_auth gate

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


def _run_and_cache(vendor, product, proposal_text, scoring_model, vote_model,
                   sample_n=None, vote_dual=None, progress=None, should_cancel=None):
    """Shared evaluate -> vote -> cache path used by both evaluate endpoints."""
    ev = evaluate_vendor(vendor, product, proposal_text,
                         scoring_model=scoring_model, requirement_sample=sample_n,
                         progress=progress, should_cancel=should_cancel)
    # Drop empty/null slots so a vote_dual of all-blank values (e.g. the UI's default
    # {openai:"", anthropic:"", ...}) doesn't activate the dual engine on placeholders.
    if vote_dual:
        vote_dual = {k: v for k, v in vote_dual.items() if v} or None
    if vote_dual:
        ev.vote = synthesize_vote_dual(
            ev, openai_model=vote_dual.get("openai", "mock"),
            anthropic_model=vote_dual.get("anthropic", "mock"),
            synthesizer_model=vote_dual.get("synthesizer", "claude-opus-4-8"))
    else:
        ev.vote = synthesize_vote(ev, model_id=vote_model)
    result = ev.to_dict()
    with _RESULTS_LOCK:
        _RESULTS[vendor] = result
    # Persist outside the in-memory lock (disk I/O must not be held under it). A
    # failed write must not fail an evaluation the user already paid for — the
    # result is still served from memory and will persist on the next success.
    try:
        store.save(result)
    except Exception as e:
        app.logger.warning("Could not persist result for %s: %s", vendor, e)
    return result

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
# Build stamp surfaced on /api/health so a deploy can be confirmed in production.
APP_VERSION = "2026.06.25"
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

# --- Authentication: signed-cookie sessions over a hashed-password user store --- #
app.secret_key = auth.get_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    # Secure by default (Render serves HTTPS). Set SESSION_COOKIE_SECURE=0 for local
    # http testing so the browser/test client will store the cookie.
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "1") != "0",
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
auth.load_users()  # seed users.json on boot (idempotent; works under gunicorn too)

# In-memory results store: vendor name -> evaluation dict. Seeded from disk on boot.
_RESULTS: dict[str, dict] = {}
_RESULTS_LOCK = threading.Lock()

# Latest uploaded committee aggregate; in-memory only (no disk persistence needed).
_COMMITTEE = {"aggregate": None}

# Job registry for background evaluations: job_id -> job state dict.
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _new_job():
    jid = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[jid] = {"stage": "queued", "scored": 0, "total": 0,
                      "done": False, "error": None, "result": None, "cancel": False}
    return jid


def _job_progress(jid):
    def cb(msg, frac):
        with _JOBS_LOCK:
            j = _JOBS.get(jid)
            if j:
                j["stage"] = msg
                # messages look like "Scored 120/422 requirements…"  (re imported at module top)
                m = re.search(r"(\d+)\s*/\s*(\d+)", msg)
                if m:
                    j["scored"], j["total"] = int(m.group(1)), int(m.group(2))
    return cb


def _job_should_cancel(jid):
    def chk():
        with _JOBS_LOCK:
            j = _JOBS.get(jid)
            return bool(j and j["cancel"])
    return chk


def _run_job(jid, **kw):
    try:
        result = _run_and_cache(progress=_job_progress(jid),
                                should_cancel=_job_should_cancel(jid), **kw)
        # Single lock block: attach ingest metadata and publish the result atomically,
        # so a status poll never sees a half-updated job and there's no ordering fragility.
        with _JOBS_LOCK:
            if "ingest" in _JOBS[jid]:
                result["_ingest"] = _JOBS[jid]["ingest"]
            _JOBS[jid].update(stage="done", done=True, result=result)
    except EvaluationCancelled:
        with _JOBS_LOCK:
            _JOBS[jid].update(stage="cancelled", done=True, error="cancelled")
    except Exception as e:
        with _JOBS_LOCK:
            _JOBS[jid].update(stage="error", done=True, error=f"{type(e).__name__}: {e}")


def _seed_results():
    # 1) Read-only demo seed (the five bundled vendors) so the UI has content on
    #    first boot / fresh checkout. Set SEED_DEMO_RESULTS=0 to suppress the demo
    #    vendors entirely — e.g. once real proposals are being evaluated and the
    #    bundled demos are just noise. The persisted store (step 2) still loads.
    if os.environ.get("SEED_DEMO_RESULTS", "1") != "0" and os.path.exists(SAMPLE_RESULTS):
        try:
            with open(SAMPLE_RESULTS, "r", encoding="utf-8") as f:
                for ev in json.load(f):
                    _RESULTS[ev["vendor"]] = ev
        except Exception as e:
            app.logger.warning("Could not seed sample results: %s", e)
    # 2) Overlay persisted runtime evaluations (durable-latest). The store wins
    #    over the demo seed: once the operator runs an evaluation, that is the
    #    real result. A store problem must never block boot.
    try:
        for vendor, result in store.load_all().items():
            _RESULTS[vendor] = result
    except Exception as e:
        app.logger.warning("Could not load persisted results: %s", e)


# --------------------------------------------------------------------------- #
# Static                                                                      #
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


# --------------------------------------------------------------------------- #
# Auth endpoints (open: login/logout/session)                                 #
# --------------------------------------------------------------------------- #
@app.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(force=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    rec = auth.verify(email, password)
    if not rec:
        # Generic message + same status for unknown-email vs wrong-password (no enumeration).
        return jsonify({"error": "Invalid email or password."}), 401
    auth.login_user(rec)
    return jsonify(auth.public_view(rec))


@app.route("/api/logout", methods=["POST"])
def logout():
    auth.logout_user()
    return jsonify({"ok": True})


@app.route("/api/session")
def session_whoami():
    rec = auth.current_user()
    if not rec:
        return jsonify({"error": "auth required"}), 401
    return jsonify(auth.public_view(rec))


@app.route("/api/account/password", methods=["POST"])
@auth.require_auth
def account_password():
    body = request.get_json(force=True) or {}
    user = auth.current_user()
    if not auth.verify(user["email"], body.get("current") or ""):
        return jsonify({"error": "Current password is incorrect."}), 400
    try:
        auth.set_password(user["email"], body.get("new") or "")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


# --------------------------------------------------------------------------- #
# Read endpoints                                                              #
# --------------------------------------------------------------------------- #
@app.route("/api/health")
def health():
    models = available_models()
    any_key = any(p["key_present"] and p["id"] != "mock" for p in models["providers"])
    return jsonify({"ok": True, "live_models_available": any_key,
                    "n_results": len(_RESULTS), "version": APP_VERSION})


@app.route("/api/models")
@auth.require_auth
def models():
    return jsonify(available_models())


@app.route("/api/knowledge")
@auth.require_auth
def knowledge():
    kb = get_kb()
    return jsonify({
        "persona": kb.persona,
        "scorecard": kb.scorecard,
        "capabilities": kb.capabilities,
        "segments": kb.segments,
    })


@app.route("/api/vendors")
@auth.require_auth
def vendors():
    kb = get_kb()
    return jsonify(kb.vendor_research)


@app.route("/api/results")
@auth.require_auth
def results():
    with _RESULTS_LOCK:
        return jsonify(list(_RESULTS.values()))


@app.route("/api/committee", methods=["GET"])
@auth.require_auth
def committee_get():
    return jsonify(_COMMITTEE["aggregate"] or {"vendors": [], "n_evaluators_total": 0, "warnings": []})


@app.route("/api/committee", methods=["POST"])
@auth.require_auth
def committee_post():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "No file uploaded."}), 400
    parsed = parse_committee_file(f.read(), f.filename or "")
    if parsed.get("error"):
        return jsonify({"error": parsed["error"]}), 400
    agg = aggregate_committee(parsed["rows"])
    agg["warnings"] = parsed.get("warnings", [])
    _COMMITTEE["aggregate"] = agg
    return jsonify(agg)


@app.route("/api/committee", methods=["DELETE"])
@auth.require_auth
def committee_delete():
    _COMMITTEE["aggregate"] = None
    return jsonify({"ok": True})


@app.route("/api/committee/template")
@auth.require_auth
def committee_template():
    return send_from_directory(DATA_DIR, "committee_template.csv",
                               as_attachment=True, download_name="committee_template.csv")


# --------------------------------------------------------------------------- #
# Action endpoints                                                            #
# --------------------------------------------------------------------------- #
@app.route("/api/evaluate", methods=["POST"])
@auth.require_auth
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
    vote_dual = body.get("vote_dual")  # {openai, anthropic, synthesizer} or None

    pair_ids = [vote_dual[k] for k in ("openai", "anthropic", "synthesizer")
                if vote_dual and vote_dual.get(k)] if vote_dual else []
    err = _validate_models(scoring_model, vote_model, *pair_ids)
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

    jid = _new_job()
    threading.Thread(target=_run_job, kwargs=dict(
        jid=jid, vendor=vendor, product=product, proposal_text=proposal_text,
        scoring_model=scoring_model, vote_model=vote_model, sample_n=sample_n,
        vote_dual=vote_dual), daemon=True).start()
    return jsonify({"job_id": jid}), 202


@app.route("/api/evaluate_upload", methods=["POST"])
@auth.require_auth
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
    vote_dual = None
    if request.form.get("vote_dual"):
        try:
            vote_dual = json.loads(request.form["vote_dual"])
        except Exception:
            vote_dual = None
    pair_ids = [vote_dual[k] for k in ("openai", "anthropic", "synthesizer")
                if vote_dual and vote_dual.get(k)] if vote_dual else []

    err = _validate_models(scoring_model, vote_model, *pair_ids)
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

    ingest_meta = {
        "files": [os.path.basename(p) for p in saved_paths],
        "urls": urls, "rejected": rejected, "chars_extracted": len(proposal_text),
    }
    jid = _new_job()
    # Attach ingest metadata BEFORE the worker is spawned below — the thread (and thus any
    # reader of _JOBS[jid]["ingest"]) only starts after this line, so no lock race exists.
    with _JOBS_LOCK:
        _JOBS[jid]["ingest"] = ingest_meta
    threading.Thread(target=_run_job, kwargs=dict(
        jid=jid, vendor=vendor, product=product, proposal_text=proposal_text,
        scoring_model=scoring_model, vote_model=vote_model, sample_n=sample_n,
        vote_dual=vote_dual), daemon=True).start()
    return jsonify({"job_id": jid}), 202


@app.route("/api/evaluate_batch", methods=["POST"])
@auth.require_auth
def evaluate_batch():
    """
    Evaluate MANY vendors in parallel from uploaded files/URLs (multipart/form-data).

    Shared fields: count, scoring_model, vote_model | vote_dual (JSON), requirement_sample?.
    Per row i in 0..count-1: vendor_i, files_i (repeatable), urls_i (newline/comma list).

    Launches one background job per valid vendor (the same machinery as the single
    endpoint); the global concurrency gate in providers.py bounds total in-flight LLM
    calls across all of them. Rows with no readable source are rejected, not fatal.
    """
    try:
        count = int(request.form.get("count", "0"))
    except ValueError:
        count = 0
    if count <= 0:
        return jsonify({"error": "count must be a positive integer"}), 400

    scoring_model = request.form.get("scoring_model", "mock")
    vote_model = request.form.get("vote_model", scoring_model)
    sample_n = request.form.get("requirement_sample", type=int)
    vote_dual = None
    if request.form.get("vote_dual"):
        try:
            vote_dual = json.loads(request.form["vote_dual"])
        except Exception:
            vote_dual = None
    pair_ids = [vote_dual[k] for k in ("openai", "anthropic", "synthesizer")
                if vote_dual.get(k)] if vote_dual else []
    err = _validate_models(scoring_model, vote_model, *pair_ids)
    if err:
        return jsonify({"error": err}), 400

    batch_id = uuid.uuid4().hex[:12]
    jobs, rejected = [], []
    for i in range(count):
        vendor = (request.form.get(f"vendor_{i}") or "").strip()
        if not vendor:
            rejected.append({"vendor": f"(row {i})", "reason": "missing vendor name"})
            continue
        urls = _split_urls(request.form.get(f"urls_{i}", ""))
        saved_paths, row_rejected = [], []
        vdir = os.path.join(UPLOAD_DIR, secure_filename(vendor) or f"vendor_{i}")
        os.makedirs(vdir, exist_ok=True)
        for f in request.files.getlist(f"files_{i}"):
            if not f or not f.filename:
                continue
            name = secure_filename(f.filename)
            ext = os.path.splitext(name)[1].lower()
            if ext not in ALLOWED_EXTS:
                row_rejected.append(f.filename)
                continue
            dest = os.path.join(vdir, name)
            try:
                f.save(dest)
            except Exception:
                row_rejected.append(f.filename)
                continue
            saved_paths.append(dest)
        if not saved_paths and not urls:
            reason = "no file (.pdf/.docx/.xlsx/.txt/.md) or URL provided"
            if row_rejected:
                reason += f"; rejected unsupported: {', '.join(row_rejected)}"
            rejected.append({"vendor": vendor, "reason": reason})
            continue
        proposal_text = extract_sources(saved_paths, urls)
        if not (proposal_text or "").strip():
            rejected.append({"vendor": vendor, "reason": "no readable text extracted"})
            continue
        ingest_meta = {
            "files": [os.path.basename(p) for p in saved_paths],
            "urls": urls, "rejected": row_rejected, "chars_extracted": len(proposal_text),
        }
        jid = _new_job()
        with _JOBS_LOCK:
            _JOBS[jid]["ingest"] = ingest_meta
        threading.Thread(target=_run_job, kwargs=dict(
            jid=jid, vendor=vendor, product="", proposal_text=proposal_text,
            scoring_model=scoring_model, vote_model=vote_model, sample_n=sample_n,
            vote_dual=vote_dual), daemon=True).start()
        jobs.append({"vendor": vendor, "job_id": jid})

    if not jobs:
        return jsonify({"error": "No valid vendors to evaluate.", "jobs": [], "rejected": rejected}), 400
    return jsonify({"batch_id": batch_id, "jobs": jobs, "rejected": rejected}), 202


@app.route("/api/evaluate/status/<job_id>")
@auth.require_auth
def evaluate_status(job_id):
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return jsonify({"error": "unknown job"}), 404
        return jsonify({k: j[k] for k in ("stage", "scored", "total", "done", "error", "result")})


@app.route("/api/evaluate/cancel/<job_id>", methods=["POST"])
@auth.require_auth
def evaluate_cancel(job_id):
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return jsonify({"error": "unknown job"}), 404
        j["cancel"] = True
    return jsonify({"ok": True})


@app.route("/api/chat", methods=["POST"])
@auth.require_auth
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


# --------------------------------------------------------------------------- #
# Error handlers                                                              #
# --------------------------------------------------------------------------- #
@app.errorhandler(413)
def _too_large(_e):
    return jsonify({"error": f"Upload exceeds the {MAX_UPLOAD_MB} MB limit."}), 413


if __name__ == "__main__":
    _seed_results()
    port = int(os.environ.get("PORT", "8000"))
    # Bind 0.0.0.0 so a hosting platform (Render/Docker) can route to the container;
    # locally you still reach it at http://127.0.0.1:PORT. Override with HOST if needed.
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"\n  FSM RFP Evaluation Agent  →  http://127.0.0.1:{port}\n")
    app.run(host=host, port=port, debug=False)
