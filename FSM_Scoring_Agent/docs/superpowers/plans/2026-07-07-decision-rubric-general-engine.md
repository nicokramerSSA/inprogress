# Decision-Rubric General Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PR #58's hard-coded per-vendor scoring with a general, evidence-derived decision engine that reproduces the committee's verdicts from the real July-2 data.

**Architecture:** Keep PR #58's seven decision categories, its computed category formulas, and its UI reframe. Delete the four vendor-name lookup tables and the fabricated `ARCH-GATE`. Reject vendors on a general enterprise-scale / vendor-viability gate (dossier-driven, capping the headline into the Reject band), turn unmet Musts into score effects instead of auto-disqualification, then migrate the five existing evaluations in place by re-deriving them from their stored per-requirement scores.

**Tech Stack:** Python 3.12, Flask, `unittest`. No new dependencies. Offline "mock" engine must keep working with no API keys.

## Global Constraints

- API keys come from the environment only, never written to disk (`providers.py` reads at call time).
- The offline "mock" engine must always run keyless. Do not break it.
- Gating stays deterministic and computed from the requirement scores, never LLM-overridable.
- Priority-weighted rollups keep the Must 3× · Should 2× · Could 1× weighting (`_PRIORITY_WEIGHT`).
- The two scoring lenses stay independent: SSA/decision categories (`scorecard.json`) vs RFP §30 capabilities (`capabilities.json`).
- No vendor names in the scoring engine. Behavior is driven by config JSON and the research dossier, not by `if vendor == ...`.
- Category weights in `scorecard.json` must sum to 1.0.
- `capabilities.json` is unchanged by this work.
- Recommendation bands (`vote.py`): headline ≥78 Recommend, ≥65 Shortlist, else Reject; `gating.disqualified=True` overrides to "Disqualified".

---

### Task 1: Working branch on the PR #58 base + July-2 snapshot fixture

Base the work on PR #58 so we inherit the config reframe and computed formulas, then commit the real July-2 data as a fixture (it doubles as the backup the spec requires).

**Files:**
- Create: `FSM_Scoring_Agent/backend/tests/fixtures/july2_store_snapshot.json`
- Branch: `fix/decision-rubric-general-engine` (already exists with the spec + handoff commits, based on `main`)

**Interfaces:**
- Produces: a committed fixture `july2_store_snapshot.json` — a JSON list of the five real `VendorEvaluation` dicts (each with `requirement_scores`, `vendor`, `weighted_total`, `gating`, ...). Later tasks read it as the calibration and idempotency input.

- [ ] **Step 1: Rebase the doc branch onto the PR #58 branch**

The branch currently holds two doc commits on top of `main`. Re-point it so PR #58's changes sit underneath them.

```bash
cd "FSM_Scoring_Agent/.."   # repo root: RFP Agent
git fetch origin codex/update-fsm-decision-rubric
git rebase --onto origin/codex/update-fsm-decision-rubric main fix/decision-rubric-general-engine
```

Expected: the two doc commits replay cleanly on top of the PR #58 tip (no conflicts — they only add files under `docs/`).

- [ ] **Step 2: Verify the PR #58 engine and config are present**

```bash
git grep -l "_KNOWN_DECISION_DIMENSIONS" FSM_Scoring_Agent/backend/agent/scoring.py
python3 -c "import json; c=json.load(open('FSM_Scoring_Agent/backend/config/scorecard.json'))['categories']; print([x['id'] for x in c])"
```
Expected: `scoring.py` matches; category ids print `['operating', 'project', 'architecture', 'implementation', 'evidence', 'agentic', 'commercial']`.

- [ ] **Step 3: Save the July-2 snapshot fixture**

The authoritative five results were pulled from prod earlier to
`<scratchpad>/results.json`. Copy that file into the repo as the fixture. If it is
no longer on disk, re-pull it first (log in to the prod app and
`GET /api/results`, as done during the investigation).

```bash
mkdir -p FSM_Scoring_Agent/backend/tests/fixtures
cp "<scratchpad>/results.json" FSM_Scoring_Agent/backend/tests/fixtures/july2_store_snapshot.json
python3 -c "import json; d=json.load(open('FSM_Scoring_Agent/backend/tests/fixtures/july2_store_snapshot.json')); assert isinstance(d,list) and len(d)==5, d; assert all(len(v['requirement_scores'])==422 for v in d); print('ok', sorted(v['vendor'] for v in d))"
```
Expected: `ok ['BuildOps', 'IFS', 'Salesforce', 'ServiceMax', 'ServiceTitan']`.

- [ ] **Step 4: Commit**

```bash
git add FSM_Scoring_Agent/backend/tests/fixtures/july2_store_snapshot.json
git commit -m "test(rubric): commit July-2 prod snapshot as calibration fixture + backup"
```

---

### Task 2: Promote tuning knobs into scorecard.json; reword gating doctrine

Move the values calibration will touch out of code and into config, and fix the doctrine wording so it names the enterprise-scale gate honestly.

**Files:**
- Modify: `FSM_Scoring_Agent/backend/config/scorecard.json` (`gating_rules` object; add `decision_knobs`)
- Modify: `FSM_Scoring_Agent/backend/config/persona.json` (weighting_doctrine implications wording)
- Test: `FSM_Scoring_Agent/backend/tests/test_decision_rubric.py`

**Interfaces:**
- Produces: `scorecard["decision_knobs"]` with keys `enterprise_scale_bar` (rating word, e.g. `"High"`), `scale_gate_cap` (float, headline ceiling for a gated vendor), and `operating_capability_weights` (map). Engine code in later tasks reads these with safe defaults.

- [ ] **Step 1: Write the failing test**

```python
# in test_decision_rubric.py
import json, os
CFG = os.path.join(os.path.dirname(__file__), "..", "config", "scorecard.json")

def test_decision_knobs_present_and_weights_sum_to_one():
    sc = json.load(open(CFG))
    knobs = sc["decision_knobs"]
    assert knobs["enterprise_scale_bar"] == "High"
    assert knobs["scale_gate_cap"] <= 64          # below the Shortlist floor (65)
    assert abs(sum(c["weight"] for c in sc["categories"]) - 1.0) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: FAIL with `KeyError: 'decision_knobs'`.

- [ ] **Step 3: Add the knobs and reword `gating_rules`**

In `scorecard.json`, add a sibling object after `gating_rules`:

```json
  "decision_knobs": {
    "enterprise_scale_bar": "High",
    "scale_gate_cap": 60,
    "operating_capability_weights": {
      "W2C": 0.28, "TPA": 0.20, "ACQ": 0.14, "EVG": 0.14, "RLC": 0.14, "CXR": 0.10
    }
  },
```

Replace the `gating_rules.description` string with:

```json
    "description": "Unmet Musts lower the score and are surfaced as risks; they no longer auto-disqualify. A vendor whose enterprise-scale / vendor-viability rating is below the bar is capped below the finalist range (a Reject), because a mid-market platform is not a fit for a 40-80 OpCo enterprise rollup regardless of functional coverage. Genuine single-tenant or union-isolation architectural failures remain hard gates."
```

- [ ] **Step 4: Reword the persona doctrine**

In `persona.json`, `weighting_doctrine.implications`, replace the first implication string:

```json
      "Treat enterprise scale / vendor viability, security, data access, and the enterprise operating model as gates/caps, not ordinary line-item preferences.",
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add FSM_Scoring_Agent/backend/config/scorecard.json FSM_Scoring_Agent/backend/config/persona.json FSM_Scoring_Agent/backend/tests/test_decision_rubric.py
git commit -m "feat(rubric): add tunable decision knobs to config; reword gate as enterprise-scale"
```

---

### Task 3: Enterprise-scale gate helper

A pure function that reads a vendor's dossier scale rating and reports whether it is below the configured bar.

**Files:**
- Modify: `FSM_Scoring_Agent/backend/agent/scoring.py` (add helpers near `_apply_decision_score_cap`)
- Test: `FSM_Scoring_Agent/backend/tests/test_decision_rubric.py`

**Interfaces:**
- Produces:
  - `_scale_tier(rating: str) -> int` — maps a rating word to 1..5.
  - `_enterprise_scale_gate(vendor: str) -> tuple[bool, str]` — returns `(gated, reason)`. `gated=True` when the vendor's `enterprise_scale` tier is below the `enterprise_scale_bar` tier; `reason` is a human sentence naming the rating, or `""` when not gated.

- [ ] **Step 1: Write the failing test**

```python
# in test_decision_rubric.py
from agent.scoring import _scale_tier, _enterprise_scale_gate

def test_scale_tier_mapping():
    assert _scale_tier("High") == 5
    assert _scale_tier("Med") == 3
    assert _scale_tier("Med-High") == 4
    assert _scale_tier("unknown") == 3   # safe default

def test_enterprise_scale_gate_uses_dossier():
    gated_bo, reason_bo = _enterprise_scale_gate("BuildOps")   # dossier scale = Med
    gated_ifs, _ = _enterprise_scale_gate("IFS")               # dossier scale = High
    assert gated_bo is True and "scale" in reason_bo.lower()
    assert gated_ifs is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: FAIL with `ImportError` / `cannot import name '_scale_tier'`.

- [ ] **Step 3: Implement the helpers**

Add to `scoring.py` (place just above `_apply_decision_score_cap`):

```python
_SCALE_TIER = {
    "low": 1, "low-med": 2, "med-low": 2,
    "med": 3, "medium": 3,
    "med-high": 4, "high-med": 4,
    "high": 5,
}


def _scale_tier(rating: str) -> int:
    """Map an enterprise-scale rating word to an ordinal tier (1..5). Unknown -> 3."""
    return _SCALE_TIER.get(str(rating).strip().lower(), 3)


def _enterprise_scale_gate(vendor: str) -> tuple[bool, str]:
    """A vendor whose dossier enterprise_scale is below the configured bar is gated
    out of the finalist range. Returns (gated, reason)."""
    kb = get_kb()
    bar = kb.scorecard.get("decision_knobs", {}).get("enterprise_scale_bar", "High")
    rating = (kb.vendor_profile(vendor).get("ratings") or {}).get("enterprise_scale", "Medium")
    if _scale_tier(rating) < _scale_tier(bar):
        return True, (f"Enterprise scale rated {rating} (bar: {bar}) — mid-market fit, "
                      f"not an enterprise platform for a 40-80 OpCo rollup.")
    return False, ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add FSM_Scoring_Agent/backend/agent/scoring.py FSM_Scoring_Agent/backend/tests/test_decision_rubric.py
git commit -m "feat(rubric): add dossier-driven enterprise-scale gate helper"
```

---

### Task 4: Unmet Musts no longer auto-disqualify

`_compute_gating` currently sets `disqualified = len(unmet) > 0`. Keep collecting unmet Musts (for risk display) but stop disqualifying on them.

**Files:**
- Modify: `FSM_Scoring_Agent/backend/agent/scoring.py` (`_compute_gating`)
- Test: `FSM_Scoring_Agent/backend/tests/test_decision_rubric.py`

**Interfaces:**
- Consumes: `GatingResult` (schemas.py) — unchanged shape.
- Produces: `_compute_gating(...)` now returns `disqualified=False` even when unmet Musts exist; `unmet_must_count`/`unmet_musts`/`architectural_gate_flags` still populated.

- [ ] **Step 1: Write the failing test**

```python
# in test_decision_rubric.py
from agent.schemas import RequirementScore
from agent.scoring import _compute_gating

def _req(rid, met, code, prio="Must"):
    return RequirementScore(rid=rid, requirement="", domain="Domain A", epic="",
        priority=prio, capability="W2C", met=met, quality=1, vendor_code=code,
        confidence="Low", rationale="", evidence="", evidence_gap="")

def test_unmet_musts_do_not_disqualify():
    scores = [_req("R1", "No", "GAP"), _req("R2", "No", "GAP")]
    g = _compute_gating(scores, "single-tenant, union, prevailing wage", {})
    assert g.disqualified is False
    assert g.unmet_must_count == 2       # still counted and surfaced
```

(Match the `RequirementScore` constructor to schemas.py; add any required fields the dataclass declares.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: FAIL — `disqualified` is `True`.

- [ ] **Step 3: Edit `_compute_gating`**

Replace the disqualification block at the end of `_compute_gating`:

```python
    # Unmet Musts are surfaced as risks but no longer auto-disqualify — the decision
    # score and the enterprise-scale gate carry the finalist/reject call now.
    disqualified = False
    summary = (
        f"Passes the Must gate. {len(unmet)} unmet 'Must' requirement(s) noted as risk"
        + (f"; {len(flags)} architectural flag(s) to confirm." if flags else ".")
    )
    return GatingResult(
        disqualified=disqualified, unmet_must_count=len(unmet),
        unmet_musts=unmet, architectural_gate_flags=flags, summary=summary,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add FSM_Scoring_Agent/backend/agent/scoring.py FSM_Scoring_Agent/backend/tests/test_decision_rubric.py
git commit -m "feat(rubric): unmet Musts become risk flags, not auto-disqualification"
```

---

### Task 5: De-hardcode category and capability scores

Remove the two `_KNOWN_*` early-returns so the computed formulas run for every vendor, and delete the now-unused constants.

**Files:**
- Modify: `FSM_Scoring_Agent/backend/agent/scoring.py` (`_decision_category_score`, `_capability_confidence_multiplier`; delete `_KNOWN_DECISION_DIMENSIONS`, `_KNOWN_CAPABILITY_MULTIPLIERS`, `_decision_category_rationale` vendor branches)
- Test: `FSM_Scoring_Agent/backend/tests/test_decision_rubric.py`

**Interfaces:**
- Produces: `_decision_category_score(cid, vendor, scores, capabilities)` and `_capability_confidence_multiplier(vendor, code, subset)` compute from evidence/dossier for all vendors, with no name lookup.

- [ ] **Step 1: Write the failing test**

```python
# in test_decision_rubric.py
from agent.sample import sample_proposal_text
from agent.scoring import evaluate_vendor

def test_categories_are_computed_not_frozen_lookup():
    # A made-up vendor name must still get differentiated, non-degenerate categories.
    ev = evaluate_vendor("Acme FSM", "", sample_proposal_text("IFS"), scoring_model="mock")
    raws = [c.raw_1_5 for c in ev.categories]
    assert len(set(round(r, 2) for r in raws)) > 1       # not all identical
    assert all(0.0 <= r <= 5.0 for r in raws)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: initially may PASS by luck (Acme is unknown so already computed). To force the real target, also assert the constants are gone:

```python
def test_hardcoded_tables_removed():
    import agent.scoring as s
    for name in ("_KNOWN_DECISION_DIMENSIONS", "_KNOWN_CAPABILITY_MULTIPLIERS",
                 "_DECISION_SCORE_CAPS", "_DECISION_GATE_OVERLAYS"):
        assert not hasattr(s, name), f"{name} still present"
```
Expected: FAIL — the constants still exist.

- [ ] **Step 3: Remove the early-returns and constants**

In `_decision_category_score`, delete the first two lines of the body:

```python
    known = _KNOWN_DECISION_DIMENSIONS.get(_known_vendor_key(vendor), {})
    if cid in known:
        return known[cid]
```

In `_capability_confidence_multiplier`, delete:

```python
    known = _KNOWN_CAPABILITY_MULTIPLIERS.get(_known_vendor_key(vendor), {})
    if code in known:
        return known[code]
```

Change the `operating` branch of `_decision_category_score` to read the weights from config (so calibration can tune them):

```python
    cap_scores = {c.code: c.score_1_5 for c in capabilities}
    if cid == "operating":
        weights = get_kb().scorecard.get("decision_knobs", {}).get(
            "operating_capability_weights", _OPERATING_CAPABILITY_WEIGHTS)
        return _clamp_1_5(_capability_average(cap_scores, weights))
```

Delete the constant blocks `_KNOWN_DECISION_DIMENSIONS`, `_KNOWN_CAPABILITY_MULTIPLIERS` (they become dead once the lookups are gone). Simplify `_decision_category_rationale` to drop the per-vendor (`key == "IFS"` etc.) branches, keeping only the base `_DECISION_CATEGORY_RATIONALE` lookup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add FSM_Scoring_Agent/backend/agent/scoring.py FSM_Scoring_Agent/backend/tests/test_decision_rubric.py
git commit -m "feat(rubric): compute category & capability scores for all vendors; drop lookup tables"
```

---

### Task 6: Wire the scale gate + cap into evaluate_vendor; delete the overlay

Replace the vendor-name cap and gate overlay with the general enterprise-scale cap, and record the reason on the gating result.

**Files:**
- Modify: `FSM_Scoring_Agent/backend/agent/scoring.py` (`evaluate_vendor`; delete `_apply_decision_score_cap`, `_apply_decision_gate_overlay`, `_DECISION_SCORE_CAPS`, `_DECISION_GATE_OVERLAYS`)
- Test: `FSM_Scoring_Agent/backend/tests/test_decision_rubric.py`

**Interfaces:**
- Consumes: `_enterprise_scale_gate(vendor)`, `scorecard["decision_knobs"]["scale_gate_cap"]`.
- Produces: `evaluate_vendor` caps the headline at `scale_gate_cap` when the scale gate fires and appends the reason to `gating.architectural_gate_flags`; no vendor-name code remains.

- [ ] **Step 1: Write the failing test**

```python
# in test_decision_rubric.py
def test_scale_gated_vendor_lands_in_reject_band():
    ev = evaluate_vendor("BuildOps", "", sample_proposal_text("BuildOps"), scoring_model="mock")
    assert ev.gating.disqualified is False
    assert ev.weighted_total <= 64                      # capped into Reject band
    assert any("scale" in f.lower() for f in ev.gating.architectural_gate_flags)

def test_high_scale_vendor_not_capped():
    ev = evaluate_vendor("IFS", "", sample_proposal_text("IFS"), scoring_model="mock")
    assert not any("scale" in f.lower() for f in ev.gating.architectural_gate_flags)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: FAIL (`_apply_decision_gate_overlay` still forces BuildOps `disqualified=True`, and the cap flag is absent).

- [ ] **Step 3: Edit `evaluate_vendor`**

Delete the overlay call (in the gating step):

```python
    gating = _apply_decision_gate_overlay(vendor, gating)   # DELETE this line
```

Replace the headline block:

```python
    # Headline weighted totals (0-100) ---------------------------------------
    raw_total = round(sum(c.weighted_points for c in categories), 1)
    scale_gated, scale_reason = _enterprise_scale_gate(vendor)
    if scale_gated:
        cap = kb.scorecard.get("decision_knobs", {}).get("scale_gate_cap", 60)
        weighted_total = round(min(raw_total, cap), 1)
        gating.architectural_gate_flags.append(scale_reason)
        gating.summary += f" {scale_reason}"
    else:
        weighted_total = raw_total
    cap_total = round(
        sum(c.weight * (c.score_1_5 / 5.0) * 100 for c in capabilities), 1
    )
```

Delete the functions `_apply_decision_score_cap` and `_apply_decision_gate_overlay` and the constants `_DECISION_SCORE_CAPS` and `_DECISION_GATE_OVERLAYS`. If `_known_vendor_key` now has no callers, delete it too (grep first).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: PASS.

- [ ] **Step 5: Verify no vendor names remain in the engine**

Run: `grep -nE '"IFS"|"Salesforce"|"ServiceMax"|"ServiceTitan"|"BuildOps"|ARCH-GATE' FSM_Scoring_Agent/backend/agent/scoring.py`
Expected: no matches.

- [ ] **Step 6: Commit**

```bash
git add FSM_Scoring_Agent/backend/agent/scoring.py FSM_Scoring_Agent/backend/tests/test_decision_rubric.py
git commit -m "feat(rubric): general enterprise-scale cap in evaluate_vendor; remove name-keyed overlay"
```

---

### Task 7: Property-based regression test

Replace the frozen-number test that pins IFS=77.8 etc. with property assertions over the real fixture.

**Files:**
- Modify: `FSM_Scoring_Agent/backend/tests/test_decision_rubric.py` (delete `test_mock_engine_uses_revised_decision_rubric_for_five_respondents`)
- Test: same file

**Interfaces:**
- Consumes: `july2_store_snapshot.json`, `evaluate_vendor`.

- [ ] **Step 1: Delete the frozen-number test and add property tests**

Remove `test_mock_engine_uses_revised_decision_rubric_for_five_respondents`. Add:

```python
def _rederive(vendor, req_scores):
    """Re-run only the rollups over stored per-req scores via the mock engine path."""
    from agent.scoring import (_rollup_capabilities, _rollup_categories,
                               _compute_gating, _enterprise_scale_gate, evaluate_vendor)
    # simplest: the mock engine is deterministic from the sample proposal, but for the
    # fixture we re-derive from stored scores in the migration module (Task 8). Here we
    # assert engine-level properties via evaluate_vendor on the sample proposals.
    return evaluate_vendor(vendor, "", sample_proposal_text(vendor), scoring_model="mock")

def test_engine_properties_for_all_five():
    from agent.vote import synthesize_vote
    for vendor in ["IFS", "Salesforce", "ServiceMax", "ServiceTitan", "BuildOps"]:
        ev = _rederive(vendor, None)
        ev.vote = synthesize_vote(ev, "mock")
        # categories present, in range, not all identical
        raws = [c.raw_1_5 for c in ev.categories]
        assert [c.id for c in ev.categories] == ["operating","project","architecture",
            "implementation","evidence","agentic","commercial"]
        assert all(0 <= r <= 5 for r in raws) and len(set(round(r,2) for r in raws)) > 1
        # no fabricated requirement ids in the gate
        assert all(m.get("rid") != "ARCH-GATE" for m in ev.gating.unmet_musts)

def test_scale_gate_matches_dossier_for_all_five():
    from agent.scoring import _enterprise_scale_gate
    expected = {"IFS": False, "Salesforce": False, "ServiceMax": False,
                "ServiceTitan": True, "BuildOps": True}
    for v, exp in expected.items():
        gated, _ = _enterprise_scale_gate(v)
        assert gated is exp, (v, gated)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_decision_rubric -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add FSM_Scoring_Agent/backend/tests/test_decision_rubric.py
git commit -m "test(rubric): replace frozen-number test with property + scale-gate assertions"
```

---

### Task 8: Migration module — re-derive the five evaluations in place

A module that recomputes the decision rollups from a stored result's `requirement_scores`, without re-running the LLM, and writes the results back to the store.

**Files:**
- Create: `FSM_Scoring_Agent/backend/agent/migrate_decision_rubric.py`
- Create: `FSM_Scoring_Agent/scripts/migrate_decision_rubric.py` (thin CLI wrapper)
- Test: `FSM_Scoring_Agent/backend/tests/test_migrate_decision_rubric.py`

**Interfaces:**
- Consumes: `_rollup_capabilities`, `_rollup_categories`, `_compute_gating`, `_enterprise_scale_gate`, `scorecard["decision_knobs"]`, `synthesize_vote`, `store.save`.
- Produces: `rederive_result(result: dict) -> dict` — returns a new result dict with recomputed `categories`, `capabilities`, `gating`, `weighted_total`, `capability_weighted_total`, `vote`, and updated `evaluated_at`; leaves `requirement_scores` untouched. `migrate_store()` reads `store.load_all()`, re-derives each, and `store.save()`s them.

- [ ] **Step 1: Write the failing test (idempotency)**

The verdict test (whether the five land at the committee's outcomes) is deliberately
NOT written here — it is Task 9's calibration target, and it would stay red until the
knobs are tuned. Task 8 only proves the migration mechanics are correct and repeatable.

```python
# test_migrate_decision_rubric.py
import json, os, unittest
from agent.migrate_decision_rubric import rederive_result

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "july2_store_snapshot.json")

class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.results = {v["vendor"]: v for v in json.load(open(FIX))}

    def test_rederive_is_idempotent(self):
        once = rederive_result(self.results["IFS"])
        twice = rederive_result(once)
        self.assertEqual(once["weighted_total"], twice["weighted_total"])
        self.assertEqual([c["id"] for c in once["categories"]],
                         [c["id"] for c in twice["categories"]])

    def test_rederive_preserves_requirement_scores(self):
        once = rederive_result(self.results["IFS"])
        self.assertEqual(len(once["requirement_scores"]), 422)   # evidence untouched
        self.assertEqual(once["requirement_scores"], self.results["IFS"]["requirement_scores"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_migrate_decision_rubric -v`
Expected: FAIL — module does not exist (`ModuleNotFoundError: agent.migrate_decision_rubric`).

- [ ] **Step 3: Implement `rederive_result`**

```python
# agent/migrate_decision_rubric.py
"""Re-derive decision-rubric rollups for an existing evaluation from its stored
per-requirement scores. No LLM calls; deterministic. Used to migrate the five
July-2 evaluations to the corrected engine in place."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, Any

from .schemas import RequirementScore
from .knowledge import get_kb
from . import scoring
from .vote import synthesize_vote


def _to_scores(result: Dict[str, Any]):
    return [RequirementScore(**rs) for rs in result["requirement_scores"]]


def rederive_result(result: Dict[str, Any]) -> Dict[str, Any]:
    kb = get_kb()
    vendor = result["vendor"]
    scores = _to_scores(result)
    req_text = {s.rid: s.requirement for s in scores}

    capabilities = scoring._rollup_capabilities(scores, vendor)
    categories = scoring._rollup_categories(scores, vendor, capabilities)
    gating = scoring._compute_gating(scores, "", req_text)

    raw_total = round(sum(c.weighted_points for c in categories), 1)
    gated, reason = scoring._enterprise_scale_gate(vendor)
    if gated:
        cap = kb.scorecard.get("decision_knobs", {}).get("scale_gate_cap", 60)
        weighted_total = round(min(raw_total, cap), 1)
        gating.architectural_gate_flags.append(reason)
        gating.summary += f" {reason}"
    else:
        weighted_total = raw_total
    cap_total = round(sum(c.weight * (c.score_1_5 / 5.0) * 100 for c in capabilities), 1)

    out = dict(result)
    out["categories"] = [c.to_dict() for c in categories]
    out["capabilities"] = [c.to_dict() for c in capabilities]
    out["gating"] = gating.to_dict()
    out["weighted_total"] = weighted_total
    out["capability_weighted_total"] = cap_total
    out["evaluated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Build a throwaway VendorEvaluation-like object for the vote. Reuse the schema.
    from .schemas import VendorEvaluation
    ev = VendorEvaluation(**{k: out.get(k) for k in (
        "vendor", "product", "model_used", "is_demo", "evaluated_at",
        "weighted_total", "capability_weighted_total")})
    ev.gating = gating
    ev.categories = categories
    ev.capabilities = capabilities
    ev.requirement_scores = scores
    ev.segment_fit = scoring._segment_fit(capabilities)
    out["segment_fit"] = [s.to_dict() for s in ev.segment_fit]
    from .schemas import AgenticFuture  # keep prior agentic_future as-is
    out["vote"] = synthesize_vote(ev, "mock").to_dict()
    return out


def migrate_store() -> int:
    """Re-derive every persisted result and save it back. Returns the count migrated."""
    from .. import store  # backend/store.py
    all_results = store.load_all()
    for vendor, result in all_results.items():
        store.save(rederive_result(result))
    return len(all_results)
```

Note for the implementer: match the exact `VendorEvaluation` / `to_dict` field
names in `schemas.py`; the block above assumes `to_dict()` exists on each schema
(it does per CLAUDE.md). If `vote.py` needs `agentic_future` on `ev`, set
`ev.agentic_future = None` before `synthesize_vote` and keep the original
`out["agentic_future"]` untouched.

- [ ] **Step 4: Add the CLI wrapper**

```python
# scripts/migrate_decision_rubric.py
"""Migrate the on-disk results store to the corrected decision rubric.
Usage: RESULTS_STORE_DIR=/var/data/... python3 scripts/migrate_decision_rubric.py
Backs up the store first, then re-derives every result in place."""
import os, sys, json, shutil, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from agent.migrate_decision_rubric import migrate_store
import store

def main():
    if os.path.isdir(store.STORE_DIR):
        stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = store.STORE_DIR.rstrip("/") + f".backup-{stamp}"
        shutil.copytree(store.STORE_DIR, backup)
        print(f"backed up store -> {backup}")
    n = migrate_store()
    print(f"migrated {n} result(s)")

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the migration-mechanics tests**

Run: `cd FSM_Scoring_Agent/backend && python3 -m unittest tests.test_migrate_decision_rubric -v`
Expected: PASS (idempotency + requirement-scores-preserved).

- [ ] **Step 6: Commit**

```bash
git add FSM_Scoring_Agent/backend/agent/migrate_decision_rubric.py FSM_Scoring_Agent/scripts/migrate_decision_rubric.py FSM_Scoring_Agent/backend/tests/test_migrate_decision_rubric.py
git commit -m "feat(rubric): in-place migration that re-derives evals from stored per-req scores"
```

---

### Task 9: Gate-driven vote + recalibrated bands; regenerate the seed

**Finding that reshaped this task (user-approved Option A):** the evidence-derived decision scores cluster tightly (IFS 62, BuildOps 58, Salesforce 56, ServiceMax 53, ServiceTitan 49) and do NOT separate the intended finalists from the rejects by score alone — ServiceMax (53, finalist) scores below BuildOps (58, reject). The reliable separator is the enterprise-scale gate. So: (1) the scale gate DRIVES the vote to "Reject" (the gate overrides the band, exactly like a disqualification), and (2) the Recommend/Shortlist bands are recalibrated to the new score distribution for the ungated finalists. Do NOT try to push finalists past a fixed 65 bar.

**Files:**
- Modify: `FSM_Scoring_Agent/backend/agent/vote.py` (`derive_recommendation`)
- Modify: `FSM_Scoring_Agent/backend/config/scorecard.json` (`decision_knobs`: add `recommend_min`, `shortlist_min`)
- Modify: `FSM_Scoring_Agent/backend/data/sample_results.json`
- Modify: `FSM_Scoring_Agent/docs/superpowers/specs/2026-07-07-decision-rubric-engine-design.md` (Appendix A)
- Test: `FSM_Scoring_Agent/backend/tests/test_migrate_decision_rubric.py` (verdict test) + `tests/test_decision_rubric.py` (vote-band unit test)

**Interfaces:**
- Produces: `derive_recommendation(ev)` returns "Reject" when `_enterprise_scale_gate(ev.vendor)` is gated (overriding the band); otherwise bands from `decision_knobs.recommend_min`/`shortlist_min`.

- [ ] **Step 1: Add the band knobs to config**

In `scorecard.json` `decision_knobs`, add: `"recommend_min": 60, "shortlist_min": 50`.

- [ ] **Step 2: Write the failing vote-band test**

Add to `test_decision_rubric.py`:

```python
def test_scale_gated_vote_is_reject_regardless_of_score():
    from agent.scoring import evaluate_vendor
    from agent.vote import synthesize_vote
    ev = evaluate_vendor("BuildOps", "", sample_proposal_text("BuildOps"), scoring_model="mock")
    ev.vote = synthesize_vote(ev, "mock")
    assert ev.vote.recommendation == "Reject"           # gate overrides the band
    assert ev.gating.disqualified is False               # Reject, not Disqualified

def test_ungated_vendor_banded_by_decision_score():
    from agent.scoring import evaluate_vendor
    from agent.vote import synthesize_vote
    ev = evaluate_vendor("IFS", "", sample_proposal_text("IFS"), scoring_model="mock")
    ev.vote = synthesize_vote(ev, "mock")
    assert ev.vote.recommendation in ("Recommend", "Shortlist")   # a finalist, not Reject
```

Run: `cd FSM_Scoring_Agent/backend && python3 -m pytest tests/test_decision_rubric.py -q`
Expected: FAIL (gate does not yet drive the vote).

- [ ] **Step 3: Implement the gate-driven vote + config bands in `vote.py`**

Add imports near the top: `from .knowledge import get_kb` and `from .scoring import _enterprise_scale_gate`.

Replace `derive_recommendation` so it reads (keeping the existing confidence logic below unchanged):

```python
def derive_recommendation(ev: VendorEvaluation) -> tuple[str, str, str]:
    """Return (recommendation, band_reason, confidence) from the numbers + gates."""
    if ev.gating and ev.gating.disqualified:
        return ("Disqualified",
                f"{ev.gating.unmet_must_count} unmet 'Must' requirement(s) — disqualifying per RFP Section 8.",
                "High")
    # Enterprise-scale / vendor-viability gate overrides the band: a mid-market
    # vendor is a Reject regardless of its decision score.
    gated, gate_reason = _enterprise_scale_gate(ev.vendor)
    if gated:
        return ("Reject", gate_reason, "High")
    knobs = get_kb().scorecard.get("decision_knobs", {})
    bands = [
        (knobs.get("recommend_min", 78), "Recommend", "Top-tier fit; advance to demos as a front-runner."),
        (knobs.get("shortlist_min", 65), "Shortlist", "Credible contender; advance to demos to close evidence gaps."),
        (0, "Reject", "Below the bar for this portfolio; do not advance without a material change."),
    ]
    score = ev.weighted_total
    for threshold, label, reason in bands:
        if score >= threshold:
            reco, band_reason = label, reason
            break
    cat_conf = [c.confidence for c in ev.categories]
    low_share = cat_conf.count("Low") / max(1, len(cat_conf))
    confidence = "Low" if low_share >= 0.34 else "High" if low_share == 0 else "Medium"
    if ev.gating and ev.gating.architectural_gate_flags:
        confidence = "Low" if confidence == "Medium" else confidence
    return (reco, band_reason, confidence)
```

Delete the module-level `RECO_BANDS` constant if it now has no other referents (grep first; if referenced elsewhere, leave it).

Run: `cd FSM_Scoring_Agent/backend && python3 -m pytest tests/test_decision_rubric.py -q`
Expected: PASS. Watch for a circular import (`vote` importing `scoring`) — run the full suite to confirm imports resolve.

- [ ] **Step 4: Rewrite the verdict test to assert votes, not a 65 headline**

Replace the Task-8 placeholder verdict test in `test_migrate_decision_rubric.py` with:

```python
    def test_rederive_reproduces_committee_verdicts(self):
        got = {v: rederive_result(self.results[v]) for v in self.results}
        self.assertEqual(got["IFS"]["vote"]["recommendation"], "Recommend")
        self.assertEqual(got["Salesforce"]["vote"]["recommendation"], "Shortlist")
        self.assertEqual(got["ServiceMax"]["vote"]["recommendation"], "Shortlist")
        self.assertEqual(got["ServiceTitan"]["vote"]["recommendation"], "Reject")
        self.assertEqual(got["BuildOps"]["vote"]["recommendation"], "Reject")
        # rejects are scale-gated, not Must-disqualified
        self.assertFalse(got["ServiceTitan"]["gating"]["disqualified"])
        self.assertFalse(got["BuildOps"]["gating"]["disqualified"])
        self.assertTrue(any("scale" in f.lower()
                            for f in got["BuildOps"]["gating"]["architectural_gate_flags"]))
        # IFS is the top finalist by decision score
        self.assertEqual(max(got, key=lambda v: got[v]["weighted_total"]), "IFS")
```

- [ ] **Step 5: Run the verdict test; tune band knobs if needed**

Run: `cd FSM_Scoring_Agent/backend && python3 -m pytest tests/test_migrate_decision_rubric.py -q`
With `recommend_min=60, shortlist_min=50` this should pass on the current numbers (IFS 62 → Recommend; Salesforce 56 / ServiceMax 53 → Shortlist; ServiceTitan / BuildOps → Reject via gate). If a finalist's Recommend/Shortlist split reads wrong, adjust `recommend_min`/`shortlist_min` only (do not touch category weights). Re-run until green.

- [ ] **Step 6: Print the final table**

```bash
cd FSM_Scoring_Agent/backend && python3 -c "
import json; from agent.migrate_decision_rubric import rederive_result
res={v['vendor']:v for v in json.load(open('tests/fixtures/july2_store_snapshot.json'))}
for v in ['IFS','Salesforce','ServiceMax','ServiceTitan','BuildOps']:
    r=rederive_result(res[v])
    print(v, r['weighted_total'], r['vote']['recommendation'],
          '| gate:', [f for f in r['gating']['architectural_gate_flags'] if 'scale' in f.lower()][:1])"
```

- [ ] **Step 7: Regenerate the seed from the migrated fixture**

```bash
cd FSM_Scoring_Agent/backend && python3 -c "
import json; from agent.migrate_decision_rubric import rederive_result
res=[rederive_result(v) for v in json.load(open('tests/fixtures/july2_store_snapshot.json'))]
json.dump(res, open('data/sample_results.json','w'), ensure_ascii=False, indent=2)
print('seed rewritten with', len(res), 'vendors')"
```

- [ ] **Step 8: Fill in spec Appendix A**

Paste the final five-vendor table from Step 6 (headline, vote, gate reason) and the final knob values (`enterprise_scale_bar`, `scale_gate_cap`, `recommend_min`, `shortlist_min`) into Appendix A of the design doc.

- [ ] **Step 9: Run the full suite and commit**

Run: `cd FSM_Scoring_Agent/backend && python3 -m pytest tests/ -q` — fully green.

```bash
git add FSM_Scoring_Agent/backend/agent/vote.py FSM_Scoring_Agent/backend/config/scorecard.json FSM_Scoring_Agent/backend/data/sample_results.json FSM_Scoring_Agent/docs/superpowers/specs/2026-07-07-decision-rubric-engine-design.md FSM_Scoring_Agent/backend/tests/test_migrate_decision_rubric.py FSM_Scoring_Agent/backend/tests/test_decision_rubric.py
git commit -m "feat(rubric): scale gate drives Reject vote; recalibrate bands; regenerate seed from real data"
```

---

### Task 10: Rebuild the standalone; update README wording

**Files:**
- Modify: `FSM_Scoring_Agent/FSM_Evaluation_Agent_Standalone.html` (generated)
- Modify: `FSM_Scoring_Agent/README.md` (if it describes the old gate/categories)
- Test: manual (offline demo)

**Interfaces:** none.

- [ ] **Step 1: Rebuild the standalone**

Run: `cd FSM_Scoring_Agent/backend && python3 build_static.py`
Expected: `../FSM_Evaluation_Agent_Standalone.html` rewritten with the new seed and labels.

- [ ] **Step 2: Smoke-test the offline app**

Run: `cd FSM_Scoring_Agent/backend && SEED_DEMO_RESULTS=1 python3 -c "import app; app._seed_results(); print(sorted(app._RESULTS)); print({v:app._RESULTS[v]['vote']['recommendation'] for v in app._RESULTS})"`
Expected: five vendors; ServiceTitan and BuildOps show "Reject", the others show a finalist band.

- [ ] **Step 3: Update README references to the gate/categories if present**

Grep and fix any prose that still says "any unmet Must disqualifies" or lists the six old categories.

Run: `grep -nE "unmet Must|six .*categor|requirement_alignment" FSM_Scoring_Agent/README.md`

- [ ] **Step 4: Update graphify**

Run: `cd FSM_Scoring_Agent && graphify update .`

- [ ] **Step 5: Commit**

```bash
git add FSM_Scoring_Agent/FSM_Evaluation_Agent_Standalone.html FSM_Scoring_Agent/README.md
git commit -m "chore(rubric): rebuild standalone and refresh docs for the general engine"
```

---

## Deployment runbook (manual, after merge — not a plan task)

1. Merge this branch to `main`; close PR #58 (superseded).
2. Deploy the new code via the `/render-deploy` skill (auto-deploy webhook is unreliable).
3. Migrate the prod store on disk (the disk wins over the seed). `render ssh` into the
   service, then `RESULTS_STORE_DIR=/var/data/... python3 scripts/migrate_decision_rubric.py`
   (it backs up the store first).
4. **Restart the service after the migration.** The app loads the store into the
   in-memory `_RESULTS` at boot, so the process started in step 2 is still serving the
   pre-migration results — a disk migration alone will not change what `GET /api/results`
   returns until a restart. Trigger a restart/redeploy (or `render` restart) so the
   migrated store is reloaded. (Order matters: deploy code → migrate disk → restart.)
5. Verify: `GET /api/results` shows IFS/Salesforce/ServiceMax as finalists and
   ServiceTitan/BuildOps as Reject, with the enterprise-scale reason on the gate.

Note: a stale local `backend/data/store/results/*.json` (gitignored dev artifact) will
override the seed in local runs — irrelevant to prod, but clear it if a local smoke test
shows old verdicts.

---

## Self-review

**Spec coverage:**
- Category scoring from evidence (spec 4.1) → Tasks 5, 9.
- Enterprise-scale gate + cap (4.2) → Tasks 3, 6, 9.
- Unmet Musts as discount, not DQ (4.2) → Task 4.
- Config knobs (4.4) → Task 2.
- Calibration (5) → Task 9.
- Migration in place + prod store (6) → Tasks 1, 8, deployment runbook.
- Property tests (7) → Tasks 6, 7, 8.
- Files touched (8) → all tasks; capabilities.json untouched (constraint honored).
- Reject label decision → Tasks 4, 6 (disqualified stays False; band yields Reject).

**Placeholder scan:** No "TBD"/"handle edge cases" — every code step shows code. Appendix A is filled in Task 9 Step 6. The one flagged assumption for the implementer (matching `to_dict`/`VendorEvaluation` field names in `schemas.py`) is a real instruction, not a placeholder.

**Type consistency:** `_enterprise_scale_gate` returns `(bool, str)` in Tasks 3, 6, 8. `rederive_result(dict) -> dict` consistent in Tasks 8, 9. `scale_gate_cap`/`enterprise_scale_bar`/`operating_capability_weights` knob names consistent across Tasks 2, 3, 6, 8, 9.
