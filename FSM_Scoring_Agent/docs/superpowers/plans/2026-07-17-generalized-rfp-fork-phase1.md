# Generalized RFP Evaluation Fork — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a new private repo where a consultant can create a project, upload an Excel of requirements + categories, evaluate vendors against it (mock engine keyless, live models optional), and get gated, weighted results stored in SQLite.

**Architecture:** Fork of FSM_Scoring_Agent with the singleton knowledge base replaced by a per-request `ProjectContext` keyed by `project_id`, all state in SQLite, and category rollups extracted into a pure function so weights can change without LLM calls. Spec: `docs/superpowers/specs/2026-07-17-generalized-rfp-fork-design.md` in the parent repo.

**Tech Stack:** Python 3.12, Flask, sqlite3 (stdlib), openpyxl, React 18 via CDN + Babel standalone (no build toolchain), pytest (dev only).

## Global Constraints

- New private GitHub repo `chagood8/rfp-eval-agent`. No git history from the parent — parent history contains Service Logic client data.
- `python3` (there is no `python` alias in this environment).
- Flask + openpyxl are required deps; LLM SDKs optional; pytest dev-only.
- API keys come from env at call time, never disk. Missing key = clear error string, never a crash.
- The offline mock engine must work end-to-end with zero keys and no network.
- Every API route except health/login/logout/session gets `@require_auth` (auth.py carries over unchanged).
- Every project-scoped API call carries `project_id` in the path. No global "active project" server state.
- Priority multipliers default Must 3.0 / Should 2.0 / Could 1.0; stored per project, editable.
- "Won't" requirements are stored but excluded from scoring, rollups, and gating.
- Gating is deterministic, computed from stored scores, never LLM-overridable.
- Default gating config: unmet Must disqualifies; response codes GAP and ROADMAP on a Must gate; CUSTOM does not.
- Response-code vocabulary (kept from parent): OOB, CONFIG, EXTENSION, CUSTOM, PARTNER, ROADMAP, GAP.
- SQLite file at `backend/data/app.db`, overridable via `DB_PATH` env var. WAL mode.
- No TypeScript, no npm, no bundler. Frontend split into `<script type="text/babel" src=...>` files served by Flask.
- `git push` requires user approval per the user's permissions policy — pause and ask at every push step.

## File structure of the fork (end of Phase 1)

```
backend/
  app.py                Flask app: auth, project/vendor/intake/evaluate/chat routes
  auth.py               unchanged from parent
  db.py                 NEW — SQLite connection, schema, init
  requirements.txt      flask, openpyxl (+ optional LLM SDKs commented)
  agent/
    project_context.py  NEW — replaces knowledge.py singleton
    rollup.py           NEW — pure rollup(scores, ...) math
    intake.py           NEW — Excel template + parse/validate/commit
    scoring.py          rewritten generic (batched LLM scoring + mock engine)
    vote.py             generalized (bands from rollup, narrative via LLM/mock)
    chat.py             per-project retrieval Q&A
    ingest.py           kept minus matrix functions
    providers.py        unchanged from parent
    schemas.py          slimmed (RequirementScore, CategoryScore, GatingResult, Vote, VendorEvaluation)
  config/
    persona.json        neutral evidence-first evaluator (structure kept, FSM content removed)
    models.json         unchanged from parent
  tests/
    conftest.py, test_db.py, test_rollup.py, test_context.py,
    test_projects_api.py, test_intake.py, test_scoring.py, test_vote.py, test_evaluate_api.py
    fixtures/rollup_fixture.json   shared Python/JS ground truth (JS side lands Phase 2)
frontend/
  index.html            shell only: head, CDN scripts, mount div, script tags
  js/api.js  js/util.js  js/components.js  js/projects.js  js/evaluation.js  js/app.js
CLAUDE.md, README.md
```

Deleted relative to parent: `capabilities.json`, `segments.json`, `vendor_research.json`, `knowledge.py`, `sample.py`, `matrix_llm.py`, `migrate_decision_rubric.py`, `committee.py`, `build_static.py` (returns in Phase 3), `data/requirements.json`, `data/sample_results.json`, `docs/`, `outputs/`, `graphify-out/`, `FSM_Evaluation_Agent_Standalone.html`, SSA logo b64 files stay (branding is fine).

---

### Task 1: Seed the private fork repo

**Files:**
- Create: `~/workspace/projects/rfp-eval-agent/` (new working tree, copied + cleaned)

**Interfaces:**
- Produces: a pushed `main` branch every later task builds on. All later paths are relative to the new repo root.

- [ ] **Step 1: Copy the parent tree without git history or FSM data**

```bash
SRC="/home/chagood/workspace/projects/RFP Agent/FSM_Scoring_Agent"
DST="$HOME/workspace/projects/rfp-eval-agent"
mkdir -p "$DST"
rsync -a "$SRC/" "$DST/" \
  --exclude '.git' --exclude 'graphify-out' --exclude 'docs' --exclude 'outputs' \
  --exclude 'FSM_Evaluation_Agent_Standalone.html' --exclude '__pycache__' \
  --exclude '.claude'
```

- [ ] **Step 2: Delete FSM-specific modules and data (use git-free paths; this is the cleaned copy, not the parent)**

Delete these files inside `$DST`:
`backend/agent/knowledge.py`, `backend/agent/sample.py`, `backend/agent/matrix_llm.py`, `backend/agent/migrate_decision_rubric.py`, `backend/agent/committee.py`, `backend/build_static.py`, `backend/config/capabilities.json`, `backend/config/segments.json`, `backend/config/vendor_research.json`, `backend/data/requirements.json`, `backend/data/sample_results.json`.

Deleting via the file manager or `rm` is a blocklisted command — ask the user to approve the single cleanup command rather than working around it:

```bash
cd "$HOME/workspace/projects/rfp-eval-agent"
rm backend/agent/knowledge.py backend/agent/sample.py backend/agent/matrix_llm.py \
   backend/agent/migrate_decision_rubric.py backend/agent/committee.py \
   backend/build_static.py backend/config/capabilities.json backend/config/segments.json \
   backend/config/vendor_research.json backend/data/requirements.json backend/data/sample_results.json
```

- [ ] **Step 3: Verify nothing Service Logic-specific remains in config/data**

```bash
cd "$HOME/workspace/projects/rfp-eval-agent"
grep -ril "service logic\|opco\|hvac" backend/config backend/data || echo CLEAN
```

Expected: `backend/config/persona.json` still matches (rewritten in Task 4); nothing else. `backend/agent/*.py` will still reference deleted modules — that is expected; imports get fixed task by task, and the app is not runnable until Task 10.

- [ ] **Step 4: git init, first commit, create the private repo, push**

```bash
cd "$HOME/workspace/projects/rfp-eval-agent"
git init -b main
printf '__pycache__/\n*.pyc\nbackend/data/app.db*\n.env\n' > .gitignore
git add -A
git commit -m "chore: seed fork from FSM_Scoring_Agent (cleaned copy, no history)"
gh repo create chagood8/rfp-eval-agent --private --source . --push
```

STOP and get user approval before the `gh repo create ... --push` (it pushes). Expected: repo visible at github.com/chagood8/rfp-eval-agent, private.

---

### Task 2: Test harness + SQLite layer (`db.py`)

**Files:**
- Create: `backend/db.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_db.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `db.connect(path=None) -> sqlite3.Connection` (row_factory=Row, FK on, WAL); `db.init_db(conn)` idempotent schema creation; `db.get_db()` Flask per-request connection bound to `flask.g`; `db.close_db(e=None)` teardown; module constant `db.DEFAULT_DB_PATH = backend/data/app.db` honoring `DB_PATH` env.

- [ ] **Step 1: Add deps**

`backend/requirements.txt` — make `openpyxl` required (it is currently optional) and add a dev note:

```
flask>=3.0
openpyxl>=3.1
# dev: pip install pytest
# optional LLM SDKs: anthropic, openai
# optional parsers: pypdf, python-docx
```

- [ ] **Step 2: Write failing tests**

`backend/tests/conftest.py`:

```python
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
import db as dbmod

@pytest.fixture()
def conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    c = dbmod.connect(path)
    dbmod.init_db(c)
    yield c
    c.close()
    os.unlink(path)
```

`backend/tests/test_db.py`:

```python
import db as dbmod

def test_schema_tables_exist(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert {"projects", "categories", "requirements", "weight_profiles",
            "vendors", "evaluations", "requirement_scores", "scenarios"} <= names

def test_init_db_is_idempotent(conn):
    dbmod.init_db(conn)  # second call must not raise

def test_foreign_keys_enforced(conn):
    import sqlite3, pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO categories (project_id, name, default_weight, sort_order)"
                     " VALUES (999, 'X', 10, 0)")

def test_project_insert_roundtrip(conn):
    cur = conn.execute(
        "INSERT INTO projects (name, client, context_brief) VALUES (?,?,?)",
        ("ERP RFP", "Acme", "Mid-market ERP selection"))
    row = conn.execute("SELECT * FROM projects WHERE id=?", (cur.lastrowid,)).fetchone()
    assert row["name"] == "ERP RFP"
    assert row["status"] == "active"
    import json
    gating = json.loads(row["gating_config"])
    assert gating["gate_priorities"] == ["Must"]
    assert "CUSTOM" not in gating["gating_codes"]
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_db.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 4: Implement `backend/db.py`**

```python
"""SQLite layer. One file, WAL mode, stdlib only. Schema is created idempotently."""
import json, os, sqlite3
from flask import g

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.environ.get("DB_PATH", os.path.join(_HERE, "data", "app.db"))

DEFAULT_GATING = {
    "gate_priorities": ["Must"],          # unmet requirement at these priorities gates
    "gating_codes": ["GAP", "ROADMAP"],   # these codes on a gated priority disqualify
    "unmet_met_values": ["No"],           # met values that count as unmet
    "verdict": "Disqualified",            # or "Reject"
}
DEFAULT_MULTIPLIERS = {"Must": 3.0, "Should": 2.0, "Could": 1.0}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  client TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  context_brief TEXT DEFAULT '',
  gating_config TEXT NOT NULL,
  priority_multipliers TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  default_weight REAL NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS requirements (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  ext_id TEXT NOT NULL,
  text TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  priority TEXT NOT NULL CHECK (priority IN ('Must','Should','Could','Wont')),
  section_label TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  UNIQUE (project_id, ext_id)
);
CREATE TABLE IF NOT EXISTS weight_profiles (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  weights TEXT NOT NULL,             -- JSON {category_id(str): weight(float 0..100)}
  is_active INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS vendors (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  dossier_text TEXT DEFAULT '',
  UNIQUE (project_id, name)
);
CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'running',   -- running | done | failed | cancelled
  scoring_model TEXT NOT NULL,
  vote_model TEXT NOT NULL,
  weight_profile_id INTEGER REFERENCES weight_profiles(id),
  vote TEXT,                                -- JSON Vote
  engine_warning TEXT DEFAULT '',
  is_demo INTEGER NOT NULL DEFAULT 0,
  proposal_text TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS requirement_scores (
  evaluation_id INTEGER NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
  requirement_id INTEGER NOT NULL REFERENCES requirements(id) ON DELETE CASCADE,
  met TEXT NOT NULL,
  quality INTEGER NOT NULL,
  response_code TEXT NOT NULL,
  confidence TEXT NOT NULL,
  rationale TEXT DEFAULT '',
  evidence_gap TEXT DEFAULT '',
  scored_live INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (evaluation_id, requirement_id)
);
CREATE TABLE IF NOT EXISTS scenarios (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  weights TEXT NOT NULL,
  archetypes TEXT NOT NULL DEFAULT '[]',
  notes TEXT DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

def connect(path=None):
    conn = sqlite3.connect(path or DEFAULT_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db(conn):
    conn.executescript(_SCHEMA)
    # column defaults that need JSON can't live in DDL cleanly; enforce at insert
    conn.commit()

def new_project(conn, name, client="", context_brief=""):
    cur = conn.execute(
        "INSERT INTO projects (name, client, context_brief, gating_config, priority_multipliers)"
        " VALUES (?,?,?,?,?)",
        (name, client, context_brief,
         json.dumps(DEFAULT_GATING), json.dumps(DEFAULT_MULTIPLIERS)))
    conn.commit()
    return cur.lastrowid

def get_db():
    if "db" not in g:
        g.db = connect()
        init_db(g.db)
    return g.db

def close_db(e=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()
```

Note for the test in Task 2 Step 2: `test_project_insert_roundtrip` inserts directly with raw SQL and expects `gating_config` defaults — that only holds via `new_project()`. Fix the test to call `dbmod.new_project(conn, "ERP RFP", "Acme", "Mid-market ERP selection")` and then SELECT. (Written here so implementer and reviewer agree: raw INSERT without gating_config must fail NOT NULL — that is intentional.)

- [ ] **Step 5: Run tests**

Run: `cd backend && python3 -m pytest tests/test_db.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add backend/db.py backend/tests backend/requirements.txt
git commit -m "feat: SQLite layer with schema, defaults, and Flask request binding"
```

---

### Task 3: Pure rollup engine (`rollup.py`) + shared fixture

**Files:**
- Create: `backend/agent/rollup.py`, `backend/tests/test_rollup.py`, `backend/tests/fixtures/rollup_fixture.json`

**Interfaces:**
- Consumes: nothing from other tasks — pure functions over plain dicts (JSON-friendly so the math ports to JS in Phase 2).
- Produces:
  - `rollup(scores, categories, weights, priority_multipliers, gating_config) -> dict` where
    `scores` = list of dicts `{requirement_id, category_id, priority, met, quality, response_code, confidence}`;
    `categories` = list of `{id, name}`; `weights` = `{category_id(str|int): float}` summing to ~100;
    returns `{"category_scores": [{id, name, weight, raw_1_5, weighted_points, n_scored}], "weighted_total": float, "gating": {"disqualified": bool, "verdict": str|None, "unmet_gating": [{requirement_id, priority, response_code, met}], "summary": str}}`.
  - `rank_vendors(rollups: dict[str, dict]) -> list[str]` vendor names sorted by weighted_total desc, disqualified last.

- [ ] **Step 1: Write the fixture (ground truth by hand)**

`backend/tests/fixtures/rollup_fixture.json` — small enough to verify by hand, rich enough to catch drift. Two categories, five scores. Hand math below.

```json
{
  "categories": [{"id": 1, "name": "Functional"}, {"id": 2, "name": "Technical"}],
  "weights": {"1": 60, "2": 40},
  "priority_multipliers": {"Must": 3.0, "Should": 2.0, "Could": 1.0},
  "gating_config": {"gate_priorities": ["Must"], "gating_codes": ["GAP", "ROADMAP"],
                    "unmet_met_values": ["No"], "verdict": "Disqualified"},
  "scores": [
    {"requirement_id": 1, "category_id": 1, "priority": "Must",   "met": "Yes",     "quality": 5, "response_code": "OOB",    "confidence": "High"},
    {"requirement_id": 2, "category_id": 1, "priority": "Should", "met": "Partial", "quality": 3, "response_code": "CONFIG", "confidence": "Medium"},
    {"requirement_id": 3, "category_id": 1, "priority": "Could",  "met": "No",      "quality": 1, "response_code": "GAP",    "confidence": "High"},
    {"requirement_id": 4, "category_id": 2, "priority": "Must",   "met": "Yes",     "quality": 4, "response_code": "CUSTOM", "confidence": "Medium"},
    {"requirement_id": 5, "category_id": 2, "priority": "Must",   "met": "N/A",     "quality": 0, "response_code": "GAP",    "confidence": "Low"}
  ],
  "expected": {
    "category_raw": {"1": 3.67, "2": 4.0},
    "weighted_total": 76.04,
    "disqualified": false
  }
}
```

Hand math (verify before trusting the code): category 1 = (3·5 + 2·3 + 1·1)/(3+2+1) = 22/6 = 3.667 → round 3.67. Requirement 5 is met=N/A so it is excluded; category 2 has only requirement 4 → raw 4.0. Weighted total = 60·(3.67/5) + 40·(4.0/5) = 44.04 + 32.0 = 76.04. Requirement 3 is a Could with GAP — Could does not gate. Requirement 4 is a Must answered CUSTOM with met=Yes — CUSTOM does not gate. Not disqualified.

- [ ] **Step 2: Write failing tests**

`backend/tests/test_rollup.py`:

```python
import json, os
from agent.rollup import rollup, rank_vendors

FIX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "rollup_fixture.json")))

def _run():
    return rollup(FIX["scores"], FIX["categories"], FIX["weights"],
                  FIX["priority_multipliers"], FIX["gating_config"])

def test_fixture_category_raw():
    r = _run()
    raw = {str(c["id"]): c["raw_1_5"] for c in r["category_scores"]}
    assert raw == FIX["expected"]["category_raw"]

def test_fixture_weighted_total():
    assert _run()["weighted_total"] == FIX["expected"]["weighted_total"]

def test_fixture_not_disqualified():
    assert _run()["gating"]["disqualified"] is False

def test_unmet_must_gap_disqualifies():
    scores = [dict(FIX["scores"][0], met="No", response_code="GAP")]
    r = rollup(scores, FIX["categories"], FIX["weights"],
               FIX["priority_multipliers"], FIX["gating_config"])
    assert r["gating"]["disqualified"] is True
    assert r["gating"]["verdict"] == "Disqualified"
    assert r["gating"]["unmet_gating"][0]["requirement_id"] == 1

def test_unmet_must_custom_does_not_disqualify():
    scores = [dict(FIX["scores"][0], met="No", response_code="CUSTOM")]
    r = rollup(scores, FIX["categories"], FIX["weights"],
               FIX["priority_multipliers"], FIX["gating_config"])
    assert r["gating"]["disqualified"] is False

def test_wont_and_na_excluded():
    scores = FIX["scores"] + [
        {"requirement_id": 9, "category_id": 1, "priority": "Wont", "met": "No",
         "quality": 1, "response_code": "GAP", "confidence": "High"}]
    r = rollup(scores, FIX["categories"], FIX["weights"],
               FIX["priority_multipliers"], FIX["gating_config"])
    assert r["weighted_total"] == FIX["expected"]["weighted_total"]
    assert r["gating"]["disqualified"] is False

def test_empty_category_scores_zero():
    r = rollup([FIX["scores"][0]], FIX["categories"], FIX["weights"],
               FIX["priority_multipliers"], FIX["gating_config"])
    raw = {str(c["id"]): c["raw_1_5"] for c in r["category_scores"]}
    assert raw["2"] == 0.0

def test_rank_vendors_dq_last():
    good = _run()
    dq = rollup([dict(FIX["scores"][0], met="No", response_code="GAP")],
                FIX["categories"], FIX["weights"],
                FIX["priority_multipliers"], FIX["gating_config"])
    assert rank_vendors({"A": dq, "B": good}) == ["B", "A"]
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_rollup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.rollup'`

- [ ] **Step 4: Implement `backend/agent/rollup.py`**

```python
"""Pure rollup math. No I/O, no LLM, no Flask — plain dicts in, plain dict out.
This is the single source of truth for weighted totals and gating; the JS port
(Phase 2) must pass tests/fixtures/rollup_fixture.json byte-for-byte."""

def rollup(scores, categories, weights, priority_multipliers, gating_config):
    scorable = [s for s in scores if s["priority"] != "Wont" and s["met"] != "N/A"]

    category_scores = []
    total = 0.0
    for cat in categories:
        cid = cat["id"]
        subset = [s for s in scorable if s["category_id"] == cid]
        num = den = 0.0
        for s in subset:
            w = priority_multipliers.get(s["priority"], 1.0)
            num += w * s["quality"]
            den += w
        raw = round(num / den, 2) if den else 0.0
        weight = float(weights.get(str(cid), weights.get(cid, 0.0)))
        weighted = round(weight * (raw / 5.0), 2)
        total += weighted
        category_scores.append({"id": cid, "name": cat["name"], "weight": weight,
                                "raw_1_5": raw, "weighted_points": weighted,
                                "n_scored": len(subset)})

    gate_prios = set(gating_config.get("gate_priorities", ["Must"]))
    gate_codes = set(gating_config.get("gating_codes", ["GAP", "ROADMAP"]))
    unmet_vals = set(gating_config.get("unmet_met_values", ["No"]))
    unmet = [
        {"requirement_id": s["requirement_id"], "priority": s["priority"],
         "response_code": s["response_code"], "met": s["met"]}
        for s in scorable
        if s["priority"] in gate_prios and s["met"] in unmet_vals
        and s["response_code"] in gate_codes
    ]
    disqualified = bool(unmet)
    verdict = gating_config.get("verdict", "Disqualified") if disqualified else None
    summary = (f"{len(unmet)} unmet gating requirement(s)" if disqualified
               else "All gating requirements satisfied")

    return {"category_scores": category_scores,
            "weighted_total": round(total, 2),
            "gating": {"disqualified": disqualified, "verdict": verdict,
                       "unmet_gating": unmet, "summary": summary}}


def rank_vendors(rollups):
    return sorted(rollups.keys(),
                  key=lambda v: (rollups[v]["gating"]["disqualified"],
                                 -rollups[v]["weighted_total"]))
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python3 -m pytest tests/test_rollup.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add backend/agent/rollup.py backend/tests/test_rollup.py backend/tests/fixtures/rollup_fixture.json
git commit -m "feat: pure rollup engine with gating and shared fixture"
```

---

### Task 4: ProjectContext + neutral persona

**Files:**
- Create: `backend/agent/project_context.py`, `backend/tests/test_context.py`
- Rewrite: `backend/config/persona.json`

**Interfaces:**
- Consumes: `db.connect/init_db/new_project` (Task 2).
- Produces: `load_project_context(conn, project_id) -> ProjectContext` raising `ValueError("project not found")`; attributes `.project` (dict row), `.categories` (list of dicts), `.requirements()` (list of dicts, Wont included — callers filter), `.gating_config` (dict), `.priority_multipliers` (dict), `.active_weights() -> dict[str,float]` from the active weight profile (falls back to category default_weights); methods `.persona_system_prompt() -> str` (persona + context_brief) and `.scoring_context() -> str` (quality scale / met values / response codes / MoSCoW text, previously in knowledge.py).

- [ ] **Step 1: Rewrite `backend/config/persona.json`** (same keys the prompt builder uses; all FSM/Service Logic content removed)

```json
{
  "id": "rfp-evaluator-v1",
  "display_name": "the RFP evaluation panel",
  "one_line": "A multi-analyst panel that scores vendor RFP responses on evidence, debates independently, and casts one advisory vote.",
  "decision_style": {
    "summary": "Evidence-first. Claims are scored by what the response actually demonstrates: shipped capability beats configuration, configuration beats roadmap, and silence is a gap. Disagreement between analysts is surfaced, not averaged away."
  },
  "priorities_ranked": [
    {"rank": 1, "name": "Requirement evidence", "why": "The response either demonstrates the capability or it does not; adjectives are not evidence."},
    {"rank": 2, "name": "Delivery certainty", "why": "Out-of-box and configured answers carry less delivery risk than custom builds and roadmap promises."},
    {"rank": 3, "name": "Fit to the client's context", "why": "The context brief describes what this buyer actually needs; generic strength does not outweigh specific fit."}
  ],
  "red_flags": [
    {"flag": "Roadmap answers on gating requirements", "trigger": "A Must answered with future delivery", "penalty": "treated as unmet for gating"},
    {"flag": "Marketing language without mechanism", "trigger": "Claims with no description of how the capability works", "penalty": "confidence capped at Low"},
    {"flag": "Silent non-answers", "trigger": "Requirement not addressed anywhere in the response", "penalty": "scored GAP, never inferred"}
  ],
  "weighting_doctrine": {"principle": "Category weights are the buyer's stated priorities. Priority multipliers (Must over Should over Could) express decision leverage inside each category. Never let a strong optional capability paper over a weak mandatory one."},
  "voice": {
    "register": "Plain, direct, specific. Short sentences. Names the evidence or the gap.",
    "signature_phrases": ["the response shows", "unproven as written", "this must be demonstrated"],
    "do": ["Cite the response text.", "Say what would change the score."],
    "dont": ["Never invent evidence.", "Never soften a gap into a partial."]
  }
}
```

- [ ] **Step 2: Write failing tests**

`backend/tests/test_context.py`:

```python
import json, pytest
import db as dbmod
from agent.project_context import load_project_context

def _seed(conn):
    pid = dbmod.new_project(conn, "ERP RFP", "Acme", "Mid-market ERP for a 300-person distributor")
    cur = conn.execute(
        "INSERT INTO categories (project_id, name, default_weight, sort_order) VALUES (?,?,?,?)",
        (pid, "Functional", 60.0, 0))
    cat1 = cur.lastrowid
    conn.execute(
        "INSERT INTO requirements (project_id, ext_id, text, category_id, priority)"
        " VALUES (?,?,?,?,?)", (pid, "R-1", "Support multi-entity GL", cat1, "Must"))
    conn.commit()
    return pid, cat1

def test_load_missing_project_raises(conn):
    with pytest.raises(ValueError):
        load_project_context(conn, 12345)

def test_context_exposes_rows(conn):
    pid, cat1 = _seed(conn)
    ctx = load_project_context(conn, pid)
    assert ctx.project["name"] == "ERP RFP"
    assert ctx.categories[0]["name"] == "Functional"
    assert ctx.requirements()[0]["ext_id"] == "R-1"
    assert ctx.gating_config["gate_priorities"] == ["Must"]
    assert ctx.priority_multipliers["Must"] == 3.0

def test_active_weights_fall_back_to_defaults(conn):
    pid, cat1 = _seed(conn)
    ctx = load_project_context(conn, pid)
    assert ctx.active_weights() == {str(cat1): 60.0}

def test_active_weights_use_active_profile(conn):
    pid, cat1 = _seed(conn)
    conn.execute("INSERT INTO weight_profiles (project_id, name, weights, is_active)"
                 " VALUES (?,?,?,1)", (pid, "Committee", json.dumps({str(cat1): 45.0})))
    conn.commit()
    ctx = load_project_context(conn, pid)
    assert ctx.active_weights() == {str(cat1): 45.0}

def test_persona_prompt_includes_context_brief(conn):
    pid, _ = _seed(conn)
    ctx = load_project_context(conn, pid)
    prompt = ctx.persona_system_prompt()
    assert "300-person distributor" in prompt
    assert "evidence" in prompt.lower()
    assert "HVAC" not in prompt and "OpCo" not in prompt

def test_scoring_context_lists_codes(conn):
    pid, _ = _seed(conn)
    ctx = load_project_context(conn, pid)
    sc = ctx.scoring_context()
    for code in ("OOB", "CONFIG", "CUSTOM", "ROADMAP", "GAP"):
        assert code in sc
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.project_context'`

- [ ] **Step 4: Implement `backend/agent/project_context.py`**

```python
"""Per-request project context — the fork's replacement for knowledge.py's singleton.
Loaded per request from SQLite; nothing here caches across requests."""
import json, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PERSONA_PATH = os.path.join(os.path.dirname(_HERE), "config", "persona.json")

QUALITY_SCALE = {
    "5": "Fully demonstrated, out-of-box or configured, with specifics",
    "4": "Demonstrated with minor caveats or light configuration",
    "3": "Partially demonstrated; material caveats or partner/extension needed",
    "2": "Claimed but unproven, custom build, or thin description",
    "1": "Roadmap, vague, or contradicted elsewhere in the response",
}
MET_VALUES = {"Yes": "requirement satisfied", "Partial": "partly satisfied",
              "No": "not satisfied", "N/A": "not applicable to this vendor"}
RESPONSE_CODES = ["OOB", "CONFIG", "EXTENSION", "CUSTOM", "PARTNER", "ROADMAP", "GAP"]
MOSCOW = {"Must": "mandatory", "Should": "important", "Could": "desirable",
          "Wont": "out of scope this cycle (stored, never scored)"}


class ProjectContext:
    def __init__(self, conn, project_row):
        self._conn = conn
        self.project = dict(project_row)
        self.gating_config = json.loads(self.project["gating_config"])
        self.priority_multipliers = json.loads(self.project["priority_multipliers"])
        self.categories = [dict(r) for r in conn.execute(
            "SELECT * FROM categories WHERE project_id=? ORDER BY sort_order",
            (self.project["id"],))]
        with open(_PERSONA_PATH, encoding="utf-8") as f:
            self.persona = json.load(f)

    def requirements(self):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM requirements WHERE project_id=? ORDER BY id",
            (self.project["id"],))]

    def active_weights(self):
        row = self._conn.execute(
            "SELECT weights FROM weight_profiles WHERE project_id=? AND is_active=1"
            " ORDER BY id DESC LIMIT 1", (self.project["id"],)).fetchone()
        if row:
            return {str(k): float(v) for k, v in json.loads(row["weights"]).items()}
        return {str(c["id"]): float(c["default_weight"]) for c in self.categories}

    def persona_system_prompt(self):
        p = self.persona
        lines = [f"You are {p['display_name']}.", p["one_line"],
                 "\nDECISION STYLE: " + p["decision_style"]["summary"],
                 "\nPRIORITIES (ranked):"]
        for pr in p["priorities_ranked"]:
            lines.append(f"  {pr['rank']}. {pr['name']} — {pr['why']}")
        lines.append("\nRED FLAGS you actively penalize:")
        for rf in p["red_flags"]:
            lines.append(f"  - {rf['flag']}: {rf['trigger']} ({rf['penalty']})")
        lines.append("\nWEIGHTING DOCTRINE: " + p["weighting_doctrine"]["principle"])
        v = p["voice"]
        lines.append("\nVOICE: " + v["register"])
        lines.append("ALWAYS: " + " ".join(v["do"]))
        lines.append("NEVER: " + " ".join(v["dont"]))
        brief = (self.project.get("context_brief") or "").strip()
        if brief:
            lines.append("\nCLIENT CONTEXT (weigh every judgment against this):\n" + brief)
        lines.append("\nGround every judgment in evidence from the response text. "
                     "Reward proven OOB/CONFIG over CUSTOM/ROADMAP. Never infer "
                     "capabilities the response does not describe.")
        return "\n".join(lines)

    def scoring_context(self):
        out = ["RFP SCORING RULES:"]
        out.append("Quality scale (1-5): " + "; ".join(f"{k}={v}" for k, v in QUALITY_SCALE.items()))
        out.append("Met values: " + "; ".join(f"{k}={v}" for k, v in MET_VALUES.items()))
        out.append("Response codes: " + ", ".join(RESPONSE_CODES))
        out.append("MoSCoW: " + "; ".join(f"{k}={v}" for k, v in MOSCOW.items()))
        g = self.gating_config
        out.append(f"GATING (deterministic, not yours to decide): a requirement with priority in "
                   f"{g['gate_priorities']} answered with met in {g['unmet_met_values']} and code in "
                   f"{g['gating_codes']} leads to {g['verdict']}.")
        return "\n".join(out)


def load_project_context(conn, project_id):
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise ValueError("project not found")
    return ProjectContext(conn, row)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python3 -m pytest tests/test_context.py -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/agent/project_context.py backend/config/persona.json backend/tests/test_context.py
git commit -m "feat: per-request ProjectContext and neutral evidence-first persona"
```

---

### Task 5: Rebuild `app.py` around projects — CRUD API for projects and vendors

**Files:**
- Rewrite: `backend/app.py` (strip all FSM routes; keep auth/health/models/static serving)
- Create: `backend/tests/test_projects_api.py`

**Interfaces:**
- Consumes: `db.get_db/close_db/new_project` (Task 2), `load_project_context` (Task 4), `auth.require_auth` (unchanged).
- Produces the route surface later tasks extend:
  - `GET /api/health` → `{ok: true}` (no auth)
  - `GET /api/models` → provider registry (as parent)
  - `GET /api/projects` → `{projects: [{id, name, client, status, created_at, n_requirements, n_vendors}]}`
  - `POST /api/projects` `{name, client?, context_brief?}` → `{project}` (400 on missing name)
  - `GET /api/projects/<pid>` → `{project, categories, n_requirements, gating_config, priority_multipliers}`
  - `PATCH /api/projects/<pid>` `{name?, client?, context_brief?, status?, gating_config?, priority_multipliers?}` → `{project}`
  - `GET/POST /api/projects/<pid>/vendors`, `DELETE /api/projects/<pid>/vendors/<vid>`
  - All non-health/login routes wrapped in `@require_auth`; 404 JSON `{error: "project not found"}` when `load_project_context` raises.
- Test-mode hook: `app.config["TESTING"] = True` plus `AUTH_DISABLED=1` env skips `require_auth` (add a guard in `auth.require_auth`: `if os.environ.get("AUTH_DISABLED") == "1": return fn(*args, **kwargs)`). Tests set it in conftest.

- [ ] **Step 1: Extend conftest with a Flask test client**

Append to `backend/tests/conftest.py`:

```python
@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_DISABLED", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import importlib
    import db as dbmod2
    importlib.reload(dbmod2)          # pick up DB_PATH
    import app as appmod
    importlib.reload(appmod)
    appmod.app.config["TESTING"] = True
    with appmod.app.test_client() as c:
        yield c
```

- [ ] **Step 2: Write failing tests**

`backend/tests/test_projects_api.py`:

```python
def test_health_open(client):
    assert client.get("/api/health").status_code == 200

def test_create_and_list_project(client):
    r = client.post("/api/projects", json={"name": "ERP RFP", "client": "Acme"})
    assert r.status_code == 200
    pid = r.get_json()["project"]["id"]
    lst = client.get("/api/projects").get_json()["projects"]
    assert any(p["id"] == pid for p in lst)

def test_create_requires_name(client):
    assert client.post("/api/projects", json={}).status_code == 400

def test_get_missing_project_404(client):
    assert client.get("/api/projects/999").status_code == 404

def test_patch_context_brief(client):
    pid = client.post("/api/projects", json={"name": "X"}).get_json()["project"]["id"]
    r = client.patch(f"/api/projects/{pid}", json={"context_brief": "New brief"})
    assert r.get_json()["project"]["context_brief"] == "New brief"

def test_vendor_crud(client):
    pid = client.post("/api/projects", json={"name": "X"}).get_json()["project"]["id"]
    v = client.post(f"/api/projects/{pid}/vendors", json={"name": "VendorA"}).get_json()["vendor"]
    assert v["name"] == "VendorA"
    assert client.post(f"/api/projects/{pid}/vendors", json={"name": "VendorA"}).status_code == 409
    vids = client.get(f"/api/projects/{pid}/vendors").get_json()["vendors"]
    assert len(vids) == 1
    assert client.delete(f"/api/projects/{pid}/vendors/{v['id']}").status_code == 200
    assert client.get(f"/api/projects/{pid}/vendors").get_json()["vendors"] == []
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_projects_api.py -v`
Expected: ERROR — `app.py` still imports deleted modules (`knowledge`, `sample`, ...).

- [ ] **Step 4: Rewrite `backend/app.py`**

Keep from the parent: Flask setup, static serving of `frontend/`, login/logout/session/password routes, `/api/models`. Delete: results store, `_merge_results`, seeding, committee routes, evaluate routes (return in Task 10), knowledge route. New body (complete, minus the untouched auth block markers):

```python
"""Flask server for the generalized RFP evaluation agent."""
import json, os, sqlite3
from flask import Flask, jsonify, request, send_from_directory
import db
from agent.project_context import load_project_context
from agent.providers import available_models
from auth import require_auth, get_secret_key   # plus existing login/logout/session routes

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.join(os.path.dirname(HERE), "frontend")

app = Flask(__name__, static_folder=None)
app.secret_key = get_secret_key()
app.teardown_appcontext(db.close_db)

# ---- auth routes: copy the parent's /api/login, /api/logout, /api/session,
# ---- /api/account/password blocks verbatim here.

@app.route("/")
@app.route("/js/<path:fname>")
def frontend(fname=None):
    return send_from_directory(FRONTEND if fname is None else os.path.join(FRONTEND, "js"),
                               fname or "index.html")

@app.route("/api/health")
def health():
    return jsonify({"ok": True})

@app.route("/api/models")
@require_auth
def models():
    return jsonify(available_models())

def _project_dict(row):
    d = dict(row)
    d["gating_config"] = json.loads(d["gating_config"])
    d["priority_multipliers"] = json.loads(d["priority_multipliers"])
    return d

@app.route("/api/projects", methods=["GET"])
@require_auth
def list_projects():
    conn = db.get_db()
    rows = conn.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM requirements r WHERE r.project_id=p.id) n_requirements,"
        " (SELECT COUNT(*) FROM vendors v WHERE v.project_id=p.id) n_vendors"
        " FROM projects p ORDER BY p.created_at DESC").fetchall()
    return jsonify({"projects": [_project_dict(r) for r in rows]})

@app.route("/api/projects", methods=["POST"])
@require_auth
def create_project():
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    conn = db.get_db()
    pid = db.new_project(conn, name, body.get("client", ""), body.get("context_brief", ""))
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return jsonify({"project": _project_dict(row)})

@app.route("/api/projects/<int:pid>", methods=["GET"])
@require_auth
def get_project(pid):
    conn = db.get_db()
    try:
        ctx = load_project_context(conn, pid)
    except ValueError:
        return jsonify({"error": "project not found"}), 404
    return jsonify({"project": _project_dict(conn.execute(
                        "SELECT * FROM projects WHERE id=?", (pid,)).fetchone()),
                    "categories": ctx.categories,
                    "n_requirements": len(ctx.requirements()),
                    "active_weights": ctx.active_weights()})

@app.route("/api/projects/<int:pid>", methods=["PATCH"])
@require_auth
def patch_project(pid):
    conn = db.get_db()
    if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
        return jsonify({"error": "project not found"}), 404
    body = request.get_json(force=True, silent=True) or {}
    fields = {}
    for k in ("name", "client", "context_brief", "status"):
        if k in body:
            fields[k] = body[k]
    for k in ("gating_config", "priority_multipliers"):
        if k in body:
            fields[k] = json.dumps(body[k])
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE projects SET {sets} WHERE id=?", (*fields.values(), pid))
        conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    return jsonify({"project": _project_dict(row)})

@app.route("/api/projects/<int:pid>/vendors", methods=["GET", "POST"])
@require_auth
def vendors(pid):
    conn = db.get_db()
    if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
        return jsonify({"error": "project not found"}), 404
    if request.method == "POST":
        body = request.get_json(force=True, silent=True) or {}
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        try:
            cur = conn.execute(
                "INSERT INTO vendors (project_id, name, dossier_text) VALUES (?,?,?)",
                (pid, name, body.get("dossier_text", "")))
            conn.commit()
        except sqlite3.IntegrityError:
            return jsonify({"error": "vendor already exists"}), 409
        row = conn.execute("SELECT * FROM vendors WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify({"vendor": dict(row)})
    rows = conn.execute("SELECT * FROM vendors WHERE project_id=? ORDER BY name", (pid,)).fetchall()
    return jsonify({"vendors": [dict(r) for r in rows]})

@app.route("/api/projects/<int:pid>/vendors/<int:vid>", methods=["DELETE"])
@require_auth
def delete_vendor(pid, vid):
    conn = db.get_db()
    conn.execute("DELETE FROM vendors WHERE id=? AND project_id=?", (vid, pid))
    conn.commit()
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8000)), debug=False)
```

Also add to `backend/auth.py` `require_auth` wrapper, first line inside `wrapper`:

```python
        if os.environ.get("AUTH_DISABLED") == "1":
            return fn(*args, **kwargs)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python3 -m pytest tests/test_projects_api.py -v`
Expected: 6 passed. Also run `python3 -m pytest tests -v` — earlier suites still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app.py backend/auth.py backend/tests
git commit -m "feat: project and vendor CRUD API on SQLite, FSM routes removed"
```

---

### Task 6: Excel template download

**Files:**
- Create: `backend/agent/intake.py` (template half), `backend/tests/test_intake.py` (template tests)
- Modify: `backend/app.py` (one route)

**Interfaces:**
- Produces: `intake.build_template() -> bytes` (an .xlsx workbook: sheet "Categories" headers `Category | Description | Weight`; sheet "Requirements" headers `ID | Requirement | Category | Priority | Section | Notes`; a third sheet "How to fill this in" with instructions and the MoSCoW vocabulary; two example rows per sheet, styled header row). Route `GET /api/template` returning it as `rfp_requirements_template.xlsx`.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_intake.py`:

```python
import io
from openpyxl import load_workbook
from agent import intake

def test_template_has_sheets_and_headers():
    wb = load_workbook(io.BytesIO(intake.build_template()))
    assert set(wb.sheetnames) >= {"Categories", "Requirements"}
    cats = [c.value for c in wb["Categories"][1]]
    assert cats[:3] == ["Category", "Description", "Weight"]
    reqs = [c.value for c in wb["Requirements"][1]]
    assert reqs[:6] == ["ID", "Requirement", "Category", "Priority", "Section", "Notes"]

def test_template_route(client):
    r = client.get("/api/template")
    assert r.status_code == 200
    assert "spreadsheetml" in r.content_type
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_intake.py -v`
Expected: FAIL — `intake` has no `build_template`.

- [ ] **Step 3: Implement the template half of `backend/agent/intake.py`**

```python
"""Excel intake: template generation + parse/validate/commit (Task 7)."""
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

_HEADER_FILL = PatternFill("solid", start_color="1F3B57")
_HEADER_FONT = Font(color="FFFFFF", bold=True)

def _header(ws, cols):
    ws.append(cols)
    for cell in ws[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT

def build_template() -> bytes:
    wb = Workbook()
    cats = wb.active
    cats.title = "Categories"
    _header(cats, ["Category", "Description", "Weight"])
    cats.append(["Functional fit", "Coverage of day-to-day operational needs", 60])
    cats.append(["Technical & architecture", "Integration, security, scalability", 40])

    reqs = wb.create_sheet("Requirements")
    _header(reqs, ["ID", "Requirement", "Category", "Priority", "Section", "Notes"])
    reqs.append(["R-001", "Support multi-entity general ledger", "Functional fit", "Must",
                 "Finance", "Consolidation across subsidiaries"])
    reqs.append(["", "Provide REST APIs for all core objects", "Technical & architecture",
                 "Should", "Integration", "ID auto-generated when blank"])

    guide = wb.create_sheet("How to fill this in")
    for line in [
        "Categories sheet: one row per scoring category. Weights must sum to 100.",
        "Requirements sheet: one row per requirement.",
        "Category must exactly match a row on the Categories sheet.",
        "Priority must be one of: Must, Should, Could, Won't.",
        "Won't rows are stored for completeness but never scored.",
        "ID is optional; blank IDs are auto-generated (R-001, R-002, ...).",
        "Section and Notes are optional free text.",
    ]:
        guide.append([line])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
```

Route in `backend/app.py`:

```python
from flask import Response
from agent import intake

@app.route("/api/template")
@require_auth
def template():
    return Response(
        intake.build_template(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=rfp_requirements_template.xlsx"})
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_intake.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/agent/intake.py backend/tests/test_intake.py backend/app.py
git commit -m "feat: downloadable Excel requirements template"
```

---

### Task 7: Intake — parse, validate, preview, confirm

**Files:**
- Modify: `backend/agent/intake.py` (parse/commit half), `backend/app.py` (two routes), `backend/tests/test_intake.py`

**Interfaces:**
- Consumes: schema from Task 2; `build_template()` from Task 6 (tests round-trip through it).
- Produces:
  - `intake.parse_workbook(file_bytes: bytes) -> dict` = `{"categories": [{name, description, weight}], "requirements": [{ext_id, text, category, priority, section_label, notes}], "errors": [str], "warnings": [str], "summary": {n_requirements, n_categories, by_priority: {..}, weight_sum}}`. Never raises on bad content — bad content produces `errors`. Priority normalization: `Won't/WONT/won't → Wont`. Blank IDs become `R-001...` in row order, skipping IDs already used in the sheet.
  - `intake.commit_intake(conn, project_id, parsed) -> dict` = `{"n_categories", "n_requirements", "weight_profile_id"}` — inserts categories, requirements, and a first weight profile named "Uploaded defaults" (`is_active=1`) in ONE transaction; raises `ValueError` if `parsed["errors"]` is non-empty or the project already has requirements.
  - Routes: `POST /api/projects/<pid>/intake` (multipart `file`) → parsed preview JSON (nothing written); `POST /api/projects/<pid>/intake/confirm` with the parsed payload echoed back → commit result. Confirm re-validates server-side; 409 if project already has requirements, body `{"error": "...", "requires": "replace"}`. With `{"replace": true}` it deletes existing categories/requirements/weight_profiles/evaluations for the project first (cascade covers scores).

- [ ] **Step 1: Write failing tests** (append to `backend/tests/test_intake.py`)

```python
import io, json
from openpyxl import load_workbook, Workbook
import db as dbmod
from agent import intake

def _wb_bytes(cats, reqs):
    wb = Workbook()
    ws = wb.active; ws.title = "Categories"
    ws.append(["Category", "Description", "Weight"])
    for r in cats: ws.append(r)
    ws2 = wb.create_sheet("Requirements")
    ws2.append(["ID", "Requirement", "Category", "Priority", "Section", "Notes"])
    for r in reqs: ws2.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

GOOD = _wb_bytes(
    [["Functional", "", 60], ["Technical", "", 40]],
    [["R-1", "Multi-entity GL", "Functional", "Must", "Fin", ""],
     ["", "REST APIs", "Technical", "Should", "", ""],
     ["R-3", "Dark mode", "Functional", "Won't", "", ""]])

def test_parse_good_workbook():
    p = intake.parse_workbook(GOOD)
    assert p["errors"] == []
    assert p["summary"]["n_requirements"] == 3
    assert p["summary"]["weight_sum"] == 100
    assert p["requirements"][1]["ext_id"] == "R-001"      # auto-generated
    assert p["requirements"][2]["priority"] == "Wont"     # normalized

def test_parse_flags_problems():
    bad = _wb_bytes([["Functional", "", 55]],
                    [["R-1", "", "Functional", "Must", "", ""],
                     ["R-1", "Dup id", "Nope", "Urgent", "", ""]])
    p = intake.parse_workbook(bad)
    msgs = " | ".join(p["errors"])
    assert "weights sum to 55" in msgs
    assert "missing requirement text" in msgs
    assert "unknown category 'Nope'" in msgs
    assert "invalid priority 'Urgent'" in msgs
    assert "duplicate ID 'R-1'" in msgs

def test_parse_garbage_bytes_is_error_not_crash():
    p = intake.parse_workbook(b"not an xlsx")
    assert p["errors"] and p["requirements"] == []

def test_commit_writes_all_rows(conn):
    pid = dbmod.new_project(conn, "P")
    out = intake.commit_intake(conn, pid, intake.parse_workbook(GOOD))
    assert out["n_categories"] == 2 and out["n_requirements"] == 3
    prof = conn.execute("SELECT * FROM weight_profiles WHERE project_id=?", (pid,)).fetchone()
    assert prof["is_active"] == 1 and prof["name"] == "Uploaded defaults"
    weights = json.loads(prof["weights"])
    assert sorted(weights.values()) == [40.0, 60.0]

def test_commit_refuses_second_upload(conn):
    import pytest
    pid = dbmod.new_project(conn, "P")
    intake.commit_intake(conn, pid, intake.parse_workbook(GOOD))
    with pytest.raises(ValueError):
        intake.commit_intake(conn, pid, intake.parse_workbook(GOOD))

def test_intake_routes(client):
    pid = client.post("/api/projects", json={"name": "P"}).get_json()["project"]["id"]
    r = client.post(f"/api/projects/{pid}/intake",
                    data={"file": (io.BytesIO(GOOD), "reqs.xlsx")},
                    content_type="multipart/form-data")
    parsed = r.get_json()
    assert parsed["errors"] == []
    r2 = client.post(f"/api/projects/{pid}/intake/confirm", json=parsed)
    assert r2.get_json()["n_requirements"] == 3
    r3 = client.post(f"/api/projects/{pid}/intake/confirm", json=parsed)
    assert r3.status_code == 409
    parsed["replace"] = True
    assert client.post(f"/api/projects/{pid}/intake/confirm", json=parsed).status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_intake.py -v`
Expected: new tests FAIL (`parse_workbook` missing); template tests still pass.

- [ ] **Step 3: Implement parse/commit in `backend/agent/intake.py`** (append)

```python
import json
from openpyxl import load_workbook

VALID_PRIORITIES = {"must": "Must", "should": "Should", "could": "Could",
                    "won't": "Wont", "wont": "Wont"}

def parse_workbook(file_bytes: bytes) -> dict:
    out = {"categories": [], "requirements": [], "errors": [], "warnings": [],
           "summary": {}}
    try:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception:
        out["errors"].append("could not read file as .xlsx")
        return out
    for sheet in ("Categories", "Requirements"):
        if sheet not in wb.sheetnames:
            out["errors"].append(f"missing sheet '{sheet}'")
    if out["errors"]:
        return out

    weight_sum = 0.0
    for i, row in enumerate(wb["Categories"].iter_rows(min_row=2, values_only=True), start=2):
        name = str(row[0] or "").strip()
        if not name:
            continue
        try:
            weight = float(row[2])
        except (TypeError, ValueError):
            out["errors"].append(f"Categories row {i}: weight is not a number")
            weight = 0.0
        weight_sum += weight
        out["categories"].append({"name": name,
                                  "description": str(row[1] or "").strip(),
                                  "weight": weight})
    if abs(weight_sum - 100.0) > 0.01:
        out["errors"].append(f"category weights sum to {weight_sum:g}, must sum to 100")
    cat_names = {c["name"] for c in out["categories"]}

    used_ids, auto_n = set(), 0
    by_priority = {}
    for i, row in enumerate(wb["Requirements"].iter_rows(min_row=2, values_only=True), start=2):
        text = str(row[1] or "").strip()
        ext_id = str(row[0] or "").strip()
        if not text and not ext_id:
            continue
        if not text:
            out["errors"].append(f"Requirements row {i}: missing requirement text")
        cat = str(row[2] or "").strip()
        if cat not in cat_names:
            out["errors"].append(f"Requirements row {i}: unknown category '{cat}'")
        prio_raw = str(row[3] or "").strip()
        prio = VALID_PRIORITIES.get(prio_raw.lower())
        if prio is None:
            out["errors"].append(f"Requirements row {i}: invalid priority '{prio_raw}'")
            prio = "Could"
        if not ext_id:
            auto_n += 1
            while f"R-{auto_n:03d}" in used_ids:
                auto_n += 1
            ext_id = f"R-{auto_n:03d}"
        if ext_id in used_ids:
            out["errors"].append(f"Requirements row {i}: duplicate ID '{ext_id}'")
        used_ids.add(ext_id)
        by_priority[prio] = by_priority.get(prio, 0) + 1
        out["requirements"].append({"ext_id": ext_id, "text": text, "category": cat,
                                    "priority": prio,
                                    "section_label": str(row[4] or "").strip(),
                                    "notes": str(row[5] or "").strip()})
    out["summary"] = {"n_requirements": len(out["requirements"]),
                      "n_categories": len(out["categories"]),
                      "by_priority": by_priority, "weight_sum": weight_sum}
    return out


def commit_intake(conn, project_id, parsed) -> dict:
    if parsed.get("errors"):
        raise ValueError("cannot commit a parse with errors")
    existing = conn.execute("SELECT COUNT(*) c FROM requirements WHERE project_id=?",
                            (project_id,)).fetchone()["c"]
    if existing:
        raise ValueError("project already has requirements")
    try:
        cat_ids = {}
        for order, c in enumerate(parsed["categories"]):
            cur = conn.execute(
                "INSERT INTO categories (project_id, name, description, default_weight, sort_order)"
                " VALUES (?,?,?,?,?)",
                (project_id, c["name"], c["description"], c["weight"], order))
            cat_ids[c["name"]] = cur.lastrowid
        for r in parsed["requirements"]:
            conn.execute(
                "INSERT INTO requirements (project_id, ext_id, text, category_id, priority,"
                " section_label, notes) VALUES (?,?,?,?,?,?,?)",
                (project_id, r["ext_id"], r["text"], cat_ids[r["category"]],
                 r["priority"], r["section_label"], r["notes"]))
        weights = {str(cid): parsed["categories"][i]["weight"]
                   for i, cid in enumerate(cat_ids.values())}
        cur = conn.execute(
            "INSERT INTO weight_profiles (project_id, name, weights, is_active) VALUES (?,?,?,1)",
            (project_id, "Uploaded defaults", json.dumps(weights)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"n_categories": len(cat_ids), "n_requirements": len(parsed["requirements"]),
            "weight_profile_id": cur.lastrowid}
```

Routes in `backend/app.py`:

```python
@app.route("/api/projects/<int:pid>/intake", methods=["POST"])
@require_auth
def intake_preview(pid):
    conn = db.get_db()
    if conn.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone() is None:
        return jsonify({"error": "project not found"}), 404
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "file is required"}), 400
    data = f.read()
    if not data:
        return jsonify({"error": "file is empty (OneDrive online-only placeholder? "
                                 "copy the file locally first)"}), 400
    if len(data) > 10 * 1024 * 1024:
        return jsonify({"error": "file exceeds 10 MB limit"}), 400
    return jsonify(intake.parse_workbook(data))

@app.route("/api/projects/<int:pid>/intake/confirm", methods=["POST"])
@require_auth
def intake_confirm(pid):
    conn = db.get_db()
    parsed = request.get_json(force=True, silent=True) or {}
    if parsed.get("errors"):
        return jsonify({"error": "parse has errors; fix the file and re-upload"}), 400
    existing = conn.execute("SELECT COUNT(*) c FROM requirements WHERE project_id=?",
                            (pid,)).fetchone()["c"]
    if existing and not parsed.get("replace"):
        return jsonify({"error": "project already has requirements", "requires": "replace"}), 409
    if existing:
        conn.execute("DELETE FROM evaluations WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM weight_profiles WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM requirements WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM categories WHERE project_id=?", (pid,))
        conn.commit()
    try:
        return jsonify(intake.commit_intake(conn, pid, parsed))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_intake.py -v`
Expected: all pass (template + 7 new).

- [ ] **Step 5: Commit**

```bash
git add backend/agent/intake.py backend/app.py backend/tests/test_intake.py
git commit -m "feat: Excel intake with validate/preview/confirm and replace guard"
```

---

### Task 8: Generic scoring engine (`scoring.py` rewrite)

**Files:**
- Rewrite: `backend/agent/scoring.py`
- Modify: `backend/agent/schemas.py` (slim), `backend/agent/ingest.py` (drop matrix functions)
- Create: `backend/tests/test_scoring.py`

**Interfaces:**
- Consumes: `ProjectContext` (Task 4), `providers.LLMClient/is_mock/extract_json` (unchanged), `ingest.build_retrieval_index/relevant_passages` (unchanged).
- Produces: `score_requirements(ctx, vendor_name, proposal_text, model_id, on_batch, cancelled=None) -> tuple[list[dict], int, int]` returning `(scores, live_count, fallback_count)` where each score dict is `{requirement_id, ext_id, category_id, priority, met, quality, response_code, confidence, rationale, evidence_gap, scored_live}`. `on_batch(scores_batch)` is called after EVERY batch (~12 requirements) so the caller persists incrementally — that is the resumability hook. `cancelled` is an optional `threading.Event`.
- `schemas.py` keeps only `Vote` (vote.py still returns it); the rest of the dataclasses are replaced by plain dicts. Delete `CapabilityScore`, `SegmentFit`, `AgenticFuture`, `RequirementScore`, `CategoryScore`, `GatingResult`, `VendorEvaluation`.
- `ingest.py`: delete `_cell`, `_find_rid_column`, `_find_response_columns`, `_find_requirement_text_column`, `extract_requirement_matrix` (matrix machinery). Keep extract/fetch/chunk/retrieval/locate functions.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_scoring.py`:

```python
import db as dbmod
from agent.project_context import load_project_context
from agent.scoring import score_requirements

def _project(conn, n=5):
    pid = dbmod.new_project(conn, "P", context_brief="Mid-market ERP")
    cur = conn.execute("INSERT INTO categories (project_id, name, default_weight, sort_order)"
                       " VALUES (?,?,?,?)", (pid, "Functional", 100.0, 0))
    cat = cur.lastrowid
    for i in range(n):
        prio = "Wont" if i == n - 1 else "Must"
        conn.execute("INSERT INTO requirements (project_id, ext_id, text, category_id, priority)"
                     " VALUES (?,?,?,?,?)",
                     (pid, f"R-{i}", f"Support capability {i} with audit trail", cat, prio))
    conn.commit()
    return pid

def test_mock_scoring_covers_all_scorable(conn):
    pid = _project(conn)
    ctx = load_project_context(conn, pid)
    batches = []
    scores, live, fb = score_requirements(
        ctx, "VendorA", "We support capability 0 out of the box with audit trail.",
        "mock", on_batch=batches.append)
    assert len(scores) == 4            # Wont excluded
    assert live == 0 and fb == 0       # mock is neither live nor fallback
    assert batches and sum(len(b) for b in batches) == 4
    for s in scores:
        assert s["met"] in ("Yes", "Partial", "No", "N/A")
        assert 1 <= s["quality"] <= 5
        assert s["response_code"] in ("OOB", "CONFIG", "EXTENSION", "CUSTOM",
                                      "PARTNER", "ROADMAP", "GAP")

def test_mock_scoring_is_deterministic(conn):
    pid = _project(conn)
    ctx = load_project_context(conn, pid)
    a, _, _ = score_requirements(ctx, "V", "text", "mock", on_batch=lambda b: None)
    b, _, _ = score_requirements(ctx, "V", "text", "mock", on_batch=lambda b: None)
    assert a == b

def test_mock_rewards_evidence_overlap(conn):
    pid = _project(conn, n=2)
    ctx = load_project_context(conn, pid)
    scores, _, _ = score_requirements(
        ctx, "V", "We fully support capability 0 with audit trail, out of the box.",
        "mock", on_batch=lambda b: None)
    strong = next(s for s in scores if s["ext_id"] == "R-0")
    assert strong["met"] in ("Yes", "Partial") and strong["quality"] >= 3
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_scoring.py -v`
Expected: ERROR — old scoring.py imports `knowledge`/`sample`/`matrix_llm`.

- [ ] **Step 3: Rewrite `backend/agent/scoring.py`** (complete replacement)

```python
"""Generic per-requirement scoring: batched LLM calls with a deterministic
keyless mock fallback. Rollups live in rollup.py; persistence in the caller."""
import hashlib, json
from typing import Callable, Optional
from .providers import LLMClient, is_mock, extract_json
from .ingest import build_retrieval_index, relevant_passages

BATCH_SIZE = 12

def score_requirements(ctx, vendor_name: str, proposal_text: str, model_id: str,
                       on_batch: Callable, cancelled=None):
    reqs = [r for r in ctx.requirements() if r["priority"] != "Wont"]
    index = build_retrieval_index(proposal_text or "")
    client = LLMClient()
    system = ctx.persona_system_prompt() + "\n\n" + ctx.scoring_context()

    scores, live, fallback = [], 0, 0
    for i in range(0, len(reqs), BATCH_SIZE):
        if cancelled is not None and cancelled.is_set():
            break
        batch = reqs[i:i + BATCH_SIZE]
        batch_scores = None
        if not is_mock(model_id):
            batch_scores = _llm_batch(client, system, ctx, vendor_name, proposal_text,
                                      batch, index, model_id)
        if batch_scores is None:
            batch_scores = [_mock_score(r, proposal_text) for r in batch]
            if not is_mock(model_id):
                fallback += len(batch)
        else:
            live += len(batch)
        scores.extend(batch_scores)
        on_batch(batch_scores)
    return scores, live, fallback


def _llm_batch(client, system, ctx, vendor_name, proposal_text, batch, index, model_id):
    keywords = " ".join(r["text"] for r in batch)
    passages = relevant_passages(index, keywords, k=8)
    context = "\n---\n".join(p["text"] if isinstance(p, dict) else str(p) for p in passages)
    lines = [f'{r["id"]} | {r["ext_id"]} | {r["priority"]} | {r["text"]}' for r in batch]
    user = (
        f"VENDOR: {vendor_name}\n\nRELEVANT PROPOSAL EXCERPTS:\n{context[:8000]}\n\n"
        "REQUIREMENTS TO SCORE (internal_id | ext_id | priority | text):\n" +
        "\n".join(lines) +
        '\n\nReturn STRICT JSON: {"rows": [{"internal_id": int, "met": "Yes|Partial|No|N/A", '
        '"quality": 1-5, "response_code": "OOB|CONFIG|EXTENSION|CUSTOM|PARTNER|ROADMAP|GAP", '
        '"confidence": "High|Medium|Low", "rationale": "<=40 words", '
        '"evidence_gap": "what must still be proven, or empty"}]}. '
        "Score ONLY from the excerpts. A requirement the excerpts never address is GAP / No.")
    try:
        raw = client.generate(system=system, user=user, model_id=model_id, expect_json=True)
        rows = extract_json(raw).get("rows", [])
    except Exception:
        return None
    by_id = {r["id"]: r for r in batch}
    out = []
    for row in rows:
        req = by_id.get(row.get("internal_id"))
        if req is None:
            continue
        out.append(_normalize(req, row, scored_live=1))
    missing = [r for r in batch if r["id"] not in {s["requirement_id"] for s in out}]
    for req in missing:
        out.append(_mock_score(req, proposal_text))
    return out if out else None


def _normalize(req, row, scored_live):
    met = row.get("met") if row.get("met") in ("Yes", "Partial", "No", "N/A") else "No"
    try:
        quality = max(1, min(5, int(row.get("quality", 1))))
    except (TypeError, ValueError):
        quality = 1
    code = row.get("response_code")
    if code not in ("OOB", "CONFIG", "EXTENSION", "CUSTOM", "PARTNER", "ROADMAP", "GAP"):
        code = "GAP"
    conf = row.get("confidence") if row.get("confidence") in ("High", "Medium", "Low") else "Low"
    return {"requirement_id": req["id"], "ext_id": req["ext_id"],
            "category_id": req["category_id"], "priority": req["priority"],
            "met": met, "quality": quality, "response_code": code, "confidence": conf,
            "rationale": str(row.get("rationale", ""))[:400],
            "evidence_gap": str(row.get("evidence_gap", ""))[:300],
            "scored_live": scored_live}


def _mock_score(req, proposal_text):
    """Deterministic keyless scorer: term overlap between requirement and proposal,
    with a stable hash jitter so vendors don't all look identical."""
    text = (proposal_text or "").lower()
    words = [w for w in req["text"].lower().split() if len(w) > 3]
    hits = sum(1 for w in words if w in text)
    overlap = hits / max(1, len(words))
    h = int(hashlib.sha1(f'{req["ext_id"]}|{proposal_text[:64]}'.encode()).hexdigest(), 16)
    jitter = (h % 100) / 100.0
    strength = 0.75 * overlap + 0.25 * jitter
    if strength >= 0.55:
        met, quality, code = "Yes", 4 + (1 if strength > 0.8 else 0), "OOB"
    elif strength >= 0.35:
        met, quality, code = "Partial", 3, "CONFIG"
    elif strength >= 0.2:
        met, quality, code = "Partial", 2, "CUSTOM"
    else:
        met, quality, code = "No", 1, "GAP"
    conf = "High" if overlap >= 0.5 else "Medium" if overlap >= 0.25 else "Low"
    return {"requirement_id": req["id"], "ext_id": req["ext_id"],
            "category_id": req["category_id"], "priority": req["priority"],
            "met": met, "quality": quality, "response_code": code, "confidence": conf,
            "rationale": f"Offline heuristic: {hits}/{len(words)} requirement terms found in the response.",
            "evidence_gap": "" if met == "Yes" else "Confirm in demo — offline heuristic score.",
            "scored_live": 0}
```

Also in this task: slim `schemas.py` to just `Vote` (keep its current fields), and delete the five matrix functions from `ingest.py` listed in Interfaces. Check `relevant_passages`'s actual signature in `ingest.py` (it takes the index, query, k) and adjust the `_llm_batch` call to match what's there — the function is kept verbatim from the parent.

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_scoring.py tests -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/scoring.py backend/agent/schemas.py backend/agent/ingest.py backend/tests/test_scoring.py
git commit -m "feat: generic batched scoring with deterministic mock engine"
```

---

### Task 9: Generalized vote (`vote.py` rewrite)

**Files:**
- Rewrite: `backend/agent/vote.py`
- Create: `backend/tests/test_vote.py`

**Interfaces:**
- Consumes: rollup result dict (Task 3), `ProjectContext` (Task 4), `providers` (unchanged), `schemas.Vote`.
- Produces: `synthesize_vote(ctx, vendor_name, roll, scores, model_id) -> Vote` where `roll` is the rollup() output and `scores` the score dicts. Deterministic band mapping (never LLM-decided): gating disqualified → verdict from gating config ("Disqualified" or "Reject"); else weighted_total ≥ 70 → "Recommend"; ≥ 55 → "Shortlist"; else "Reject". Narrative/dissent/top_risks come from the LLM (mock: template text built from the numbers). Vote.mode stays "single" in Phase 1 (dual-provider votes: Phase 2+ if wanted).

- [ ] **Step 1: Write failing tests**

`backend/tests/test_vote.py`:

```python
import db as dbmod
from agent.project_context import load_project_context
from agent.rollup import rollup
from agent.vote import synthesize_vote, band

def test_bands():
    assert band(80) == "Recommend"
    assert band(70) == "Recommend"
    assert band(60) == "Shortlist"
    assert band(54.9) == "Reject"

def test_disqualified_wins_over_score(conn):
    pid = dbmod.new_project(conn, "P")
    ctx = load_project_context(conn, pid)
    roll = {"weighted_total": 90.0, "category_scores": [],
            "gating": {"disqualified": True, "verdict": "Disqualified",
                       "unmet_gating": [{"requirement_id": 1, "priority": "Must",
                                         "response_code": "GAP", "met": "No"}],
                       "summary": "1 unmet gating requirement(s)"}}
    v = synthesize_vote(ctx, "V", roll, [], "mock")
    assert v.recommendation == "Disqualified"

def test_mock_vote_has_narrative_and_risks(conn):
    pid = dbmod.new_project(conn, "P", context_brief="ERP for Acme")
    ctx = load_project_context(conn, pid)
    roll = {"weighted_total": 72.5,
            "category_scores": [{"id": 1, "name": "Functional", "weight": 100,
                                 "raw_1_5": 3.6, "weighted_points": 72.5, "n_scored": 4}],
            "gating": {"disqualified": False, "verdict": None, "unmet_gating": [],
                       "summary": "All gating requirements satisfied"}}
    v = synthesize_vote(ctx, "V", roll, [], "mock")
    assert v.recommendation == "Recommend"
    assert v.narrative and v.dissent
    assert isinstance(v.top_risks, list)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_vote.py -v`
Expected: ERROR (old vote.py imports knowledge/schemas types now gone).

- [ ] **Step 3: Rewrite `backend/agent/vote.py`**

```python
"""Vote synthesis: deterministic recommendation band + LLM (or mock) narrative."""
import json
from .providers import LLMClient, is_mock, extract_json
from .schemas import Vote

def band(total: float) -> str:
    if total >= 70:
        return "Recommend"
    if total >= 55:
        return "Shortlist"
    return "Reject"

def synthesize_vote(ctx, vendor_name, roll, scores, model_id) -> Vote:
    if roll["gating"]["disqualified"]:
        reco = roll["gating"]["verdict"]
        reason = roll["gating"]["summary"]
    else:
        reco = band(roll["weighted_total"])
        reason = f'weighted total {roll["weighted_total"]}/100'

    weak = sorted(roll["category_scores"], key=lambda c: c["raw_1_5"])[:2]
    gaps = [s for s in scores if s.get("evidence_gap")][:5]
    findings = {"vendor": vendor_name, "recommendation": reco, "reason": reason,
                "weighted_total": roll["weighted_total"],
                "weakest_categories": [{"name": c["name"], "raw_1_5": c["raw_1_5"]} for c in weak],
                "unmet_gating": roll["gating"]["unmet_gating"],
                "sample_evidence_gaps": [g["evidence_gap"] for g in gaps]}

    if is_mock(model_id):
        narrative, dissent, risks = _mock_narrative(findings)
    else:
        narrative, dissent, risks = _llm_narrative(ctx, findings, model_id)
    return Vote(recommendation=reco, confidence="Medium", narrative=narrative,
                dissent=dissent, top_risks=risks, evidence_to_close=[
                    g["evidence_gap"] for g in gaps][:3], mode="single")

def _mock_narrative(f):
    weak = ", ".join(f'{c["name"]} ({c["raw_1_5"]}/5)' for c in f["weakest_categories"]) or "none"
    narrative = (f'{f["vendor"]} lands at {f["weighted_total"]}/100 — {f["recommendation"]} '
                 f'({f["reason"]}). Weakest areas: {weak}.')
    dissent = ("The offline heuristic rewards keyword overlap; a live-model pass could move "
               "borderline categories in either direction.")
    risks = [g for g in f["sample_evidence_gaps"][:3]] or ["No material risks surfaced."]
    return narrative, dissent, risks

def _llm_narrative(ctx, findings, model_id):
    system = ctx.persona_system_prompt()
    user = ("FINDINGS (computed deterministically — do NOT change the recommendation):\n" +
            json.dumps(findings, indent=1) +
            '\n\nReturn STRICT JSON {"narrative": "<=180 words", "dissent": "<=80 words '
            'steel-manning the opposite view", "top_risks": ["...", "..."]}')
    try:
        raw = LLMClient().generate(system=system, user=user, model_id=model_id, expect_json=True)
        d = extract_json(raw)
        return (str(d.get("narrative", "")), str(d.get("dissent", "")),
                [str(r) for r in d.get("top_risks", [])][:5])
    except Exception:
        return _mock_narrative(findings)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_vote.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/agent/vote.py backend/tests/test_vote.py
git commit -m "feat: generalized vote with deterministic bands and LLM narrative"
```

---

### Task 10: Evaluation API with batch-level resumability

**Files:**
- Modify: `backend/app.py`, `backend/tests/test_evaluate_api.py` (new)

**Interfaces:**
- Consumes: `score_requirements` (Task 8), `rollup`/`rank_vendors` (Task 3), `synthesize_vote` (Task 9), `ingest.extract_sources` (unchanged) for file/URL uploads.
- Produces:
  - `POST /api/projects/<pid>/evaluate` `{vendor_id, proposal_text?, scoring_model, vote_model}` → `{job_id}`. Runs in a background thread (same pattern as the parent's evaluate: a module-level `_JOBS = {}` dict of `{job_id: {"status", "progress", "message", "evaluation_id", "cancel": threading.Event}}`).
  - `POST /api/projects/<pid>/evaluate_upload` — multipart variant (`vendor_id, files[], urls`) that runs `ingest.extract_sources` then delegates to the same runner.
  - `GET /api/evaluate/status/<job_id>` → job dict (minus the Event).
  - `POST /api/evaluate/cancel/<job_id>` → sets the Event.
  - `GET /api/projects/<pid>/results` → `{results: [{evaluation_id, vendor, status, weighted_total, category_scores, gating, vote, n_scores, is_demo, engine_warning, created_at}], "ranking": [vendor names]}` — rollup computed on read from stored scores + active weight profile, so results always reflect current weights.
  - **Resumability:** the runner writes each batch to `requirement_scores` inside `on_batch` (INSERT OR REPLACE) and re-queries existing scores at start, skipping already-scored requirement IDs. Re-POSTing evaluate for a vendor whose last evaluation is `failed`/`cancelled` RESUMES it (same evaluation row) instead of starting over; a vendor with a `done` evaluation gets a fresh evaluation row (re-evaluation replaces on completion).
- Evaluation runner outline (complete code in step 3): create/reuse evaluation row → `score_requirements(..., on_batch=persist)` with its own `db.connect()` (threads don't share the Flask-g connection) → rollup from ALL stored scores → `synthesize_vote` → store vote JSON, status=done.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_evaluate_api.py`:

```python
import io, json, time

def _setup(client):
    pid = client.post("/api/projects", json={"name": "P"}).get_json()["project"]["id"]
    import io as _io
    from tests.test_intake import GOOD
    parsed = client.post(f"/api/projects/{pid}/intake",
                         data={"file": (_io.BytesIO(GOOD), "r.xlsx")},
                         content_type="multipart/form-data").get_json()
    client.post(f"/api/projects/{pid}/intake/confirm", json=parsed)
    vid = client.post(f"/api/projects/{pid}/vendors", json={"name": "V"}).get_json()["vendor"]["id"]
    return pid, vid

def _wait(client, job_id, timeout=15):
    for _ in range(timeout * 10):
        s = client.get(f"/api/evaluate/status/{job_id}").get_json()
        if s["status"] in ("done", "failed"):
            return s
        time.sleep(0.1)
    raise AssertionError("job did not finish")

def test_mock_evaluation_end_to_end(client):
    pid, vid = _setup(client)
    r = client.post(f"/api/projects/{pid}/evaluate",
                    json={"vendor_id": vid, "proposal_text": "We support multi-entity GL and REST APIs.",
                          "scoring_model": "mock", "vote_model": "mock"})
    job = r.get_json()["job_id"]
    assert _wait(client, job)["status"] == "done"
    res = client.get(f"/api/projects/{pid}/results").get_json()
    assert len(res["results"]) == 1
    ev = res["results"][0]
    assert ev["n_scores"] == 2                     # 3 uploaded, 1 is Won't
    assert ev["vote"]["recommendation"] in ("Recommend", "Shortlist", "Reject", "Disqualified")
    assert res["ranking"] == ["V"]

def test_results_reflect_active_weights(client):
    pid, vid = _setup(client)
    job = client.post(f"/api/projects/{pid}/evaluate",
                      json={"vendor_id": vid, "proposal_text": "x",
                            "scoring_model": "mock", "vote_model": "mock"}).get_json()["job_id"]
    _wait(client, job)
    before = client.get(f"/api/projects/{pid}/results").get_json()["results"][0]["weighted_total"]
    # flip weights via a new active profile: all weight on category 2
    cats = client.get(f"/api/projects/{pid}").get_json()["categories"]
    import db as dbmod
    conn = dbmod.connect(); 
    conn.execute("INSERT INTO weight_profiles (project_id, name, weights, is_active) VALUES (?,?,?,1)",
                 (pid, "Flipped", json.dumps({str(cats[1]["id"]): 100.0})))
    conn.execute("UPDATE weight_profiles SET is_active=0 WHERE project_id=? AND name!='Flipped'", (pid,))
    conn.commit(); conn.close()
    after = client.get(f"/api/projects/{pid}/results").get_json()["results"][0]["weighted_total"]
    assert after != before

def test_evaluate_missing_vendor_400(client):
    pid, _ = _setup(client)
    r = client.post(f"/api/projects/{pid}/evaluate",
                    json={"proposal_text": "x", "scoring_model": "mock", "vote_model": "mock"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python3 -m pytest tests/test_evaluate_api.py -v`
Expected: 404s / failures — routes don't exist.

- [ ] **Step 3: Implement in `backend/app.py`**

```python
import threading, uuid
from agent.scoring import score_requirements
from agent.rollup import rollup, rank_vendors
from agent.vote import synthesize_vote
from agent import ingest

_JOBS = {}

def _run_evaluation(pid, vid, proposal_text, scoring_model, vote_model, job_id):
    job = _JOBS[job_id]
    conn = db.connect()
    try:
        from agent.project_context import load_project_context
        ctx = load_project_context(conn, pid)
        row = conn.execute(
            "SELECT id FROM evaluations WHERE project_id=? AND vendor_id=? "
            "AND status IN ('failed','cancelled') ORDER BY id DESC LIMIT 1", (pid, vid)).fetchone()
        if row:
            eid = row["id"]
            conn.execute("UPDATE evaluations SET status='running' WHERE id=?", (eid,))
        else:
            cur = conn.execute(
                "INSERT INTO evaluations (project_id, vendor_id, scoring_model, vote_model,"
                " is_demo, proposal_text) VALUES (?,?,?,?,?,?)",
                (pid, vid, scoring_model, vote_model,
                 1 if scoring_model == "mock" else 0, proposal_text[:200000]))
            eid = cur.lastrowid
        conn.commit()
        job["evaluation_id"] = eid

        done_ids = {r["requirement_id"] for r in conn.execute(
            "SELECT requirement_id FROM requirement_scores WHERE evaluation_id=?", (eid,))}

        def persist(batch):
            conn.executemany(
                "INSERT OR REPLACE INTO requirement_scores (evaluation_id, requirement_id,"
                " met, quality, response_code, confidence, rationale, evidence_gap, scored_live)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                [(eid, s["requirement_id"], s["met"], s["quality"], s["response_code"],
                  s["confidence"], s["rationale"], s["evidence_gap"], s["scored_live"])
                 for s in batch])
            conn.commit()
            job["progress"] = min(0.9, job.get("progress", 0) + 0.9 * len(batch) / max(1, job["total"]))

        # skip already-persisted requirements on resume
        all_reqs = [r for r in ctx.requirements() if r["priority"] != "Wont"]
        job["total"] = len(all_reqs)
        pending = [r for r in all_reqs if r["id"] not in done_ids]
        if pending:
            class _PendingCtx:
                def __init__(self, base, pending):
                    self._base, self._pending = base, pending
                def requirements(self): return self._pending
                def persona_system_prompt(self): return self._base.persona_system_prompt()
                def scoring_context(self): return self._base.scoring_context()
            _, live, fb = score_requirements(_PendingCtx(ctx, pending), _vendor_name(conn, vid),
                                             proposal_text, scoring_model, on_batch=persist,
                                             cancelled=job["cancel"])
            if fb and scoring_model != "mock":
                conn.execute("UPDATE evaluations SET engine_warning=? WHERE id=?",
                             (f"{fb} requirement(s) fell back to the offline engine", eid))
        if job["cancel"].is_set():
            conn.execute("UPDATE evaluations SET status='cancelled' WHERE id=?", (eid,))
            conn.commit(); job["status"] = "cancelled"; return

        scores = [dict(r) for r in conn.execute(
            "SELECT rs.*, r.category_id, r.priority, r.ext_id FROM requirement_scores rs"
            " JOIN requirements r ON r.id = rs.requirement_id WHERE rs.evaluation_id=?", (eid,))]
        roll = rollup(scores, ctx.categories, ctx.active_weights(),
                      ctx.priority_multipliers, ctx.gating_config)
        vote = synthesize_vote(ctx, _vendor_name(conn, vid), roll, scores, vote_model)
        conn.execute("UPDATE evaluations SET status='done', vote=? WHERE id=?",
                     (json.dumps(vote.to_dict()), eid))
        # a fresh 'done' evaluation supersedes older ones for the vendor
        conn.execute("DELETE FROM evaluations WHERE project_id=? AND vendor_id=? AND id!=?"
                     " AND status='done'", (pid, vid, eid))
        conn.commit()
        job["status"], job["progress"] = "done", 1.0
    except Exception as e:
        try:
            conn.execute("UPDATE evaluations SET status='failed' WHERE id=?", (eid,))
            conn.commit()
        except Exception:
            pass
        job["status"], job["message"] = "failed", str(e)
    finally:
        conn.close()

def _vendor_name(conn, vid):
    row = conn.execute("SELECT name FROM vendors WHERE id=?", (vid,)).fetchone()
    return row["name"] if row else f"vendor {vid}"

@app.route("/api/projects/<int:pid>/evaluate", methods=["POST"])
@require_auth
def evaluate(pid):
    body = request.get_json(force=True, silent=True) or {}
    vid = body.get("vendor_id")
    conn = db.get_db()
    if not vid or conn.execute("SELECT 1 FROM vendors WHERE id=? AND project_id=?",
                               (vid, pid)).fetchone() is None:
        return jsonify({"error": "vendor_id is required and must belong to the project"}), 400
    if conn.execute("SELECT COUNT(*) c FROM requirements WHERE project_id=?", (pid,)).fetchone()["c"] == 0:
        return jsonify({"error": "project has no requirements — upload the Excel first"}), 400
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"status": "running", "progress": 0.0, "message": "",
                     "evaluation_id": None, "cancel": threading.Event(), "total": 0}
    t = threading.Thread(target=_run_evaluation, daemon=True,
                         args=(pid, vid, body.get("proposal_text", ""),
                               body.get("scoring_model", "mock"),
                               body.get("vote_model", "mock"), job_id))
    t.start()
    return jsonify({"job_id": job_id})

@app.route("/api/evaluate/status/<job_id>")
@require_auth
def evaluate_status(job_id):
    job = _JOBS.get(job_id)
    if not job:
        return jsonify({"error": "unknown job"}), 404
    return jsonify({k: v for k, v in job.items() if k != "cancel"})

@app.route("/api/evaluate/cancel/<job_id>", methods=["POST"])
@require_auth
def evaluate_cancel(job_id):
    job = _JOBS.get(job_id)
    if job:
        job["cancel"].set()
    return jsonify({"ok": True})

@app.route("/api/projects/<int:pid>/results")
@require_auth
def results(pid):
    conn = db.get_db()
    try:
        from agent.project_context import load_project_context
        ctx = load_project_context(conn, pid)
    except ValueError:
        return jsonify({"error": "project not found"}), 404
    out, rolls = [], {}
    rows = conn.execute(
        "SELECT e.*, v.name vendor_name FROM evaluations e JOIN vendors v ON v.id=e.vendor_id"
        " WHERE e.project_id=? AND e.status='done' ORDER BY e.created_at DESC", (pid,)).fetchall()
    for e in rows:
        scores = [dict(r) for r in conn.execute(
            "SELECT rs.*, r.category_id, r.priority, r.ext_id, r.text FROM requirement_scores rs"
            " JOIN requirements r ON r.id=rs.requirement_id WHERE rs.evaluation_id=?", (e["id"],))]
        roll = rollup(scores, ctx.categories, ctx.active_weights(),
                      ctx.priority_multipliers, ctx.gating_config)
        rolls[e["vendor_name"]] = roll
        out.append({"evaluation_id": e["id"], "vendor": e["vendor_name"], "status": e["status"],
                    "weighted_total": roll["weighted_total"],
                    "category_scores": roll["category_scores"], "gating": roll["gating"],
                    "vote": json.loads(e["vote"]) if e["vote"] else None,
                    "requirement_scores": scores, "n_scores": len(scores),
                    "is_demo": bool(e["is_demo"]), "engine_warning": e["engine_warning"],
                    "created_at": e["created_at"]})
    return jsonify({"results": out, "ranking": rank_vendors(rolls) if rolls else []})
```

Also add `evaluate_upload` (multipart) delegating to the same `_run_evaluation` after `ingest.extract_sources(paths, urls)`. The file-saving pattern to copy is the parent repo's `app.py` `/api/evaluate_upload` route (parent lines 484–556: save each upload to a tempdir, collect paths, pass to extract). Add the same empty-file (OneDrive placeholder) and 10 MB checks used in Task 7's intake route.

- [ ] **Step 4: Run tests**

Run: `cd backend && python3 -m pytest tests/test_evaluate_api.py tests -v`
Expected: all pass (full suite green).

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/tests/test_evaluate_api.py
git commit -m "feat: evaluation pipeline with batch persistence, resume, and weight-aware results"
```

---

### Task 11: Per-project chat

**Files:**
- Rewrite: `backend/agent/chat.py`; Modify: `backend/app.py` (one route)

**Interfaces:**
- Consumes: `ProjectContext`, results query from Task 10, `ingest.build_retrieval_index/relevant_passages`, `providers`.
- Produces: `chat.answer(ctx, question, results, model_id, history=None) -> str`; route `POST /api/projects/<pid>/chat` `{question, model_id, history?}` → `{answer}`. Context assembled from: context_brief, top-10 requirement rows matching the question terms, and per-vendor summary lines (total, verdict, weakest categories) from the results payload. Mock mode returns a deterministic summary of the retrieved context (parent `_mock_answer` pattern).

- [ ] **Step 1: Test** (`backend/tests/test_chat.py`): create project + one mock evaluation (reuse `_setup`/`_wait` from `tests/test_evaluate_api.py` via import), then `POST /api/projects/<pid>/chat {"question": "who leads and why", "model_id": "mock"}` → 200, non-empty `answer` mentioning the vendor name. Run, expect failure.

- [ ] **Step 2: Implement** — rewrite `chat.py`: `_project_context_blurb(ctx, question)` (requirement retrieval by term overlap — reuse `build_retrieval_index` over the concatenated requirement texts), `_results_blurb(results)` (per vendor: `f"{vendor}: {weighted_total}/100, {vote.recommendation}"` plus top unmet gating), `answer()` calling `LLMClient().generate(system=ctx.persona_system_prompt(), user=...)` with mock fallback. Route follows the Task 5 pattern (404 on bad pid, `@require_auth`).

- [ ] **Step 3: Run** `python3 -m pytest tests/test_chat.py -v` → pass. Full suite green.

- [ ] **Step 4: Commit** `git commit -m "feat: project-scoped retrieval chat"`

---

### Task 12: Frontend split + Phase 1 screens

No JS test runner exists (no build toolchain) — verification for this task is the manual end-to-end script in Task 13. Keep each file under ~600 lines.

**Files:**
- Rewrite: `frontend/index.html` (shell only)
- Create: `frontend/js/api.js`, `frontend/js/util.js`, `frontend/js/components.js`, `frontend/js/projects.js`, `frontend/js/evaluation.js`, `frontend/js/app.js`

**Interfaces:**
- Consumes: every route from Tasks 5–11.
- Produces: the browser app. Globals (no module system with Babel standalone): each file attaches to `window.RFP` namespace — `RFP.api`, `RFP.util`, `RFP.ui` (shared components), `RFP.screens`.

- [ ] **Step 1: Shell `frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RFP Evaluation Agent</title>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>/* copy the parent's <style> block verbatim, minus FSM-specific classes */</style>
</head>
<body>
  <div id="root"></div>
  <script>window.RFP = {};</script>
  <script type="text/babel" data-presets="react" src="/js/util.js"></script>
  <script type="text/babel" data-presets="react" src="/js/api.js"></script>
  <script type="text/babel" data-presets="react" src="/js/components.js"></script>
  <script type="text/babel" data-presets="react" src="/js/projects.js"></script>
  <script type="text/babel" data-presets="react" src="/js/evaluation.js"></script>
  <script type="text/babel" data-presets="react" src="/js/app.js"></script>
</body>
</html>
```

Babel standalone fetches `src` scripts via XHR — this only works served from Flask (`/js/<fname>` route from Task 5), which is the Phase 1 contract. Login screen: copy the parent's login component into `app.js` unchanged.

- [ ] **Step 2: `frontend/js/api.js`**

```jsx
(function () {
  async function jget(u) {
    const r = await fetch(u, { credentials: "same-origin" });
    if (r.status === 401) { window.RFP.onAuthFail && window.RFP.onAuthFail(); throw new Error("auth"); }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText);
    return r.json();
  }
  async function jpost(u, body, method = "POST") {
    const r = await fetch(u, { method, credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    if (r.status === 401) { window.RFP.onAuthFail && window.RFP.onAuthFail(); throw new Error("auth"); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.error || r.statusText); e.status = r.status; e.data = data; throw e; }
    return data;
  }
  async function upload(u, formData) {
    const r = await fetch(u, { method: "POST", credentials: "same-origin", body: formData });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const e = new Error(data.error || r.statusText); e.status = r.status; throw e; }
    return data;
  }
  window.RFP.api = {
    jget, jpost, upload,
    projects: () => jget("/api/projects"),
    createProject: (b) => jpost("/api/projects", b),
    project: (id) => jget(`/api/projects/${id}`),
    patchProject: (id, b) => jpost(`/api/projects/${id}`, b, "PATCH"),
    vendors: (id) => jget(`/api/projects/${id}/vendors`),
    addVendor: (id, b) => jpost(`/api/projects/${id}/vendors`, b),
    intakePreview: (id, fd) => upload(`/api/projects/${id}/intake`, fd),
    intakeConfirm: (id, parsed) => jpost(`/api/projects/${id}/intake/confirm`, parsed),
    evaluate: (id, b) => jpost(`/api/projects/${id}/evaluate`, b),
    jobStatus: (jid) => jget(`/api/evaluate/status/${jid}`),
    results: (id) => jget(`/api/projects/${id}/results`),
    chat: (id, b) => jpost(`/api/projects/${id}/chat`, b),
    models: () => jget("/api/models"),
  };
})();
```

- [ ] **Step 3: Move existing code**

- `util.js` ← parent index.html functions: `toCSV, csvSlug, exportFilename, htmlEsc, tableHTML, downloadCSV, leadAndRest` (drop FSM-specific derive* helpers: `deriveCompleteness, deriveRedFlags, deriveAdvisoryRead, archetypePriorities, cmpCapabilityLead, disqualificationRows`). Attach each to `window.RFP.util`.
- `components.js` ← `BarRow, Disclosure, Tabs, Picker, ModelControls` verbatim, attached to `window.RFP.ui`.
- `evaluation.js` ← `Dashboard, VendorDetail` adapted: props change from the FSM results shape to the Task 10 `/results` payload (`vendor, weighted_total, category_scores[{name, raw_1_5, weighted_points}], gating{disqualified, verdict, summary, unmet_gating}, vote{recommendation, narrative, dissent, top_risks}, requirement_scores`). Delete segment-fit, capability-heatmap, agentic-future, and external-research sections. Requirement table columns: ext_id, text, priority, met, quality, response_code, confidence, rationale.

- [ ] **Step 4: New screens in `projects.js`**

```jsx
(function () {
  const { useState, useEffect } = React;
  const api = window.RFP.api;

  function ProjectPicker({ onOpen }) {
    const [projects, setProjects] = useState(null);
    const [form, setForm] = useState({ name: "", client: "", context_brief: "" });
    useEffect(() => { api.projects().then(d => setProjects(d.projects)); }, []);
    if (!projects) return <div className="muted">Loading…</div>;
    return (
      <div className="project-picker">
        <h2>Projects</h2>
        {projects.map(p => (
          <div key={p.id} className="card row" onClick={() => onOpen(p.id)}>
            <b>{p.name}</b> <span className="muted">{p.client}</span>
            <span className="muted">{p.n_requirements} requirements · {p.n_vendors} vendors</span>
          </div>
        ))}
        <h3>New project</h3>
        <input placeholder="Project name" value={form.name}
               onChange={e => setForm({ ...form, name: e.target.value })} />
        <input placeholder="Client" value={form.client}
               onChange={e => setForm({ ...form, client: e.target.value })} />
        <textarea placeholder="Context brief — industry, client situation, what matters most"
                  value={form.context_brief}
                  onChange={e => setForm({ ...form, context_brief: e.target.value })} />
        <button disabled={!form.name.trim()}
                onClick={() => api.createProject(form).then(d => onOpen(d.project.id))}>
          Create project
        </button>
      </div>
    );
  }

  function IntakeWizard({ projectId, onDone }) {
    const [parsed, setParsed] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    async function pick(e) {
      const f = e.target.files[0];
      if (!f) return;
      if (f.size === 0) { setError("That file is empty — if it lives in OneDrive, copy it locally first."); return; }
      const fd = new FormData(); fd.append("file", f);
      setBusy(true); setError("");
      try { setParsed(await api.intakePreview(projectId, fd)); }
      catch (err) { setError(err.message); }
      finally { setBusy(false); }
    }
    async function confirm(replace) {
      try { await api.intakeConfirm(projectId, replace ? { ...parsed, replace: true } : parsed); onDone(); }
      catch (err) {
        if (err.status === 409) {
          if (window.confirm("This project already has requirements. Replace EVERYTHING, including existing evaluations?"))
            return confirm(true);
          return;
        }
        setError(err.message);
      }
    }
    return (
      <div className="intake">
        <h2>Upload requirements</h2>
        <p><a href="/api/template">Download the Excel template</a>, fill it in, then upload it here.</p>
        <input type="file" accept=".xlsx" onChange={pick} disabled={busy} />
        {error && <div className="error">{error}</div>}
        {parsed && (
          <div className="preview card">
            <h3>Preview</h3>
            <p>{parsed.summary.n_requirements} requirements in {parsed.summary.n_categories} categories.
               Priorities: {Object.entries(parsed.summary.by_priority || {}).map(([k, v]) => `${k} ${v}`).join(", ")}.
               Weights sum to {parsed.summary.weight_sum}.</p>
            {parsed.errors.length > 0 ? (
              <div className="error">
                <b>Fix these in the file and re-upload:</b>
                <ul>{parsed.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
              </div>
            ) : (
              <button onClick={() => confirm(false)}>Confirm and load</button>
            )}
          </div>
        )}
      </div>
    );
  }

  window.RFP.screens = Object.assign(window.RFP.screens || {}, { ProjectPicker, IntakeWizard });
})();
```

- [ ] **Step 5: `app.js` root**

`App` component: session check (parent's pattern) → if no `projectId` in state (persist in `localStorage["rfp.projectId"]`) show `ProjectPicker` → project view with tabs: **Setup** (project fields + IntakeWizard + vendor list/add), **Evaluate** (vendor picker, proposal textarea/file upload, model pickers via `RFP.ui.ModelControls`, run button polling `jobStatus` with a progress bar), **Results** (`Dashboard` + `VendorDetail`), **Chat** (parent's chat panel pointed at `/api/projects/<pid>/chat`). A header button switches projects (clears localStorage key).

- [ ] **Step 6: Manual smoke check**

```bash
cd backend && AUTH_DISABLED=1 python3 app.py
```

Open http://127.0.0.1:8000 — create project → download template → upload it → confirm → add vendor → evaluate (mock) → results render → chat answers. Fix what breaks.

- [ ] **Step 7: Commit**

```bash
git add frontend backend/app.py
git commit -m "feat: split frontend into namespaced babel files with project screens"
```

---

### Task 13: End-to-end verification, README, CLAUDE.md

**Files:**
- Create: `README.md`, `CLAUDE.md` (fork versions)
- Modify: anything the E2E pass shakes out

- [ ] **Step 1: Full test suite**

Run: `cd backend && python3 -m pytest tests -v`
Expected: all green. Record the count.

- [ ] **Step 2: Scripted E2E against a live server (mock engine, no keys)**

```bash
cd backend && DB_PATH=/tmp/e2e.db AUTH_DISABLED=1 python3 app.py &
sleep 2
# create project
PID=$(curl -s -X POST localhost:8000/api/projects -H 'Content-Type: application/json' \
  -d '{"name":"E2E","context_brief":"test"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["project"]["id"])')
# template → fill → upload: use the template itself (it ships valid example rows)
curl -s localhost:8000/api/template -o /tmp/t.xlsx
curl -s -X POST localhost:8000/api/projects/$PID/intake -F file=@/tmp/t.xlsx > /tmp/parsed.json
curl -s -X POST localhost:8000/api/projects/$PID/intake/confirm -H 'Content-Type: application/json' \
  -d @/tmp/parsed.json
# vendor + evaluate + poll + results  (assert weighted_total present and gating computed)
```

Expected: results JSON has one vendor, `weighted_total` between 0 and 100, `vote.recommendation` set. Then kill the server, restart with the same `DB_PATH`, and GET results again — **they survive the restart** (the point of SQLite).

- [ ] **Step 3: Write fork `README.md`** — run instructions (template → upload → evaluate → results), env vars (`DB_PATH`, `PORT`, `AUTH_DISABLED` dev-only, API keys, `RESULTS_MAX_CONCURRENCY` if carried), and a one-paragraph "what this is". Write fork `CLAUDE.md` — same conventions sections as the parent minus FSM specifics, plus: SQLite is the store; rollup.py is pure and shared-fixture-tested; every project-scoped route takes project_id; tests exist and must pass (`python3 -m pytest backend/tests`).

- [ ] **Step 4: Commit and push (ask user approval for the push)**

```bash
git add -A && git commit -m "docs: fork README and CLAUDE.md; e2e verified"
git push -u origin main
```

---

## Plan self-review notes (already applied)

- Task 2's `test_project_insert_roundtrip` must use `db.new_project()`, per the note in Task 2 Step 4.
- `relevant_passages` signature in Task 8 must be checked against the copied `ingest.py` before use.
- Phase 1 deliberately omits: weight-studio UI, sliders, scenarios/archetypes/sensitivity (Phase 2); mapping wizard, standalone export, matrix upload (Phase 3). The `scenarios` table ships empty in Phase 1 — that is expected.
