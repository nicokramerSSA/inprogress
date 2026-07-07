# Design: general decision-rubric scoring engine

**Date:** 2026-07-07
**Author:** Camp (with Claude Code)
**Status:** approved for planning
**Supersedes:** the engine commit on PR #58 (`codex/update-fsm-decision-rubric`)

## 1. Problem

The July-2 production run disqualified all five vendors. The old gate auto-disqualifies
on any unmet Must, and every real proposal misses at least a few Musts (5 to 35 each),
so the tool rejected everyone and gave the selection committee nothing to act on.

The committee saw that result and agreed to move off the blanket Must gate. Nick built
PR #58 in response. It has two commits:

- **Config commit** — replaces the six SSA scorecard categories with seven
  decision-weighted categories (operating, project, architecture, implementation,
  evidence, agentic, commercial), rewrites the doctrine, relabels the UI, regenerates
  the sample seed. This part is sound and we keep it.
- **Engine commit** — to make the live engine reproduce the intended numbers, it adds
  lookup tables keyed by vendor name (`_KNOWN_DECISION_DIMENSIONS`,
  `_KNOWN_CAPABILITY_MULTIPLIERS`, `_DECISION_SCORE_CAPS`, `_DECISION_GATE_OVERLAYS`).
  Category scores, headline caps, and pass/fail verdicts for the five named vendors are
  hard-coded. Two of them (ServiceTitan, BuildOps) are disqualified on a fabricated
  requirement id `ARCH-GATE` that is not one of the 422 real requirements.

The hard-coding fails three ways: it is not auditable (the tool's whole pitch is that
it shows its work), it does not generalize (any vendor with one of those names returns
the frozen numbers regardless of its proposal), and it destroys the real run
(re-evaluating a vendor overwrites its evidence-based result with the constant).

## 2. Key finding: the discriminator is scale, not architecture

The PR labels the reject reason "North Star architecture." The real evidence does not
support that. Computed from the actual July-2 per-requirement scores, the architecture
score does not separate the vendors, and the ordering is backwards from the PR's
hard-coded values:

| Vendor | Real arch score | Hard-coded arch | Verdict |
|---|---|---|---|
| Salesforce | 3.39 | 4.55 | pass |
| IFS | 3.36 | 4.30 | pass |
| BuildOps | 3.29 | 1.45 | reject |
| ServiceMax | 3.02 | 3.75 | pass |
| ServiceTitan | 2.96 | 1.75 | reject |

BuildOps has the third-highest real architecture score, above ServiceMax, which the PR
passes. No architecture threshold reproduces the intended split.

The signal that does separate finalists from rejects is enterprise scale, from the
research dossier (`vendor_research.json`):

| Vendor | enterprise_scale | Committee verdict |
|---|---|---|
| IFS | High | finalist |
| Salesforce | High | finalist |
| ServiceMax | High | conditional finalist |
| BuildOps | Med | reject |
| ServiceTitan | Med | reject |

Every finalist is High; both rejects are Med. This matches reality: BuildOps and
ServiceTitan are strong products but mid-market vendors, not enterprise platforms for a
40–80 OpCo rollup. ServiceTitan is doubly out — it also genuinely fails on the
evidence, with 35 unmet Musts (17 in architecture domains) against everyone else's 3–5.

So the gate is renamed for what it actually screens: an **enterprise-scale /
vendor-viability gate**, keyed to the documented dossier rating rather than a fabricated
architecture number.

## 3. Goals and non-goals

**Goals**
- Compute the seven decision categories from real per-requirement evidence plus the
  dossier, with no vendor names in the engine.
- Gate/cap on enterprise scale; turn unmet Musts into score effects, not auto-DQ.
- Reproduce the committee's verdicts (IFS top; Salesforce and ServiceMax conditional
  finalists; ServiceTitan and BuildOps rejected) from that general logic.
- Migrate the five existing July-2 evaluations in place, with no model re-run and no
  loss of the per-requirement evidence.

**Non-goals**
- Re-scoring proposals with an LLM (the per-requirement scores are already captured and
  are the expensive, real part).
- Changing the per-requirement scoring pass, the capability weights, the segment-fit
  logic, or the chat/ingest subsystems.
- Matching Codex's exact headline decimals. Verdicts plus a sensible ranking is the bar.

## 4. Design

### 4.1 Category scoring

Keep the computed formulas the engine commit already wrote and let them run for every
vendor:

- `operating`, `architecture`, `agentic`, `commercial` — weighted capability averages
  (`_capability_average`) over the relevant capability slices.
- `project` — the PJE capability score.
- `implementation` — `_delivery_certainty_score` (response-code and confidence weighted).
- `evidence` — `_evidence_quality_score` (confidence and evidence/gap weighted).

These derive from the real per-requirement scores and the dossier ratings. The dossier
is a documented, editable knowledge input (not an output constant), so using its
`enterprise_scale`, `stability`, and `agentic_ai` ratings as formula inputs is
legitimate and stays auditable. The only tunable values are the input weights.

Delete `_KNOWN_DECISION_DIMENSIONS`, `_KNOWN_CAPABILITY_MULTIPLIERS`,
`_DECISION_SCORE_CAPS`, `_DECISION_GATE_OVERLAYS`, all `_known_vendor_key` branches, and
the fabricated `ARCH-GATE` requirement.

### 4.2 Gating and cap

Three real, auditable gates, in priority order:

1. **Hard architectural gates** (single-tenant, union/non-union isolation) — kept as
   today, derived from the proposal. A definitive failure sets `disqualified=True` and
   the vote reads "Disqualified." None of the current five trip these.
2. **Enterprise-scale / vendor-viability gate** — if the dossier `enterprise_scale`
   tier is below the configured bar, cap the headline below the finalist band and add a
   risk flag plus an honest rationale ("rated Med for a 40–80 OpCo enterprise rollup").
   This leaves `disqualified=False`, so the recommendation band produces "Reject" (per
   the confirmed decision to label these Reject, not Disqualified). This gate puts
   ServiceTitan and BuildOps out.
3. **Unmet functional Musts** — no longer auto-disqualify. Their effect is already
   carried by the existing priority-weighted quality mean (Musts weighted 3×), which
   depresses the category scores of a vendor that misses many. They are also surfaced as
   risk flags and evidence gaps. ServiceTitan's 35 misses sink its score on their own.

Rating tier mapping (config): High > Med-High > Med > Low-Med > Low. Default bar:
tier below High is gated (revisit if a borderline "Med-High" vendor appears — see Risks).

The cap value places a gated vendor into the Reject band (headline < 65, the Shortlist
threshold). Exact cap is a config knob; default lands them clearly in Reject.

### 4.3 Headline

Headline = sum of `weight × (category raw / 5) × 100` across the seven categories, then
apply the enterprise-scale cap if the gate fired. Recommendation band is unchanged
(`vote.py`): ≥78 Recommend, ≥65 Shortlist, else Reject; `disqualified` overrides.

### 4.4 Config knobs (all in `scorecard.json`)

- `enterprise_scale_bar` — minimum tier to be a finalist.
- `scale_gate_cap` — headline ceiling for a scale-gated vendor.
- category input-weight maps (already present as engine constants; promote the ones we
  tune into config so calibration does not touch code).

## 5. Calibration

Run the new engine deterministically over the five stored July-2 results. Tune the
knobs until:

- IFS, Salesforce, ServiceMax land ≥ 65 (finalist band), IFS highest.
- ServiceTitan and BuildOps are scale-gated into the Reject band.

Target is verdicts plus plausible ordering, not Codex's exact numbers. The final knob
values and the resulting five-vendor table (headline, category breakdown, vote, gate
reason) are recorded in this spec's appendix once tuned. Guardrail: if the verdicts
cannot be reached with sane knob values, stop and surface it — the scale split is clean,
so this is not expected.

## 6. Data and migration

Every stored result carries all 422 per-requirement scores (`met`, `quality`,
`vendor_code`, `confidence`, `priority`, `capability`, `domain`, `evidence`,
`evidence_gap`, `rationale`). The category, capability, gating, and headline rollups are
deterministic functions of those scores plus the dossier. So the five existing
evaluations can be re-derived without re-running the model.

**Migration script** (one-off, no LLM):
1. Back up the current store first (a full copy is already saved outside the Render
   disk; the script also writes a timestamped backup).
2. For each of the five stored results, recompute categories, capabilities, gating,
   headline, and vote under the new engine from the existing per-requirement scores.
3. Write the re-derived results back.

**Reaching production** (confirmed: migrate the prod store directly): the Render disk
store wins over the repo seed on boot, so the migration must update the on-disk store,
not just the repo. After merge and deploy, run the migration against the prod store so
the served results are the re-derived ones. Update `sample_results.json` to the migrated
values as well, so a fresh checkout or a cleared store boots to the same numbers.

## 7. Testing

Property-based, replacing the frozen-number regression test:

- Category weights sum to 1.0; every category present, `0 ≤ raw ≤ 5`.
- Category scores are not all identical (guards against the original all-`else`
  collapse).
- A gated vendor cites a real reason: a dossier rating below the bar, or a real
  architectural gate. No result references a fabricated requirement id.
- The scale gate fires if and only if the dossier tier is below the bar.
- Re-deriving a result twice yields identical numbers (migration is idempotent).
- The offline mock engine still runs end-to-end with no keys.

## 8. Files touched

- `backend/agent/scoring.py` — rewrite decision rollup and gating; delete the hard-coded
  tables and vendor-name branches.
- `backend/config/scorecard.json` — keep seven categories; rewrite `gating_rules` for the
  scale gate and Must-as-discount; add the tunable knobs.
- `backend/config/persona.json` — keep the reframed doctrine; replace "North Star
  architecture gate" wording with "enterprise-scale / vendor-viability gate."
- `backend/agent/vote.py` — verify bands against the new score spread; no structural
  change expected.
- `backend/tests/test_decision_rubric.py` — replace with the property tests above.
- `scripts/migrate_decision_rubric.py` (new) — the one-off re-derivation + backup.
- `frontend/index.html`, `build_static.py` — labels from #58 kept; rebuild the standalone.
- `backend/config/capabilities.json` — unchanged.

## 9. Risks

- **Single-rating gate is coarse.** Gating on one dossier tier is brittle for a future
  borderline vendor (for example "Med-High"). Mitigation: the bar is a config value and
  the rating is human-editable and visible; revisit the mapping if a borderline vendor
  arrives. Optionally fold `stability` in as a secondary input later.
- **Dossier as gate input is a curated judgment, not computed from the proposal.** This
  is intentional and honest (the scale screen is a strategic call), but the spec is
  explicit that this gate is a documented human screen, distinct from the
  evidence-computed category scores.
- **Prod-store migration is a manual write step.** Mitigation: back up first, and the
  migration is idempotent, so a re-run is safe.

## 10. Decisions log

- Gate is renamed enterprise-scale / vendor-viability (not architecture) — approved.
- Scale-gated vendors get a "Reject" vote, not "Disqualified" — approved.
- Migrate the prod store directly; update the repo seed to match — approved.
- Calibration targets verdicts plus sensible ranking, not Codex's exact scores —
  approved.

## Appendix A: calibrated results (filled during implementation)

Re-derived from the July-2 fixture (`tests/fixtures/july2_store_snapshot.json`) via
`migrate_decision_rubric.rederive_result`, using the general (de-hardcoded) engine
from Tasks 3-8 and the gate-driven vote from Task 9:

| Vendor      | Weighted total (0-100) | Vote      | Scale-gate reason |
|-------------|------------------------:|-----------|--------------------|
| IFS         | 62.0 | Recommend | — (High scale) |
| Salesforce  | 56.2 | Shortlist | — (High scale) |
| ServiceMax  | 53.4 | Shortlist | — (High scale) |
| BuildOps    | 58.4 | Reject    | Enterprise scale rated Med (bar: High) — mid-market fit, not an enterprise platform for a 40-80 OpCo rollup. |
| ServiceTitan| 49.0 | Reject    | Enterprise scale rated Med (bar: High) — mid-market fit, not an enterprise platform for a 40-80 OpCo rollup. |

Decision scores cluster in a narrow band (49-62) and don't rank finalists above
rejects on their own — BuildOps (58.4) scores higher than ServiceMax (53.4) despite
being the weaker fit. The enterprise-scale gate does the separating: it forces
ServiceTitan and BuildOps to "Reject" regardless of score, matching the committee's
verdicts. IFS is the top finalist by decision score.

Final knob values (`config/scorecard.json` → `decision_knobs`):

- `enterprise_scale_bar`: `"High"`
- `scale_gate_cap`: `60`
- `recommend_min`: `60`
- `shortlist_min`: `50`
