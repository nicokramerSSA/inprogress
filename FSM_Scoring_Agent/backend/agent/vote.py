"""
vote.py — synthesize the agent's final, independent VOTE for one vendor.

The vote is deliberately separate from the arithmetic. The scoring engine produces
auditable numbers (weighted total, capability scores, gating, segment fit, agentic
future). This module turns those numbers into a senior-partner judgment:

  * recommendation : Recommend / Shortlist / Reject / Disqualified
  * narrative      : the "lead with the verdict, then the why" rationale, in the panel's reconciled voice
  * dissent        : the strongest honest counter-argument to that recommendation
  * top_risks      : the few risks that actually matter
  * evidence_to_close : what must be proven in the July 13-16 Charlotte demos / references

A clear, deterministic RUBRIC maps score + gating to a recommendation band, so the
vote is reproducible and explainable even before any LLM polish. When a real model is
selected, it writes the narrative/dissent in-voice; the mock engine composes them from
the structured findings so the app is fully functional offline.
"""
from __future__ import annotations

import concurrent.futures as _f
import json
from typing import List

from .knowledge import get_kb
from .providers import client, is_mock, extract_json
from .schemas import VendorEvaluation, Vote


# --------------------------------------------------------------------------- #
# Recommendation rubric (deterministic, auditable)                            #
# --------------------------------------------------------------------------- #
# Bands are expressed on the 0-100 weighted SSA-category total. A disqualifying
# gate overrides the band entirely — that is the whole point of a gate.
RECO_BANDS = [
    (78, "Recommend", "Top-tier fit; advance to demos as a front-runner."),
    (65, "Shortlist", "Credible contender; advance to demos to close evidence gaps."),
    (0,  "Reject", "Below the bar for this portfolio; do not advance without a material change."),
]


def _customization_risk(scores):
    """Deterministic risk when Musts are met only via custom development.
    Returns (count_of_CUSTOM_Musts, message) or (0, None) when none."""
    n = sum(1 for s in scores if s.priority == "Must" and s.vendor_code == "CUSTOM")
    if n == 0:
        return 0, None
    return n, (f"Heavy customization: {n} Must requirement(s) met only via custom "
               f"development — costly to maintain and evolve.")


def derive_recommendation(ev: VendorEvaluation) -> tuple[str, str, str]:
    """Return (recommendation, band_reason, confidence) from the numbers + gates."""
    if ev.gating and ev.gating.disqualified:
        return ("Disqualified",
                f"{ev.gating.unmet_must_count} unmet 'Must' requirement(s) — disqualifying per RFP Section 8.",
                "High")
    score = ev.weighted_total
    for threshold, label, reason in RECO_BANDS:
        if score >= threshold:
            reco, band_reason = label, reason
            break
    # Confidence on the vote = the modal confidence across categories, discounted if
    # there are many architectural flags or the score is near a band boundary.
    cat_conf = [c.confidence for c in ev.categories]
    low_share = cat_conf.count("Low") / max(1, len(cat_conf))
    confidence = "Low" if low_share >= 0.34 else "High" if low_share == 0 else "Medium"
    if ev.gating and ev.gating.architectural_gate_flags:
        confidence = "Low" if confidence == "Medium" else confidence
    return (reco, band_reason, confidence)


def _structured_findings(ev: VendorEvaluation) -> dict:
    """Compact, model-friendly digest of the numbers behind the vote."""
    caps_sorted = sorted(ev.capabilities, key=lambda c: c.score_1_5)
    seg_sorted = sorted(ev.segment_fit, key=lambda s: s.fit_1_5)
    return {
        "weighted_total_100": ev.weighted_total,
        "capability_total_100": ev.capability_weighted_total,
        "gating": ev.gating.summary if ev.gating else "",
        "unmet_musts": (ev.gating.unmet_musts[:8] if ev.gating else []),
        "weakest_capabilities": [f"{c.code} {c.score_1_5}/5 (w{int(c.weight*100)}%)" for c in caps_sorted[:3]],
        "strongest_capabilities": [f"{c.code} {c.score_1_5}/5" for c in caps_sorted[-3:]],
        "weakest_segments": [f"{s.segment_name} {s.fit_1_5}/5" for s in seg_sorted[:2]],
        "strongest_segments": [f"{s.segment_name} {s.fit_1_5}/5" for s in seg_sorted[-2:]],
        "agentic_future": (f"{ev.agentic_future.score_1_5}/5, data-control risk "
                           f"{ev.agentic_future.data_control_risk}") if ev.agentic_future else "",
        "architectural_flags": (ev.gating.architectural_gate_flags if ev.gating else []),
        "category_breakdown": [f"{c.name}: {c.raw_1_5}/5 → {c.weighted_points} pts" for c in ev.categories],
    }


def synthesize_vote(ev: VendorEvaluation, model_id: str = "mock") -> Vote:
    """Produce the agent's vote. Mutates nothing; returns a Vote object."""
    reco, band_reason, confidence = derive_recommendation(ev)
    findings = _structured_findings(ev)

    # Evidence to close = the distinct, non-empty evidence gaps surfaced by categories,
    # plus any architectural flags. These are the things to verify in Charlotte.
    evidence: List[str] = []
    for c in ev.categories:
        evidence += c.evidence_gaps
    if ev.gating:
        evidence += ev.gating.architectural_gate_flags
    evidence = list(dict.fromkeys([e for e in evidence if e]))[:6]

    # Top risks = weakest high-weight capabilities + data-control risk + worst segment,
    # plus a deterministic customization risk (Musts met only via custom development).
    cust_n, cust_msg = _customization_risk(ev.requirement_scores)
    risks: List[str] = []
    if ev.gating and ev.gating.disqualified:
        risks.append(f"Disqualifying: {ev.gating.unmet_must_count} unmet Must requirement(s).")
    if cust_msg and cust_n >= 3:
        risks.append(cust_msg)   # material reliance on custom work -> ranked high
    for c in sorted(ev.capabilities, key=lambda c: c.score_1_5)[:2]:
        if c.score_1_5 < 3.5:
            risks.append(f"{c.name} weak at {c.score_1_5}/5 (weight {int(c.weight*100)}%).")
    if ev.agentic_future and ev.agentic_future.data_control_risk == "High":
        risks.append("High data-control risk — the OpCos may not control their own AI destiny.")
    worst_seg = min(ev.segment_fit, key=lambda s: s.fit_1_5, default=None)
    if worst_seg and worst_seg.fit_1_5 < 3.0:
        risks.append(f"Poor fit for {worst_seg.segment_name} ({worst_seg.fit_1_5}/5).")
    if cust_msg and cust_n < 3:
        risks.append(cust_msg)   # some custom work -> lower priority
    risks = risks[:5] or ["No dominant risk; close the evidence gaps in the demo."]

    if is_mock(model_id):
        narrative, dissent = _mock_narrative(ev, reco, band_reason, findings)
    else:
        narrative, dissent = _llm_narrative(ev, reco, band_reason, findings, model_id)

    return Vote(
        recommendation=reco, confidence=confidence, narrative=narrative,
        dissent=dissent, top_risks=risks, evidence_to_close=evidence,
    )


# --------------------------------------------------------------------------- #
# Narrative writers                                                           #
# --------------------------------------------------------------------------- #
def _mock_narrative(ev, reco, band_reason, findings) -> tuple[str, str]:
    """Compose a verdict-first narrative from the structured findings (offline)."""
    strong = ", ".join(findings["strongest_capabilities"])
    weak = ", ".join(findings["weakest_capabilities"])
    seg_hi = ", ".join(findings["strongest_segments"])
    seg_lo = ", ".join(findings["weakest_segments"])
    narrative = (
        f"[demo vote] {reco}. {band_reason} {ev.vendor} lands at {ev.weighted_total}/100 on the "
        f"SSA category weighting ({ev.capability_weighted_total}/100 on the capability lens). "
        f"{ev.gating.summary if ev.gating else ''} "
        f"Strongest where it counts: {strong}. Weakest: {weak}. "
        f"Best-fit OpCo archetypes: {seg_hi}; thinnest for {seg_lo}. "
        f"On the agentic future, {findings['agentic_future']} — and remember, openness beats any "
        f"single AI feature, because what we build on top is transient. "
        f"Net: I'd {reco.lower()} this one, and prove the rest in Charlotte."
    )
    dissent = (
        "Counter-argument: requirement-level scoring rewards breadth of claims; a vendor that is "
        "narrower but deeper on Work-to-Cash and offline mobile could deliver more real value than "
        "this composite suggests. The demo and references should test depth, not just coverage."
    )
    return narrative, dissent


def _provider_narrative(ev, reco, band_reason, findings, model_id) -> dict:
    """Generate one provider's narrative+dissent for the vote. Returns a dict so the
    dual path can carry per-provider results; the single path unwraps it."""
    kb = get_kb()
    system = kb.persona_system_prompt()
    user = (
        f"You are casting your independent VOTE on vendor {ev.vendor} ({ev.product}) for the "
        f"Service Logic FSM selection. The deterministic rubric says: {reco} ({band_reason}).\n\n"
        f"STRUCTURED FINDINGS:\n{json.dumps(findings, indent=2)}\n\n"
        f"Write your vote. Lead with the verdict, then the why. Tie weaknesses to dollars/outcomes "
        f"where you can (billing lag, revenue leakage, DSO, adoption). Name what must be proven in the "
        f"July 13-16 Charlotte demos. Then write the single strongest honest DISSENT against your own "
        f"recommendation.\n\n"
        f"Return ONLY JSON: {{\"narrative\": \"...\", \"dissent\": \"...\"}}"
    )
    # generous cap (plan said 1500): adaptive thinking on opus-4-8 spends budget before the JSON; cap is billed only for tokens actually generated (model hard-cap 8192), so headroom is free insurance against truncation.
    resp = client.generate(system, user, model_id, expect_json=True, max_tokens=4000, temperature=0.3)
    out = {"provider": resp.get("provider", ""), "model": model_id,
           "narrative": band_reason, "dissent": "", "ok": bool(resp.get("ok"))}
    if resp.get("ok"):
        try:
            d = extract_json(resp["text"])
            out["narrative"] = str(d.get("narrative", "")).strip() or band_reason
            out["dissent"] = str(d.get("dissent", "")).strip()
        except Exception:
            # API responded but the body was unparseable (rare truncation). Flag it so the
            # caller can report honestly rather than claiming "no live response".
            out["ok"] = False
            out["parse_error"] = True
    return out


def _llm_narrative(ev, reco, band_reason, findings, model_id) -> tuple[str, str]:
    """Single-model path (unchanged behavior): returns (narrative, dissent)."""
    r = _provider_narrative(ev, reco, band_reason, findings, model_id)
    return (r["narrative"], r["dissent"])


def _reconcile(ev, reco, band_reason, findings, raw_votes, synthesizer_model) -> dict:
    """Anthropic reconciliation of the two provider votes. Returns
    {"narrative","dissent","disagreements":[...]} ; falls back to the Anthropic raw vote."""
    kb = get_kb()
    system = kb.persona_system_prompt()
    user = (
        f"Two AI analysts independently voted on vendor {ev.vendor} ({ev.product}). The deterministic "
        f"rubric says {reco} ({band_reason}). Reconcile their votes into ONE final vote in the panel's reconciled "
        f"voice, and surface where they materially disagreed.\n\n"
        f"DETERMINISTIC FINDINGS:\n{json.dumps(findings, indent=2)}\n\n"
        f"ANALYST VOTES:\n{json.dumps(raw_votes, indent=2)}\n\n"
        f"Return ONLY JSON: {{\"narrative\":\"...\",\"dissent\":\"...\",\"disagreements\":"
        f"[{{\"dimension\":\"...\",\"openai_position\":\"...\",\"anthropic_position\":\"...\",\"resolution\":\"...\"}}]}}"
    )
    # generous cap (plan said 2000): adaptive thinking on opus-4-8 spends budget before the JSON; cap is billed only for tokens actually generated (model hard-cap 8192), so headroom is free insurance against truncation.
    resp = client.generate(system, user, synthesizer_model, expect_json=True, max_tokens=4000, temperature=0.3)
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
            elif r.get("parse_error"):
                # The model DID respond; we just couldn't parse its body. Say so honestly
                # rather than implying the key/network was the problem.
                notes.append(f"{label} model responded but its output could not be parsed; excluded from the vote")
            else:
                notes.append(f"{label} vote unavailable (missing key or API error)")

    # Stable UI order: the two known providers, openai before anthropic.
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
