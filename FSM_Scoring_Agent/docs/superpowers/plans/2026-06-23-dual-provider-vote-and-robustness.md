# Dual-Provider Vote, `.env` Loading, and Robustness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the FSM RFP Evaluation Agent fully usable with live models — fix the Opus API bug, load keys from `.env`, add a dual-provider (OpenAI + Anthropic) vote reconciled by Anthropic, and harden evaluation against timeouts/transient errors/bad inputs.

**Architecture:** Backend changes are additive and centered on the existing provider/engine layers (`providers.py`, `vote.py`, `app.py`, `scoring.py`, `ingest.py`, `models.json`, `schemas.py`); the single React-via-CDN file (`frontend/index.html`) gains model-selection and dual-vote UI plus job polling. The offline mock engine and the single-model path stay untouched and must keep working with zero keys.

**Tech Stack:** Python 3.12 / Flask (no DB, in-memory results), React 18 via CDN + Babel (no build step), `anthropic` / `openai` SDKs (optional), `python-dotenv` (optional, with a built-in fallback).

## Global Constraints

- **No test suite (project convention).** `CLAUDE.md` mandates manual verification. This plan replaces pytest TDD cycles with **verification-driven** steps: make the change → run a concrete command (curl / `python3 -c` / scratchpad script / browser screenshot) → confirm the expected output → commit. Do **not** scaffold a pytest suite. Throwaway check scripts live in the scratchpad dir, never committed.
- **Scratchpad dir for temp files:** `/tmp/claude-1000/-home-chagood-workspace-projects-RFP-Agent-FSM-Scoring-Agent/b8bc3f98-10e6-4167-bcaa-b007f9b186a5/scratchpad`
- **Python invocation:** Flask is installed via `pip --user`; run backend commands as `cd backend && python3 ...` (no venv on this box).
- **Branch:** all work on `feature/dual-provider-vote`. Commit per task; **do not push** (push requires explicit user approval per the user's global rules).
- **Invariants (never violate):** persona JSON drives every LLM call; gating is deterministic and never LLM-overridable; rollup weights stay Must 3× / Should 2× / Could 1×; API keys come from env only, never written to disk by the app; the offline mock engine must work with no network; the two scoring lenses stay independent.
- **Model ids (verified against the Claude API reference):** `claude-opus-4-8`, `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` are valid. Sampling params (`temperature`/`top_p`/`top_k`) **400 on Opus 4.7/4.8** but are accepted on Sonnet 4.6 / Haiku 4.5. The OpenAI **GPT-5.5** id (`gpt-5.5`) is a placeholder to verify against OpenAI's model list when an OpenAI key is added; it is not exercised until then.
- **After all code changes:** rebuild the standalone (`python build_static.py`) and run `graphify update .` (Task 10).

---

### Task 1: Fix the Opus sampling-parameter 400 (§0 prerequisite)

**Files:**
- Modify: `backend/config/models.json` (add `sampling_params: false` to Opus 4.7/4.8; add GPT-5.5 entry; add `dual_vote` defaults)
- Modify: `backend/agent/providers.py` (`_anthropic`, ~L126-143)

**Interfaces:**
- Consumes: `resolve_model(model_id)` → `(provider, model)` dicts (existing).
- Produces: `_anthropic()` behavior — omits `temperature` and sends `thinking={"type":"adaptive"}` when the resolved model has `"sampling_params": false`. No signature change to `generate()`.

- [ ] **Step 1: Edit `models.json` — Opus sampling flags + GPT-5.5 + dual_vote defaults**

In the `anthropic` provider's `models` array, add `"sampling_params": false` to the two Opus entries (leave Sonnet/Haiku untouched):
```json
{"id": "claude-opus-4-8", "label": "Claude Opus 4.8", "tier": "frontier", "best_for": "Deepest reasoning: final vote synthesis, contested Must gating, nuanced OpCo-fit judgment.", "max_output_tokens": 8192, "sampling_params": false},
```
(There is no `claude-opus-4-7` entry today — only add the flag to entries that exist, i.e. `claude-opus-4-8`. If a 4.7 entry is added later, it needs the same flag.)

In the `openai` provider's `models` array, add a GPT-5.5 entry **before** `gpt-4o`:
```json
{"id": "gpt-5.5", "label": "GPT-5.5", "tier": "frontier", "best_for": "OpenAI side of the dual-provider vote. VERIFY this exact model id against OpenAI's current model list before first live use.", "max_output_tokens": 8192, "verify_id": true},
```

Replace the `task_defaults` block with:
```json
  "task_defaults": {
    "scoring": "claude-sonnet-4-6",
    "vote_synthesis": "claude-opus-4-8",
    "chat": "claude-haiku-4-5-20251001",
    "dual_vote": { "openai": "gpt-5.5", "anthropic": "claude-opus-4-8", "synthesizer": "claude-opus-4-8" }
  }
```

- [ ] **Step 2: Edit `providers.py._anthropic()` to honor the flag**

Replace the body of `_anthropic` (currently L126-143) with:
```python
    def _anthropic(self, provider, model, system, user, expect_json, max_tokens, temperature):
        key = os.environ.get(provider["api_key_env"])
        if not key:
            return {"text": "", "provider": "anthropic", "model": model["id"], "ok": False,
                    "error": f"Missing {provider['api_key_env']} in environment."}
        import anthropic  # imported lazily so the app runs without the SDK installed
        client = anthropic.Anthropic(api_key=key)
        if expect_json:
            user = user + "\n\nReturn ONLY valid JSON. No prose, no code fences."
        kwargs = dict(
            model=model["id"],
            system=system,
            max_tokens=min(max_tokens, model.get("max_output_tokens", max_tokens)),
            messages=[{"role": "user", "content": user}],
        )
        # Opus 4.7/4.8 removed sampling params (temperature/top_p/top_k) — sending them 400s.
        # Models flagged sampling_params:false omit temperature and use adaptive thinking so
        # reasoning doesn't leak into the (often JSON) response.
        if model.get("sampling_params", True):
            kwargs["temperature"] = temperature
        else:
            kwargs["thinking"] = {"type": "adaptive"}
        resp = client.messages.create(**kwargs)
        text = "".join(block.text for block in resp.content
                       if getattr(block, "type", "") == "text")
        return {"text": text, "provider": "anthropic", "model": model["id"], "ok": True, "error": None}
```

- [ ] **Step 3: Verify the flag is honored without needing a network call**

Write `scratchpad/check_opus_fix.py`:
```python
import sys; sys.path.insert(0, "backend")
from agent.providers import resolve_model
_, opus = resolve_model("claude-opus-4-8")
_, sonnet = resolve_model("claude-sonnet-4-6")
assert opus.get("sampling_params") is False, "Opus must omit sampling params"
assert sonnet.get("sampling_params", True) is True, "Sonnet keeps sampling params"
print("OK: opus sampling_params =", opus.get("sampling_params"),
      "| sonnet =", sonnet.get("sampling_params", True))
```
Run: `cd backend && python3 ../scratchpad/check_opus_fix.py` (adjust the relative path to the scratchpad).
Expected: `OK: opus sampling_params = False | sonnet = True`

- [ ] **Step 4: (If an Anthropic key is present) live-confirm Opus no longer 400s**

Run: `cd backend && ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3 -c "import sys; sys.path.insert(0,'.'); from agent.providers import client; r=client.generate('You are terse.','Say the single word READY.','claude-opus-4-8',max_tokens=20); print(r['ok'], repr(r['text'])[:60], r['error'])"`
Expected: `True 'READY'... None` (previously this was `False … BadRequestError`). If no key is set, skip — Step 3 covers the logic.

- [ ] **Step 5: Commit**
```bash
cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent"
git add backend/config/models.json backend/agent/providers.py
git commit -m "fix: omit sampling params for Opus 4.7/4.8 (temperature 400); add gpt-5.5 + dual_vote defaults"
```

---

### Task 2: `.env` loading

**Files:**
- Modify: `backend/requirements.txt` (add `python-dotenv`)
- Modify: `backend/app.py` (load `.env` at the very top, before agent imports)
- Create: `backend/.env.example`
- Modify/Create: `.gitignore` (repo root)

**Interfaces:**
- Produces: `_load_dotenv()` in `app.py` runs at import time, populating `os.environ` from `backend/.env` without overwriting already-set vars. No other module changes.

- [ ] **Step 1: Add the dependency**

In `backend/requirements.txt`, under the `# Core server` section add:
```
python-dotenv>=1.0   # optional: load backend/.env at startup (built-in fallback if absent)
```

- [ ] **Step 2: Add the loader at the top of `app.py`**

`app.py` currently starts (after the module docstring) with imports including `from flask import ...` (L32) and `FRONTEND_DIR = ...` (L43). Immediately **after the `import os` / `import json` block and before any `from agent... ` import**, insert:
```python
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


_load_dotenv()
```
Place `_load_dotenv()` **before** `from agent.providers import ...` etc., so keys are present when those modules are imported.

- [ ] **Step 3: Create `backend/.env.example`**
```
# Copy to backend/.env and fill in. backend/.env is gitignored and never committed.
# Models without a present key are greyed out in the UI.
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
PORT=8000
```

- [ ] **Step 4: Gitignore `backend/.env`**

Append to the repo-root `.gitignore` (create it if missing):
```
# Local secrets — never commit
backend/.env
.env
```

- [ ] **Step 5: Verify load + non-overwrite + gitignore**

Create `scratchpad/check_env.py`:
```python
import os, sys
os.environ["ALREADY_SET"] = "from-real-env"
with open("backend/.env", "w") as f:
    f.write("FSM_TEST_VAR=hello\nALREADY_SET=from-file\n# comment\n")
sys.path.insert(0, "backend")
import importlib, app  # triggers _load_dotenv()
assert os.environ.get("FSM_TEST_VAR") == "hello", "should load new var"
assert os.environ["ALREADY_SET"] == "from-real-env", "must NOT overwrite real env"
print("OK: .env loaded; real env preserved")
```
Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && python3 scratchpad/check_env.py`
Expected: `OK: .env loaded; real env preserved`
Then confirm ignore: `git check-ignore backend/.env` → prints `backend/.env`. **Delete the test file:** `rm backend/.env`.

- [ ] **Step 6: Commit**
```bash
git add backend/requirements.txt backend/app.py backend/.env.example .gitignore
git commit -m "feat: load backend/.env at startup (python-dotenv + built-in fallback)"
```

---

### Task 3: Add dual-vote fields to the `Vote` schema

**Files:**
- Modify: `backend/agent/schemas.py` (`Vote` dataclass, L101-112)

**Interfaces:**
- Produces: `Vote` gains `mode: str = "single"`, `raw_votes: List[Dict[str,Any]] = []`, `disagreements: List[Dict[str,Any]] = []`. `to_dict()` (asdict) serializes them automatically. Existing constructions (positional/keyword without the new fields) keep working; existing `sample_results.json` loads unchanged.

- [ ] **Step 1: Add the fields**

In `schemas.py`, change the `Vote` dataclass to:
```python
@dataclass
class Vote:
    """The agent's final, independent vote."""
    recommendation: str           # Recommend / Shortlist / Reject / Disqualified
    confidence: str               # High / Medium / Low
    narrative: str                # in Nick's voice
    dissent: str                  # the strongest counter-argument to the recommendation
    top_risks: List[str] = field(default_factory=list)
    evidence_to_close: List[str] = field(default_factory=list)  # validate in Charlotte demos / refs
    mode: str = "single"          # "single" | "dual"
    raw_votes: List[Dict[str, Any]] = field(default_factory=list)
        # each: {provider, model, recommendation, narrative, dissent, top_risks}
    note: str = ""                # e.g. "dual off — add OPENAI_API_KEY to enable"
    disagreements: List[Dict[str, Any]] = field(default_factory=list)
        # each: {dimension, openai_position, anthropic_position, resolution}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```
(`Dict`/`Any` are already imported at the top of `schemas.py` — confirm; they are used by other dataclasses.)

- [ ] **Step 2: Verify defaults + serialization + sample load**

Create `scratchpad/check_vote_schema.py`:
```python
import sys; sys.path.insert(0, "backend")
from agent.schemas import Vote
v = Vote(recommendation="Shortlist", confidence="High", narrative="x", dissent="y")
d = v.to_dict()
assert d["mode"] == "single" and d["raw_votes"] == [] and d["disagreements"] == [] and d["note"] == ""
import json
json.load(open("backend/data/sample_results.json"))  # still valid JSON
print("OK: Vote defaults serialize; sample_results.json loads")
```
Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && python3 scratchpad/check_vote_schema.py`
Expected: `OK: Vote defaults serialize; sample_results.json loads`

- [ ] **Step 3: Commit**
```bash
git add backend/agent/schemas.py
git commit -m "feat: add dual-vote fields (mode, raw_votes, disagreements, note) to Vote"
```

---

### Task 4: Dual-vote engine in `vote.py`

**Files:**
- Modify: `backend/agent/vote.py` (refactor `_llm_narrative`; add `synthesize_vote_dual`, `_reconcile`)

**Interfaces:**
- Consumes: `derive_recommendation(ev)`, `_structured_findings(ev)`, `client.generate(...)`, `is_mock(model_id)`, `extract_json(text)`, `Vote(...)` with the Task 3 fields.
- Produces:
  - `_provider_narrative(ev, reco, band_reason, findings, model_id) -> dict` returning `{"provider","model","narrative","dissent","ok"}`.
  - `synthesize_vote_dual(ev, openai_model, anthropic_model, synthesizer_model) -> Vote` — Task 7 calls this.

- [ ] **Step 1: Refactor `_llm_narrative` into a reusable per-provider function**

Replace `_llm_narrative` (L147-167) with:
```python
def _provider_narrative(ev, reco, band_reason, findings, model_id) -> dict:
    """Generate one provider's narrative+dissent for the vote. Returns a dict so the
    dual path can carry per-provider results; the single path unwraps it."""
    kb = get_kb()
    system = kb.persona_system_prompt()
    import json as _json
    user = (
        f"You are casting your independent VOTE on vendor {ev.vendor} ({ev.product}) for the "
        f"Service Logic FSM selection. The deterministic rubric says: {reco} ({band_reason}).\n\n"
        f"STRUCTURED FINDINGS:\n{_json.dumps(findings, indent=2)}\n\n"
        f"Write your vote. Lead with the verdict, then the why. Tie weaknesses to dollars/outcomes "
        f"where you can (billing lag, revenue leakage, DSO, adoption). Name what must be proven in the "
        f"July 13-16 Charlotte demos. Then write the single strongest honest DISSENT against your own "
        f"recommendation.\n\n"
        f"Return ONLY JSON: {{\"narrative\": \"...\", \"dissent\": \"...\"}}"
    )
    resp = client.generate(system, user, model_id, expect_json=True, max_tokens=1500, temperature=0.3)
    out = {"provider": resp.get("provider", ""), "model": model_id,
           "narrative": band_reason, "dissent": "", "ok": bool(resp.get("ok"))}
    if resp.get("ok"):
        try:
            d = extract_json(resp["text"])
            out["narrative"] = str(d.get("narrative", "")).strip() or band_reason
            out["dissent"] = str(d.get("dissent", "")).strip()
        except Exception:
            out["ok"] = False
    return out


def _llm_narrative(ev, reco, band_reason, findings, model_id) -> tuple[str, str]:
    """Single-model path (unchanged behavior): returns (narrative, dissent)."""
    r = _provider_narrative(ev, reco, band_reason, findings, model_id)
    return (r["narrative"], r["dissent"])
```
This keeps `synthesize_vote()` (which calls `_llm_narrative`) byte-for-byte equivalent in behavior.

- [ ] **Step 2: Add the reconciler and the dual entry point**

Append to `vote.py`:
```python
def _reconcile(ev, reco, band_reason, findings, raw_votes, synthesizer_model) -> dict:
    """Anthropic reconciliation of the two provider votes. Returns
    {"narrative","dissent","disagreements":[...]} ; falls back to the Anthropic raw vote."""
    kb = get_kb()
    system = kb.persona_system_prompt()
    import json as _json
    user = (
        f"Two AI analysts independently voted on vendor {ev.vendor} ({ev.product}). The deterministic "
        f"rubric says {reco} ({band_reason}). Reconcile their votes into ONE final vote in Nick Kramer's "
        f"voice, and surface where they materially disagreed.\n\n"
        f"DETERMINISTIC FINDINGS:\n{_json.dumps(findings, indent=2)}\n\n"
        f"ANALYST VOTES:\n{_json.dumps(raw_votes, indent=2)}\n\n"
        f"Return ONLY JSON: {{\"narrative\":\"...\",\"dissent\":\"...\",\"disagreements\":"
        f"[{{\"dimension\":\"...\",\"openai_position\":\"...\",\"anthropic_position\":\"...\",\"resolution\":\"...\"}}]}}"
    )
    resp = client.generate(system, user, synthesizer_model, expect_json=True, max_tokens=2000, temperature=0.3)
    # Fallback = the Anthropic raw vote (or first available) if reconciliation fails.
    fallback = next((v for v in raw_votes if v["provider"] == "anthropic"), raw_votes[0] if raw_votes else {})
    out = {"narrative": fallback.get("narrative", band_reason),
           "dissent": fallback.get("dissent", ""), "disagreements": []}
    if resp.get("ok"):
        try:
            d = extract_json(resp["text"])
            out["narrative"] = str(d.get("narrative", "")).strip() or out["narrative"]
            out["dissent"] = str(d.get("dissent", "")).strip() or out["dissent"]
            dis = d.get("disagreements", [])
            out["disagreements"] = dis if isinstance(dis, list) else []
        except Exception:
            pass
    return out


def synthesize_vote_dual(ev, openai_model: str, anthropic_model: str,
                         synthesizer_model: str = "claude-opus-4-8") -> Vote:
    """Vote produced by OpenAI and Anthropic independently, then reconciled by Anthropic.
    Degrades to a single-provider vote when only one live key is present, and to the mock
    single vote when neither is. Gating/recommendation stay deterministic."""
    import concurrent.futures as _f
    from .providers import resolve_model

    # If neither side can run live, keep the offline demo behavior intact.
    if is_mock(openai_model) and is_mock(anthropic_model):
        return synthesize_vote(ev, model_id="mock")

    reco, band_reason, confidence = derive_recommendation(ev)
    findings = _structured_findings(ev)

    # Reuse the single path's deterministic risks + evidence so they stay identical.
    base = synthesize_vote(ev, model_id="mock")  # mock => no network, gives us risks/evidence
    risks, evidence = base.top_risks, base.evidence_to_close

    # Decide which providers actually have keys (a missing-key generate() returns ok:False fast).
    sides = []
    for label, mid in (("openai", openai_model), ("anthropic", anthropic_model)):
        if mid and not is_mock(mid):
            sides.append((label, mid))

    raw_votes, notes = [], []
    with _f.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(_provider_narrative, ev, reco, band_reason, findings, mid): (label, mid)
                for (label, mid) in sides}
        for fut in _f.as_completed(futs):
            label, mid = futs[fut]
            try:
                r = fut.result()
            except Exception:
                r = {"ok": False}
            if r.get("ok"):
                raw_votes.append({"provider": label, "model": mid,
                                  "recommendation": reco,
                                  "narrative": r["narrative"], "dissent": r["dissent"],
                                  "top_risks": risks})
            else:
                notes.append(f"{label} vote unavailable (missing key or API error)")

    # Order raw_votes openai-then-anthropic for stable UI.
    raw_votes.sort(key=lambda v: 0 if v["provider"] == "openai" else 1)

    if len(raw_votes) >= 2:
        rec = _reconcile(ev, reco, band_reason, findings, raw_votes, synthesizer_model)
        return Vote(recommendation=reco, confidence=confidence,
                    narrative=rec["narrative"], dissent=rec["dissent"],
                    top_risks=risks, evidence_to_close=evidence,
                    mode="dual", raw_votes=raw_votes, disagreements=rec["disagreements"],
                    note="; ".join(notes))
    if len(raw_votes) == 1:
        only = raw_votes[0]
        missing = "OPENAI_API_KEY" if only["provider"] == "anthropic" else "ANTHROPIC_API_KEY"
        return Vote(recommendation=reco, confidence=confidence,
                    narrative=only["narrative"], dissent=only["dissent"],
                    top_risks=risks, evidence_to_close=evidence,
                    mode="single", raw_votes=raw_votes, disagreements=[],
                    note=f"Dual synthesis off — add {missing} to enable a two-model read.")
    # Both sides failed -> deterministic mock vote, flagged.
    base.note = "Live vote unavailable; showing deterministic read. " + "; ".join(notes)
    return base
```

- [ ] **Step 3: Verify keyless degradation (mock pair → single mock vote)**

Create `scratchpad/check_dual.py`:
```python
import sys; sys.path.insert(0, "backend")
from agent.knowledge import get_kb
from agent.scoring import evaluate_vendor
from agent.vote import synthesize_vote_dual
# Build a cheap evaluation via the mock pipeline (first 12 requirements only):
from agent.sample import sample_proposal_text
ev = evaluate_vendor("IFS", "", sample_proposal_text("IFS"), scoring_model="mock", requirement_sample=12)
v = synthesize_vote_dual(ev, openai_model="mock", anthropic_model="mock")
assert v.mode == "single" and v.recommendation, v.mode
print("OK: keyless dual -> single mock vote, reco =", v.recommendation, "| mode =", v.mode)
```
Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && python3 scratchpad/check_dual.py`
Expected: `OK: keyless dual -> single mock vote, reco = ... | mode = single`

- [ ] **Step 4: (If Anthropic key present) verify Anthropic-only degrades to mode="single" with a note**

Run with `ANTHROPIC_API_KEY` set, calling `synthesize_vote_dual(ev, openai_model="gpt-5.5", anthropic_model="claude-opus-4-8")`. Expected: `mode == "single"`, `len(raw_votes) == 1` (anthropic), `note` mentions `OPENAI_API_KEY`. (Skip if no key — Step 3 covers logic.)

- [ ] **Step 5: Commit**
```bash
git add backend/agent/vote.py
git commit -m "feat: dual-provider vote with Anthropic reconciliation and graceful degradation"
```

---

### Task 5: Retry/backoff on transient provider errors

**Files:**
- Modify: `backend/agent/providers.py` (`generate`, ~L99-123)

**Interfaces:**
- Produces: `generate()` retries transient failures (timeouts, 429, ≥500, connection errors) with exponential backoff; client errors (400/401/403/404) and missing-key/unsupported-sdk results are returned immediately. Same `{text,provider,model,ok,error}` return shape.

- [ ] **Step 1: Wrap the dispatch in a retry loop**

In `generate()`, the current body does a single `try/except` around the sdk dispatch. Replace the dispatch section so it retries. Add `import time` at the top of `providers.py` if not present, then change `generate`'s try block to:
```python
        provider, model = resolve_model(model_id)
        sdk = provider["sdk"]
        last = None
        for attempt in range(3):  # 1 try + 2 retries
            try:
                if sdk == "anthropic":
                    return self._anthropic(provider, model, system, user, expect_json, max_tokens, temperature)
                if sdk in ("openai", "openai_azure"):
                    return self._openai(provider, model, system, user, expect_json, max_tokens, temperature,
                                        azure=(sdk == "openai_azure"))
                return {"text": "", "provider": provider["id"], "model": model_id,
                        "ok": False, "error": f"Unsupported sdk {sdk!r}"}
            except Exception as e:  # fail soft — never take the server down over an API error
                last = e
                if not _is_transient(e) or attempt == 2:
                    break
                time.sleep(0.8 * (2 ** attempt))  # 0.8s, 1.6s
        return {"text": "", "provider": provider["id"], "model": model_id,
                "ok": False, "error": f"{type(last).__name__}: {last}"}
```
Add a module-level helper near `extract_json`:
```python
def _is_transient(e: Exception) -> bool:
    """True for errors worth retrying (timeouts, rate limits, 5xx, connection drops)."""
    name = type(e).__name__.lower()
    if any(k in name for k in ("timeout", "connection", "ratelimit", "apiconnection",
                               "internalserver", "serviceunavailable", "overloaded")):
        return True
    status = getattr(e, "status_code", None) or getattr(e, "status", None)
    return status in (408, 409, 429, 500, 502, 503, 504, 529)
```

- [ ] **Step 2: Verify retry-then-succeed and no-retry-on-client-error**

Create `scratchpad/check_retry.py`:
```python
import sys, types; sys.path.insert(0, "backend")
from agent import providers
calls = {"n": 0}
class Boom(Exception):
    def __init__(self): self.status_code = 503
def flaky(self, *a, **k):
    calls["n"] += 1
    if calls["n"] < 2: raise Boom()
    return {"text": "ok", "provider": "anthropic", "model": "x", "ok": True, "error": None}
providers.LLMClient._anthropic = flaky
# Make resolve_model return an anthropic provider for a fake id by monkeypatching:
providers.resolve_model = lambda mid: ({"id":"anthropic","sdk":"anthropic"}, {"id": mid})
r = providers.LLMClient().generate("s", "u", "fake", max_tokens=10)
assert r["ok"] and calls["n"] == 2, (r, calls)
print("OK: retried transient 503 then succeeded after", calls["n"], "calls")
```
Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && python3 scratchpad/check_retry.py`
Expected: `OK: retried transient 503 then succeeded after 2 calls`

- [ ] **Step 3: Commit**
```bash
git add backend/agent/providers.py
git commit -m "feat: retry transient provider errors with exponential backoff"
```

---

### Task 6: Fail-soft ingestion — size cap, missing-parser message, SSRF guard

**Files:**
- Modify: `backend/agent/ingest.py` (`extract_text` import-error message; `fetch_url` SSRF guard + download size cap)
- Modify: `backend/app.py` (set `MAX_CONTENT_LENGTH`; add a 413 JSON handler)

**Interfaces:**
- Produces: oversized uploads → HTTP 413 JSON error; private/loopback URLs → refused with a clear string; missing parser SDK → friendly "install X" string instead of a raw traceback. `MAX_UPLOAD_MB` configurable via env (default 25).

- [ ] **Step 1: Friendlier missing-parser message in `extract_text`**

In `ingest.py`, change the `except Exception as e:` block of `extract_text` (L29-30) to distinguish ImportError:
```python
    except ImportError as e:
        return (f"[parser not installed for {os.path.basename(path)} ({ext}); "
                f"install the matching library (pdfplumber/pypdf, python-docx, or openpyxl): {e}]")
    except Exception as e:
        return f"[ingest error for {os.path.basename(path)}: {type(e).__name__}: {e}]"
```

- [ ] **Step 2: SSRF guard + download size cap in `fetch_url`**

In `fetch_url`, after the `http/https` check (L58-59) and before building the request, add a private-address guard:
```python
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
```
Then cap the download size: change `data = resp.read()` (L65) to:
```python
            max_bytes = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                return f"[refused: {url} exceeds the {max_bytes // (1024*1024)} MB limit]"
```

- [ ] **Step 3: Cap uploads in `app.py`**

After `app = Flask(...)` (L81), add:
```python
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "25"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
```
And add an error handler (near the other route defs):
```python
@app.errorhandler(413)
def _too_large(_e):
    return jsonify({"error": f"Upload exceeds the {MAX_UPLOAD_MB} MB limit."}), 413
```

- [ ] **Step 4: Verify SSRF refusal + missing-parser message shape**

Create `scratchpad/check_ingest.py`:
```python
import sys; sys.path.insert(0, "backend")
from agent.ingest import fetch_url
out = fetch_url("http://127.0.0.1:8000/secret")
assert out.startswith("[refused:"), out
print("OK: SSRF guard refused loopback ->", out[:50])
```
Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && python3 scratchpad/check_ingest.py`
Expected: `OK: SSRF guard refused loopback -> [refused: http://127.0.0.1:8000/secret resolves...`

- [ ] **Step 5: Commit**
```bash
git add backend/agent/ingest.py backend/app.py
git commit -m "feat: fail-soft ingestion — upload size cap, SSRF guard, friendly missing-parser message"
```

---

### Task 7: Wire the dual vote into the evaluate endpoints (still synchronous)

**Files:**
- Modify: `backend/app.py` (`_validate_models`, `_run_and_cache`, `evaluate`, `evaluate_upload`)

**Interfaces:**
- Consumes: `synthesize_vote_dual(ev, openai_model, anthropic_model, synthesizer_model)` (Task 4), `synthesize_vote(ev, model_id)` (existing).
- Produces: both evaluate endpoints accept an optional `vote_dual` object `{openai, anthropic, synthesizer}` (JSON body, or JSON-encoded string form field for multipart). `_run_and_cache` chooses dual vs single. `_validate_models` validates every model in the pair.

- [ ] **Step 1: Extend `_run_and_cache` and `_validate_models`**

Replace `_run_and_cache` (L71-79) with:
```python
def _run_and_cache(vendor, product, proposal_text, scoring_model, vote_model,
                   sample_n=None, vote_dual=None, progress=None, should_cancel=None):
    """Shared evaluate -> vote -> cache path used by both evaluate endpoints."""
    ev = evaluate_vendor(vendor, product, proposal_text,
                         scoring_model=scoring_model, requirement_sample=sample_n,
                         progress=progress)
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
    return result
```
(`should_cancel` is accepted now but used in Task 8; harmless here.) Add `synthesize_vote_dual` to the import from `agent.vote`.

`_validate_models` already loops over `*ids`; no change needed — callers will pass the pair's ids into it.

- [ ] **Step 2: Parse `vote_dual` in `evaluate` (JSON)**

In `evaluate()` after `vote_model = body.get("vote_model", scoring_model)` (L160) add:
```python
    vote_dual = body.get("vote_dual")  # {openai, anthropic, synthesizer} or None
```
Change the validation call (L163) to include the pair when present:
```python
    pair_ids = [vote_dual[k] for k in ("openai", "anthropic", "synthesizer")
                if vote_dual and vote_dual.get(k)] if vote_dual else []
    err = _validate_models(scoring_model, vote_model, *pair_ids)
```
Change the final return (L183) to pass `vote_dual`:
```python
    return jsonify(_run_and_cache(vendor, product, proposal_text, scoring_model,
                                  vote_model, sample_n, vote_dual=vote_dual))
```

- [ ] **Step 3: Parse `vote_dual` in `evaluate_upload` (multipart)**

In `evaluate_upload()` after `vote_model = request.form.get("vote_model", scoring_model)` (L200) add:
```python
    vote_dual = None
    if request.form.get("vote_dual"):
        try:
            vote_dual = json.loads(request.form["vote_dual"])
        except Exception:
            vote_dual = None
    pair_ids = [vote_dual[k] for k in ("openai", "anthropic", "synthesizer")
                if vote_dual and vote_dual.get(k)] if vote_dual else []
```
Change its validation (L204) to `err = _validate_models(scoring_model, vote_model, *pair_ids)`.
Change its `_run_and_cache` call (L234) to pass `vote_dual=vote_dual`.

- [ ] **Step 4: Verify wiring via the running server (mock degrades to single)**

Start the server: `cd backend && python3 app.py` (background). Then:
```bash
curl -s -X POST http://127.0.0.1:8000/api/evaluate -H 'Content-Type: application/json' \
  -d '{"vendor":"IFS","use_sample":true,"scoring_model":"mock","vote_dual":{"openai":"mock","anthropic":"mock","synthesizer":"claude-opus-4-8"}}' \
  | python3 -c "import sys,json; v=json.load(sys.stdin)['vote']; print('mode=',v['mode'],'reco=',v['recommendation'])"
```
Expected: `mode= single reco= ...` (mock pair → single, no crash). Also verify a bad id is rejected:
```bash
curl -s -X POST http://127.0.0.1:8000/api/evaluate -H 'Content-Type: application/json' \
  -d '{"vendor":"IFS","use_sample":true,"vote_dual":{"openai":"nope","anthropic":"claude-opus-4-8"}}'
```
Expected: JSON `{"error":"Unknown model id: 'nope'..."}`. Stop the server.

- [ ] **Step 5: Commit**
```bash
git add backend/app.py
git commit -m "feat: route evaluate endpoints through dual vote when vote_dual is provided"
```

---

### Task 8: Background-job evaluation (progress + cancel)

**Files:**
- Modify: `backend/app.py` (job registry; convert `evaluate`/`evaluate_upload` to return `job_id`; add status + cancel routes)
- Modify: `backend/agent/scoring.py` (`evaluate_vendor` + `_score_requirements` accept a `should_cancel` callback)

**Interfaces:**
- Consumes: `_run_and_cache(..., progress, should_cancel)` (Task 7 added the params).
- Produces:
  - `POST /api/evaluate` and `/api/evaluate_upload` return `{"job_id": "..."}` (202) and run in a worker thread.
  - `GET /api/evaluate/status/<job_id>` → `{stage, scored, total, done, error, result}`.
  - `POST /api/evaluate/cancel/<job_id>` → `{"ok": true}`; scoring stops between batches.
  - `evaluate_vendor(..., should_cancel=None)` and `_score_requirements(..., should_cancel=None)` raise `EvaluationCancelled` when cancelled.

- [ ] **Step 1: Cancellation hook in `scoring.py`**

At the top of `scoring.py` add an exception class:
```python
class EvaluationCancelled(Exception):
    """Raised when a running evaluation is cancelled via the job API."""
```
Add `should_cancel: Optional[Callable[[], bool]] = None` to `evaluate_vendor`'s signature, and pass it into `_score_requirements`:
```python
    req_scores = _score_requirements(vendor, product, proposal_text, reqs, scoring_model, _emit, should_cancel)
```
Change `_score_requirements`'s signature to `(vendor, product, proposal_text, reqs, model_id, emit, should_cancel=None)` and, inside the `for i in range(0, total, BATCH):` loop, add as the first line of the loop body:
```python
        if should_cancel and should_cancel():
            raise EvaluationCancelled()
```
(The mock path returns before the loop; cancellation applies to live scoring, which is the slow path.)

- [ ] **Step 2: Job registry + worker in `app.py`**

After `_RESULTS_LOCK = threading.Lock()` (L85) add:
```python
import uuid
from agent.scoring import EvaluationCancelled

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
                # messages look like "Scored 120/422 requirements…"
                import re as _re
                m = _re.search(r"(\d+)\s*/\s*(\d+)", msg)
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
        with _JOBS_LOCK:
            _JOBS[jid].update(stage="done", done=True, result=result)
    except EvaluationCancelled:
        with _JOBS_LOCK:
            _JOBS[jid].update(stage="cancelled", done=True, error="cancelled")
    except Exception as e:
        with _JOBS_LOCK:
            _JOBS[jid].update(stage="error", done=True, error=f"{type(e).__name__}: {e}")
```

- [ ] **Step 3: Return a job_id from both evaluate endpoints**

In `evaluate()`, replace the final `return jsonify(_run_and_cache(...))` (Task 7 Step 2) with:
```python
    jid = _new_job()
    threading.Thread(target=_run_job, kwargs=dict(
        jid=jid, vendor=vendor, product=product, proposal_text=proposal_text,
        scoring_model=scoring_model, vote_model=vote_model, sample_n=sample_n,
        vote_dual=vote_dual), daemon=True).start()
    return jsonify({"job_id": jid}), 202
```
In `evaluate_upload()`, the result currently has `_ingest` attached. Capture ingest metadata into the job: replace its `result = _run_and_cache(...)` + `result["_ingest"] = {...}` + `return jsonify(result)` block (L234-241) with:
```python
    ingest_meta = {
        "files": [os.path.basename(p) for p in saved_paths],
        "urls": urls, "rejected": rejected, "chars_extracted": len(proposal_text),
    }
    jid = _new_job()
    with _JOBS_LOCK:
        _JOBS[jid]["ingest"] = ingest_meta
    threading.Thread(target=_run_job, kwargs=dict(
        jid=jid, vendor=vendor, product=product, proposal_text=proposal_text,
        scoring_model=scoring_model, vote_model=vote_model, sample_n=sample_n,
        vote_dual=vote_dual), daemon=True).start()
    return jsonify({"job_id": jid}), 202
```
(So `_run_job` attaches `_ingest` to the result when present — add this inside `_run_job` right after computing `result`:)
```python
        with _JOBS_LOCK:
            if "ingest" in _JOBS[jid]:
                result["_ingest"] = _JOBS[jid]["ingest"]
```

- [ ] **Step 4: Status + cancel routes**

Add near the other action routes:
```python
@app.route("/api/evaluate/status/<job_id>")
def evaluate_status(job_id):
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return jsonify({"error": "unknown job"}), 404
        return jsonify({k: j[k] for k in ("stage", "scored", "total", "done", "error", "result")})


@app.route("/api/evaluate/cancel/<job_id>", methods=["POST"])
def evaluate_cancel(job_id):
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return jsonify({"error": "unknown job"}), 404
        j["cancel"] = True
    return jsonify({"ok": True})
```

- [ ] **Step 5: Verify job lifecycle (mock is fast; confirm shape)**

Start `cd backend && python3 app.py` (background). Then:
```bash
JID=$(curl -s -X POST http://127.0.0.1:8000/api/evaluate -H 'Content-Type: application/json' \
  -d '{"vendor":"IFS","use_sample":true,"scoring_model":"mock","vote_model":"mock"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
echo "job=$JID"
sleep 1
curl -s http://127.0.0.1:8000/api/evaluate/status/$JID \
  | python3 -c "import sys,json;j=json.load(sys.stdin);print('done=',j['done'],'stage=',j['stage'],'has_result=',bool(j['result']))"
```
Expected: `done= True stage= done has_result= True`. Cancel path (best-effort on the fast mock — just confirm the route works):
```bash
curl -s -X POST http://127.0.0.1:8000/api/evaluate/cancel/$JID | python3 -c "import sys,json;print(json.load(sys.stdin))"
```
Expected: `{'ok': True}`. Stop the server.

- [ ] **Step 6: Commit**
```bash
git add backend/app.py backend/agent/scoring.py
git commit -m "feat: background-job evaluation with progress polling and cancel"
```

---

### Task 9: Frontend — split model selection, dual-vote render, job progress, errors

**Files:**
- Modify: `frontend/index.html` (`ModelSelector` → richer controls; `App` state; `RunBar` job polling; vote-detail render)

**Interfaces:**
- Consumes: `/api/models` (provider/key data), `POST /api/evaluate*` → `{job_id}`, `GET /api/evaluate/status/<id>`, `POST /api/evaluate/cancel/<id>`; `vote.mode/raw_votes/disagreements/note`.
- Produces: UI sends `scoring_model` + (`vote_model` or `vote_dual`), polls jobs, renders the two-model read.

- [ ] **Step 1: App-level state for scoring/vote selection**

In `App()` (L648-651) replace the single `model` state with three pieces (keep `model` as the scoring model so existing props still resolve):
```javascript
  const [models,setModels]=useState(null);
  const [model,setModel]=useState("mock");        // scoring model
  const [voteMode,setVoteMode]=useState("single"); // "single" | "dual"
  const [voteModel,setVoteModel]=useState("mock");  // single-vote model
  const [voteDual,setVoteDual]=useState({openai:"",anthropic:"",synthesizer:"claude-opus-4-8"});
```
In the init effect (L661) after setting `model`, seed the vote defaults from `task_defaults`:
```javascript
      const td = m.task_defaults || {};
      const has = id => m.providers.some(p=>p.key_present && p.models.some(x=>x.id===id));
      setVoteModel(has(td.vote_synthesis) ? td.vote_synthesis : m.default_model);
      if(td.dual_vote) setVoteDual({openai:td.dual_vote.openai||"", anthropic:td.dual_vote.anthropic||"", synthesizer:td.dual_vote.synthesizer||"claude-opus-4-8"});
```

- [ ] **Step 2: Replace `ModelSelector` with scoring + vote controls**

Replace the `ModelSelector` component (L234-253) with a `ModelControls` component that renders a scoring picker, a single/dual toggle, and the dual pair pickers. (A flat `<option>` list helper avoids repeating the optgroup logic.)
```javascript
function modelOptions(models){
  return models.providers.flatMap(p=>p.models.map(m=>({
    id:m.id, label:m.label, group:p.name,
    disabled: !p.key_present && p.id!=="mock"
  })));
}
function Picker({models,value,onChange,title}){
  return (
    <select title={title||""} value={value} onChange={e=>onChange(e.target.value)}
            style={{fontFamily:"var(--font)",fontSize:12,padding:"6px 8px",borderRadius:6,
                    border:"1px solid rgba(255,255,255,.4)",background:"rgba(255,255,255,.12)",color:"#fff"}}>
      {models.providers.map(p=>(
        <optgroup key={p.id} label={p.name+(p.key_present?"":" (no key)")}>
          {p.models.map(m=>(<option key={m.id} value={m.id} disabled={!p.key_present && p.id!=="mock"}
             style={{color:"#000"}}>{m.label}{!p.key_present&&p.id!=="mock"?" — key missing":""}</option>))}
        </optgroup>
      ))}
    </select>
  );
}
function ModelControls({models, scoring, setScoring, voteMode, setVoteMode, voteModel, setVoteModel, voteDual, setVoteDual}){
  if(!models) return null;
  return (
    <div className="modelsel" style={{gap:12,flexWrap:"wrap"}}>
      <span style={{display:"flex",alignItems:"center",gap:6}}>
        <label>Scoring</label><Picker models={models} value={scoring} onChange={setScoring}/>
      </span>
      <span style={{display:"flex",alignItems:"center",gap:6}}>
        <label>Vote</label>
        <select value={voteMode} onChange={e=>setVoteMode(e.target.value)}
                style={{fontSize:12,padding:"6px 8px",borderRadius:6,border:"1px solid rgba(255,255,255,.4)",background:"rgba(255,255,255,.12)",color:"#fff"}}>
          <option value="single" style={{color:"#000"}}>Single model</option>
          <option value="dual" style={{color:"#000"}}>Dual (two-model read)</option>
        </select>
      </span>
      {voteMode==="single"
        ? <Picker models={models} value={voteModel} onChange={setVoteModel} title="Vote model"/>
        : <span style={{display:"flex",alignItems:"center",gap:6}}>
            <Picker models={models} value={voteDual.openai} onChange={v=>setVoteDual({...voteDual,openai:v})} title="OpenAI vote model"/>
            <span style={{opacity:.7}}>+</span>
            <Picker models={models} value={voteDual.anthropic} onChange={v=>setVoteDual({...voteDual,anthropic:v})} title="Anthropic vote model"/>
            <span className="keypill" title="Reconciler (fixed)">↻ Opus 4.8 reconciles</span>
          </span>}
    </div>
  );
}
```
In the header (L684) replace `<ModelSelector .../>` with:
```javascript
          <ModelControls models={models} scoring={model} setScoring={setModel}
            voteMode={voteMode} setVoteMode={setVoteMode} voteModel={voteModel} setVoteModel={setVoteModel}
            voteDual={voteDual} setVoteDual={setVoteDual}/>
```

- [ ] **Step 3: Thread the vote selection into `RunBar` and poll the job**

Change the `RunBar` call site (find `<RunBar vendors={vendors} model={model} onDone={loadResults}/>`) to:
```javascript
        <RunBar vendors={vendors} model={model} voteMode={voteMode} voteModel={voteModel} voteDual={voteDual} onDone={loadResults}/>
```
In `RunBar`'s signature (L557) add the props: `function RunBar({vendors, model, voteMode, voteModel, voteDual, onDone})`. Add a progress state near the others: `const [prog,setProg]=useState(null); const [jobId,setJobId]=useState(null);`

Replace the `run(useSample)` function body (L570-596) with a version that submits, then polls the job:
```javascript
  function votePayload(){
    return voteMode==="dual" ? {vote_dual: voteDual} : {vote_model: voteModel};
  }
  async function poll(jid){
    setJobId(jid);
    while(true){
      await new Promise(r=>setTimeout(r,900));
      const s=await jget("/api/evaluate/status/"+jid);
      if(s.error){ setBusy(false); setProg(null); setJobId(null); setMsg({ok:false,text:"Error: "+s.error}); return; }
      setProg(s.total? `${s.stage} (${s.scored}/${s.total})` : s.stage);
      if(s.done){
        setBusy(false); setProg(null); setJobId(null);
        if(s.error){ setMsg({ok:false,text:"Error: "+s.error}); }
        else {
          const res=s.result, ing=res._ingest;
          setMsg({ok:true, text:`Done — ${vendor}: ${res.vote.recommendation} (${fmt(res.weighted_total)}/100).`,
                  ingest: ing? `Ingested ${ing.files.length} file(s)${ing.urls.length?` + ${ing.urls.length} URL(s)`:""}, ${ing.chars_extracted.toLocaleString()} chars${ing.rejected.length?` · rejected: ${ing.rejected.join(", ")}`:""}.`:null});
          onDone();
        }
        return;
      }
    }
  }
  async function run(useSample){
    if(!vendor) return;
    setBusy(true); setProg("Starting…");
    setMsg({ok:true, text:`Evaluating ${vendor}…`});
    if(STATIC){
      const res=await jpost("/api/evaluate",{vendor}); setBusy(false);
      if(res.error) setMsg({ok:false,text:"Error: "+res.error});
      else { setMsg({ok:true,text:`${vendor}: ${res.vote.recommendation} (${fmt(res.weighted_total)}/100).`}); onDone(); }
      return;
    }
    let jid;
    if(useSample){
      const res=await jpost("/api/evaluate",{vendor,product:"",use_sample:true,scoring_model:model,...votePayload()});
      if(res.error){ setBusy(false); setMsg({ok:false,text:"Error: "+res.error}); return; }
      jid=res.job_id;
    } else {
      const fd=new FormData();
      fd.append("vendor",vendor); fd.append("scoring_model",model);
      if(voteMode==="dual") fd.append("vote_dual",JSON.stringify(voteDual)); else fd.append("vote_model",voteModel);
      fd.append("urls",urls); files.forEach(f=>fd.append("files",f));
      const r=await fetch("/api/evaluate_upload",{method:"POST",body:fd});
      const res=await r.json();
      if(res.error){ setBusy(false); setMsg({ok:false,text:"Error: "+res.error}); return; }
      jid=res.job_id;
    }
    poll(jid);
  }
  async function cancel(){ if(jobId) await jpost("/api/evaluate/cancel/"+jobId,{}); }
```
In the controls row, show progress + a cancel button while busy. After the existing Run buttons block, add:
```javascript
        {busy && !STATIC && <span className="small" style={{display:"flex",alignItems:"center",gap:8}}>
          <span className="spin"/>{prog||"Working…"}
          <button className="btn ghost" onClick={cancel} style={{padding:"4px 10px"}}>Cancel</button>
        </span>}
```

- [ ] **Step 4: Render the two-model read in the vote section**

In the vendor-detail vote card (L340-352), after the existing dissent line, add a dual panel:
```javascript
        {r.vote.note && <div className="small muted" style={{marginTop:8}}>ℹ {r.vote.note}</div>}
        {r.vote.mode==="dual" && r.vote.raw_votes.length>0 && <div style={{marginTop:14}}>
          <div className="section-title" style={{marginTop:0}}>Two-model read</div>
          <div className="grid vote-columns">
            {r.vote.raw_votes.map((rv,i)=>(
              <div key={i} className="card" style={{padding:14}}>
                <b className="small" style={{color:"var(--ssa-blue)"}}>{rv.provider==="openai"?"OpenAI":"Anthropic"} <span className="muted">({rv.model})</span></b>
                <p className="small" style={{marginTop:6}}>{rv.narrative}</p>
                {rv.dissent && <p className="small muted" style={{marginTop:6}}><b>Dissent:</b> {rv.dissent}</p>}
              </div>
            ))}
          </div>
          {r.vote.disagreements.length>0 && <div className="small" style={{marginTop:10}}>
            <b>Where they disagreed</b>
            <ul style={{margin:"6px 0 0 16px",padding:0}}>
              {r.vote.disagreements.map((d,i)=>(<li key={i}><b>{d.dimension}:</b> OpenAI — {d.openai_position}; Anthropic — {d.anthropic_position}. <i>Resolved:</i> {d.resolution}</li>))}
            </ul></div>}
        </div>}
```

- [ ] **Step 5: Verify in the browser (headless screenshot)**

Restart the server, render the page, and screenshot to confirm the controls render and the single-mode vote still shows:
```bash
cd backend && python3 app.py &   # background
SP="/tmp/claude-1000/-home-chagood-workspace-projects-RFP-Agent-FSM-Scoring-Agent/b8bc3f98-10e6-4167-bcaa-b007f9b186a5/scratchpad"
google-chrome --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=1500,900 --virtual-time-budget=4000 --screenshot=$SP/dual_ui.png http://127.0.0.1:8000/
```
Read `$SP/dual_ui.png`. Expected: header shows **Scoring** picker + **Vote** single/dual toggle; switching to Dual (manually, when verifying interactively) reveals the OpenAI + Anthropic pickers and the "Opus 4.8 reconciles" pill. The Dashboard and an open vendor's single-mode vote render unchanged. Stop the server.

- [ ] **Step 6: Commit**
```bash
git add frontend/index.html
git commit -m "feat: split scoring/vote model selection, dual-vote render, job progress + cancel"
```

---

### Task 10: Rebuild standalone, refresh graph, full offline-demo verification

**Files:**
- Regenerate: `FSM_Evaluation_Agent_Standalone.html` (via `build_static.py`)
- Update: `graphify-out/` (via `graphify update .`)

- [ ] **Step 1: Rebuild the standalone bundle**

Run: `cd backend && python3 build_static.py`
Expected: `Wrote .../FSM_Evaluation_Agent_Standalone.html (… KB)`. Confirm the new UI is bundled:
```bash
grep -c "ModelControls" "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent/FSM_Evaluation_Agent_Standalone.html"
```
Expected: `≥ 1`.

- [ ] **Step 2: Verify the offline demo still works end-to-end**

Render the standalone file directly (no server) and screenshot:
```bash
SP="/tmp/claude-1000/-home-chagood-workspace-projects-RFP-Agent-FSM-Scoring-Agent/b8bc3f98-10e6-4167-bcaa-b007f9b186a5/scratchpad"
google-chrome --headless --disable-gpu --no-sandbox --hide-scrollbars --window-size=1500,900 --virtual-time-budget=4000 --screenshot=$SP/standalone.png "file:///home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent/FSM_Evaluation_Agent_Standalone.html"
```
Read `$SP/standalone.png`. Expected: dashboard renders with the 5 seeded vendors; no JS errors; the header controls show (Scoring/Vote). The mock-only standalone has no live keys, so dual is inert — that's correct.

- [ ] **Step 3: Live server smoke (mock engine, no keys)**

`cd backend && python3 app.py` (background); `curl -s http://127.0.0.1:8000/api/health` → `{"live_models_available":false,...,"ok":true}`; `curl -s http://127.0.0.1:8000/api/results | python3 -c "import sys,json;print(len(json.load(sys.stdin)),'vendors')"` → `5 vendors`. Stop the server.

- [ ] **Step 4: Refresh the knowledge graph**

Run: `cd "/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent" && graphify update .`
Expected: completes without error (AST-only, no API cost).

- [ ] **Step 5: Commit**
```bash
git add FSM_Evaluation_Agent_Standalone.html graphify-out
git commit -m "build: rebuild standalone bundle and refresh knowledge graph"
```

---

## Self-review notes (author)

- **Spec coverage:** §0 fix → Task 1; §4 `.env` → Task 2; §5 schema → Task 3; §5 engine → Task 4; §7.2 retry → Task 5; §7.3 ingestion → Task 6; §5.3 wiring → Task 7; §7.1 background jobs → Task 8; §6 frontend → Task 9; §8 verification + standalone/graph → throughout + Task 10. §9 roadmap is intentionally not built.
- **No persisted tests** by project convention; every task ends with a runnable verification + commit (skill TDD adapted to the codebase's manual-verification model — see Global Constraints).
- **Type/name consistency:** `synthesize_vote_dual(ev, openai_model, anthropic_model, synthesizer_model)` is defined in Task 4 and called with those names in Task 7; `_run_and_cache(..., vote_dual, progress, should_cancel)` defined in Task 7 and called in Task 8; `EvaluationCancelled` defined in Task 8 Step 1 and imported in Step 2; job status keys (`stage/scored/total/done/error/result`) match between Task 8 (`evaluate_status`) and Task 9 (`poll`); `vote.mode/raw_votes/disagreements/note` match between Task 3 schema, Task 4 engine, and Task 9 render.
- **Known external unknown:** the `gpt-5.5` id (Task 1) is flagged `verify_id` and never exercised until an OpenAI key exists.
