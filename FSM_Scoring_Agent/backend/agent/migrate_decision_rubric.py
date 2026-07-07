"""
migrate_decision_rubric.py — re-derive an evaluation's decision rollups from its
stored per-requirement scores, with NO LLM calls.

The five July-2 evaluations were scored under the old (SSA-specific, auto-
disqualifying) decision rubric. Tasks 2-6 generalized the engine's category/
capability rollups, gating, and scale-gate cap without changing how a requirement
itself is scored. This module replays that new deterministic pipeline over each
result's already-scored `requirement_scores` — the expensive, non-reproducible part
(the LLM scoring pass) is left completely alone — and recomputes everything derived
from those scores: categories, capabilities, gating, segment fit, the two headline
totals, and the vote.

`requirement_scores`, `agentic_future`, and `external_research` are carried over
unchanged: the first is the evidence base itself (nothing to re-derive), and the
other two come from the LLM's agentic-future read and the vendor research dossier,
neither of which the decision-rubric fix touches.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from . import scoring
from .knowledge import get_kb
from .schemas import AgenticFuture, RequirementScore, VendorEvaluation
from .vote import synthesize_vote


def _to_scores(result: Dict[str, Any]) -> List[RequirementScore]:
    """Rehydrate the stored requirement-score dicts into RequirementScore objects.
    Field names match schemas.RequirementScore exactly (verified against the
    committed fixture), so this is a straight **kwargs reconstruction."""
    return [RequirementScore(**rs) for rs in result["requirement_scores"]]


def _agentic_future_from(result: Dict[str, Any]) -> AgenticFuture | None:
    """Rebuild the AgenticFuture object the vote needs to reference (e.g. the
    'agentic' category / data-control-risk top-risk check), from the untouched
    stored dict. Returns None if the result never had one (defensive; every real
    evaluation has one)."""
    raw = result.get("agentic_future")
    return AgenticFuture(**raw) if raw else None


def rederive_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recompute categories, capabilities, gating, segment_fit, weighted_total,
    capability_weighted_total, and vote from `result["requirement_scores"]`,
    using the current (general) engine — no LLM calls. Returns a NEW result dict;
    `result` is not mutated. `requirement_scores`, `agentic_future`, and
    `external_research` are carried over byte-for-byte unchanged.
    """
    kb = get_kb()
    vendor = result["vendor"]
    scores = _to_scores(result)

    # Requirement text (for gating's unmet-Must detail) comes from the current
    # requirements.json, keyed the same way evaluate_vendor builds it — NOT from
    # RequirementScore, which has no "requirement" text field.
    req_text = {r["rid"]: r.get("requirement", "") for r in kb.requirement_list()}

    capabilities = scoring._rollup_capabilities(scores, vendor)
    categories = scoring._rollup_categories(scores, vendor, capabilities)
    # No original proposal text is stored on a result, so the architectural-flag
    # scan runs on "" (same behavior evaluate_vendor gets for a proposal that
    # never mentions multi-tenant/union/CBA terms at all).
    gating = scoring._compute_gating(scores, "", req_text)
    segment_fit = scoring._segment_fit(capabilities)

    raw_total = round(sum(c.weighted_points for c in categories), 1)
    scale_gated, scale_reason = scoring._enterprise_scale_gate(vendor)
    if scale_gated:
        cap = kb.scorecard.get("decision_knobs", {}).get("scale_gate_cap", 60)
        weighted_total = round(min(raw_total, cap), 1)
        gating.architectural_gate_flags.append(scale_reason)
        gating.summary += f" {scale_reason}"
    else:
        weighted_total = raw_total
    capability_weighted_total = round(
        sum(c.weight * (c.score_1_5 / 5.0) * 100 for c in capabilities), 1
    )

    evaluated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Build a real VendorEvaluation so vote.synthesize_vote sees the same shape it
    # would from evaluate_vendor. agentic_future is rebuilt (not stored back) so the
    # vote's narrative/top-risks logic — which reads ev.agentic_future — behaves
    # exactly as it would on a fresh evaluation.
    ev = VendorEvaluation(
        vendor=vendor,
        product=result.get("product", ""),
        model_used=result.get("model_used", "mock"),
        is_demo=result.get("is_demo", True),
        evaluated_at=evaluated_at,
        weighted_total=weighted_total,
        capability_weighted_total=capability_weighted_total,
        gating=gating,
        categories=categories,
        capabilities=capabilities,
        segment_fit=segment_fit,
        agentic_future=_agentic_future_from(result),
        vote=None,
        external_research=result.get("external_research", {}),
        requirement_scores=scores,
        scoring_live_count=result.get("scoring_live_count", 0),
        scoring_fallback_count=result.get("scoring_fallback_count", 0),
        engine_warning=result.get("engine_warning", ""),
    )
    ev.vote = synthesize_vote(ev, "mock")

    out = dict(result)  # start from the original; requirement_scores/agentic_future/
                        # external_research fall through untouched below.
    out["categories"] = [c.to_dict() for c in categories]
    out["capabilities"] = [c.to_dict() for c in capabilities]
    out["gating"] = gating.to_dict()
    out["segment_fit"] = [s.to_dict() for s in segment_fit]
    out["weighted_total"] = weighted_total
    out["capability_weighted_total"] = capability_weighted_total
    out["evaluated_at"] = evaluated_at
    out["vote"] = ev.vote.to_dict()
    return out
