"""
scoring.py — the scoring engine.

This is the heart of the agent. Given a vendor's proposal text, it:

  1. Scores every RFP requirement (Met? + Quality 1-5 + response code + confidence
     + rationale + evidence gap) — in the persona's voice, grounded in the RFP rules.
     Requirements are scored in BATCHES to keep token use and latency manageable.
  2. Rolls requirement scores up into the six SSA scorecard CATEGORIES (weighted).
  3. Rolls them up into the eight RFP business CAPABILITIES (the Section-30 lens).
  4. Applies MoSCoW + architectural GATING (any unmet 'Must' disqualifies).
  5. Computes OpCo-SEGMENT FIT for each archetype, using each segment's capability
     emphasis multipliers.
  6. Produces an AGENTIC-FUTURE assessment (openness/data-control weighted over
     shipped AI features), augmented with the external-research dossier.

Every LLM call routes through providers.client.generate(..., model_id=...), so the
caller chooses the model PER INTERACTION. When model_id == 'mock', a deterministic,
knowledge-base-grounded engine produces structured, persona-flavored output so the
whole pipeline runs with no API keys (clearly labeled as a demo).

Design choices worth noting
---------------------------
* The 1-5 category score is the MEAN requirement quality for that category's
  requirements, but 'Must' requirements are weighted 3x and 'Should' 2x ('Could' 1x)
  so the score reflects what actually matters — Nick's "weight by decision leverage".
* Confidence is rolled up by majority/worst-case: a category with many Low-confidence
  items inherits Low confidence and surfaces the evidence gaps to close in the demo.
* Gating is computed from the requirement scores directly (not the LLM's opinion), so
  the disqualification rule is deterministic and auditable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Callable

from .knowledge import get_kb
from .providers import client, is_mock, extract_json
from .ingest import build_retrieval_index, relevant_passages
from .schemas import (
    RequirementScore, CategoryScore, CapabilityScore, SegmentFit,
    GatingResult, AgenticFuture, VendorEvaluation,
)

class EvaluationCancelled(Exception):
    """Raised when a running evaluation is cancelled via the job API."""


# Map each SSA scorecard category to the domains that feed it.
# Requirement Alignment spans everything; the others draw on focused slices.
_CATEGORY_DOMAIN_HINTS = {
    "architecture": ["Domain H", "Domain I", "NFR", "Domain K"],
    "requirement_alignment": [],  # all functional domains
}

# Priority leverage weights — Musts dominate the rollup (decision-leverage doctrine).
_PRIORITY_WEIGHT = {"Must": 3.0, "Should": 2.0, "Could": 1.0, "Won't": 0.0}

# Response codes that cannot satisfy a Must without a firm SOW (gating doctrine).
_WEAK_CODES_FOR_MUST = {"ROADMAP", "GAP"}


# --------------------------------------------------------------------------- #
# Public entry point                                                          #
# --------------------------------------------------------------------------- #
def evaluate_vendor(
    vendor: str,
    product: str,
    proposal_text: str,
    scoring_model: str = "mock",
    progress: Optional[Callable[[str, float], None]] = None,
    requirement_sample: Optional[int] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> VendorEvaluation:
    """
    Run the full evaluation pipeline for one vendor and return a VendorEvaluation.

    Parameters
    ----------
    vendor, product     : identifying strings.
    proposal_text       : extracted text of the vendor's proposal (see ingest.py).
    scoring_model       : model id for the per-requirement scoring pass (any id from
                          models.json; 'mock' runs the offline engine).
    progress            : optional callback(message, fraction 0..1) for UI streaming.
    requirement_sample  : if set, only score the first N requirements (useful for a
                          fast smoke test / preliminary read before full proposals).
    """
    kb = get_kb()
    reqs = kb.requirement_list()
    if requirement_sample:
        reqs = reqs[:requirement_sample]

    def _emit(msg: str, frac: float):
        if progress:
            progress(msg, frac)

    _emit(f"Scoring {len(reqs)} requirements for {vendor}…", 0.05)

    # 1) Per-requirement scoring (batched) -----------------------------------
    req_scores = _score_requirements(vendor, product, proposal_text, reqs, scoring_model, _emit, should_cancel)

    # 2) Gating (deterministic, from the scores) -----------------------------
    gating = _compute_gating(req_scores, proposal_text)
    _emit("Applying MoSCoW + architectural gates…", 0.72)

    # 3) Category rollup ------------------------------------------------------
    categories = _rollup_categories(req_scores)
    _emit("Rolling up SSA scorecard categories…", 0.80)

    # 4) Capability rollup ----------------------------------------------------
    capabilities = _rollup_capabilities(req_scores)

    # 5) OpCo-segment fit -----------------------------------------------------
    segment_fit = _segment_fit(capabilities)
    _emit("Assessing OpCo-segment fit…", 0.88)

    # 6) Agentic-future assessment (LLM or mock, + dossier) ------------------
    agentic = _agentic_future(vendor, product, proposal_text, scoring_model)
    _emit("Assessing fit into an agentic future…", 0.94)

    # Headline weighted totals (0-100) ---------------------------------------
    weighted_total = round(sum(c.weighted_points for c in categories), 1)
    cap_total = round(
        sum(c.weight * (c.score_1_5 / 5.0) * 100 for c in capabilities), 1
    )

    research = kb.vendor_profile(vendor)

    return VendorEvaluation(
        vendor=vendor,
        product=product or research.get("product", ""),
        model_used=scoring_model,
        is_demo=is_mock(scoring_model),
        evaluated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        weighted_total=weighted_total,
        capability_weighted_total=cap_total,
        gating=gating,
        categories=categories,
        capabilities=capabilities,
        segment_fit=segment_fit,
        agentic_future=agentic,
        vote=None,  # filled by vote.py after this returns
        external_research=research,
        requirement_scores=req_scores,
    )


# --------------------------------------------------------------------------- #
# 1) Per-requirement scoring                                                  #
# --------------------------------------------------------------------------- #
def _score_requirements(vendor, product, proposal_text, reqs, model_id, emit, should_cancel=None) -> List[RequirementScore]:
    strengths = _vendor_cap_strength(vendor)
    proposal_low = (proposal_text or "").lower()
    if is_mock(model_id):
        return [_mock_score_requirement(r, proposal_text, strengths, proposal_low) for r in reqs]

    kb = get_kb()
    system = kb.persona_system_prompt() + "\n\n" + kb.scoring_context()
    out: List[RequirementScore] = []
    BATCH = 12
    total = len(reqs)
    retrieval_index = build_retrieval_index(proposal_text)
    for i in range(0, total, BATCH):
        if should_cancel and should_cancel():
            raise EvaluationCancelled()
        batch = reqs[i:i + BATCH]
        # Localize the vendor's most relevant passages for this batch's terms.
        kws = _batch_keywords(batch)
        context = relevant_passages(proposal_text, kws, max_chunks=8, index=retrieval_index)

        user = _batch_prompt(vendor, product, batch, context)
        resp = client.generate(system, user, model_id, expect_json=True,
                               max_tokens=8192, temperature=0.15)
        if resp["ok"]:
            try:
                parsed = extract_json(resp["text"])
                rows = parsed if isinstance(parsed, list) else parsed.get("scores", [])
                by_rid = {row.get("rid"): row for row in rows}
            except Exception:
                by_rid = {}
        else:
            by_rid = {}

        for r in batch:
            row = by_rid.get(r["rid"])
            if row:
                out.append(_row_to_score(r, row))
            else:
                # Fall back to the deterministic engine for any row the model skipped,
                # so the rollups never have holes (fail soft).
                out.append(_mock_score_requirement(r, proposal_text, strengths, proposal_low))

        emit(f"Scored {min(i + BATCH, total)}/{total} requirements…",
             0.05 + 0.62 * (min(i + BATCH, total) / total))
    return out


def _batch_keywords(batch: List[Dict[str, Any]]) -> List[str]:
    """Return de-duplicated, high-signal requirement terms for retrieval."""
    seen = set()
    kws = []
    for r in batch:
        for word in r["requirement"].split():
            term = word.strip(".,;:()/").lower()
            if len(term) <= 5 or term in seen:
                continue
            seen.add(term)
            kws.append(term)
            if len(kws) >= 48:
                return kws
    return kws


def _batch_prompt(vendor, product, batch, context) -> str:
    reqs_json = [
        {"rid": r["rid"], "domain": r["domain"], "capability": r["capability"],
         "priority": r["priority"], "requirement": r["requirement"],
         "rfp_notes": r.get("rfp_notes", "")}
        for r in batch
    ]
    return (
        f"VENDOR: {vendor} — {product}\n\n"
        f"RELEVANT EXCERPTS FROM THE VENDOR'S PROPOSAL (may be partial):\n"
        f"\"\"\"\n{context[:9000]}\n\"\"\"\n\n"
        f"Score EACH of the following requirements. For each, decide:\n"
        f"  - met: Yes | Partial | No | N/A\n"
        f"  - quality: integer 1-5 (0 if N/A)\n"
        f"  - vendor_code: OOB | CONFIG | EXTENSION | CUSTOM | PARTNER | ROADMAP | GAP\n"
        f"  - confidence: High | Medium | Low (Low if the proposal does not clearly evidence it)\n"
        f"  - rationale: one terse sentence in your voice (tie to outcomes/dollars where you can)\n"
        f"  - evidence_gap: what must still be proven in the Charlotte demo or references (\"\" if none)\n\n"
        f"If the excerpts do not address a requirement, do NOT invent a capability — mark it "
        f"Partial/No with Low confidence and name the gap.\n\n"
        f"REQUIREMENTS:\n{json.dumps(reqs_json, indent=0)}\n\n"
        f"Return ONLY a JSON array, one object per requirement, keys: "
        f"rid, met, quality, vendor_code, confidence, rationale, evidence_gap."
    )


def _row_to_score(r: Dict[str, Any], row: Dict[str, Any]) -> RequirementScore:
    """Coerce one LLM row into a validated RequirementScore."""
    met = str(row.get("met", "Partial")).strip().title()
    if met not in ("Yes", "Partial", "No", "N/A"):
        met = "Partial"
    try:
        quality = int(round(float(row.get("quality", 3))))
    except (TypeError, ValueError):
        quality = 3
    quality = 0 if met == "N/A" else max(1, min(5, quality))
    code = str(row.get("vendor_code", "CONFIG")).strip().upper()
    conf = str(row.get("confidence", "Medium")).strip().title()
    if conf not in ("High", "Medium", "Low"):
        conf = "Medium"
    return RequirementScore(
        rid=r["rid"], domain=r["domain"], capability=r["capability"],
        priority=r["priority"], met=met, quality=quality, vendor_code=code,
        confidence=conf, rationale=str(row.get("rationale", "")).strip()[:400],
        evidence_gap=str(row.get("evidence_gap", "")).strip()[:300],
    )


# --------------------------------------------------------------------------- #
# Deterministic "mock" scoring (offline demo, no API key)                     #
# --------------------------------------------------------------------------- #
# Rating words -> a 0..1 capability-strength scalar.
_RATING_SCALE = {"high": 1.0, "med-high": 0.8, "medium": 0.6, "med": 0.6,
                 "med-low": 0.45, "low": 0.3}

# Which dossier rating drives each capability's mock strength. Where two ratings
# apply (e.g. compliance reflects both enterprise maturity and stability), we average.
_CAP_TO_RATING = {
    "W2C": ["hvac_fit"],                       # core FSM / work-to-cash strength
    "TPA": ["hvac_fit"],                        # technician mobile/adoption
    "PJE": ["project_financials"],              # project/construction financials
    "ACQ": ["enterprise_scale"],                # onboarding at portfolio scale
    "EVG": ["enterprise_scale"],                # enterprise visibility & governance
    "SCL": ["enterprise_scale"],                # scalable architecture
    "RLC": ["enterprise_scale", "stability"],   # regulatory/labor/SOX maturity
    "CXR": ["hvac_fit"],                        # customer experience
}

# "Hard" requirement terms that a genuinely WEAK capability cannot satisfy out of the
# box — these are where a real gap (Met=No) appears, rather than everything failing.
_HARD_TERMS = {
    "PJE": ("aia", "g702", "g703", "asc 606", "percentage-of-completion",
            "percentage of completion", "work-in-progress", "wip", "retainage",
            "progress billing"),
    "RLC": ("certified payroll", "prevailing wage", "davis-bacon", "collective bargaining",
            "cba", "segregation of duties", "sox"),
}


def _rate(word: str) -> float:
    return _RATING_SCALE.get(str(word).strip().lower(), 0.6)


def _vendor_cap_strength(vendor: str) -> Dict[str, float]:
    """
    Map a vendor's external-research ratings onto an 8-capability strength vector (0..1).
    This makes the offline demo faithful to real market positioning instead of naive
    term-matching: e.g. a vendor rated Low on project_financials shows real gaps on the
    AIA/WIP/ASC-606 'Must' requirements, while a Leader shows broad coverage.
    """
    kb = get_kb()
    ratings = (kb.vendor_profile(vendor).get("ratings") or {})
    strengths = {}
    for cap, keys in _CAP_TO_RATING.items():
        vals = [_rate(ratings.get(k, "Medium")) for k in keys]
        strengths[cap] = sum(vals) / len(vals) if vals else 0.6
    return strengths


def _mock_score_requirement(r: Dict[str, Any], proposal_text: str,
                            strengths: Optional[Dict[str, float]] = None,
                            proposal_text_lower: Optional[str] = None) -> RequirementScore:
    """
    Deterministic, dossier-grounded stand-in (offline demo, no API key). Strength comes
    from the vendor's research ratings for this requirement's capability; the proposal
    text provides confidence signal. Genuine gaps (Met=No) only appear where a WEAK
    capability meets a 'hard' requirement it cannot satisfy OOB. NOT a substitute for a
    real model on live proposals — it exists so the full pipeline/UI runs with zero keys.
    """
    if r["priority"] == "Won't":
        return RequirementScore(r["rid"], r["domain"], r["capability"], r["priority"],
                                "N/A", 0, "N/A", "High", "[demo] Out of scope (Won't).", "")

    cap = r["capability"]
    strengths = strengths or {}
    s = strengths.get(cap, 0.6)
    req_low = r["requirement"].lower() + " " + r.get("rfp_notes", "").lower()
    text = proposal_text_lower if proposal_text_lower is not None else (proposal_text or "").lower()

    # Confidence from how clearly the proposal text touches this requirement's terms.
    terms = [w.strip(".,()/") for w in r["requirement"].lower().split() if len(w) > 5]
    coverage = sum(1 for t in terms if t in text) / max(1, len(terms))

    is_hard = any(k in req_low for k in _HARD_TERMS.get(cap, ()))

    if s < 0.4 and is_hard and r["priority"] in ("Must", "Should"):
        # A real gap: weak capability, hard requirement -> not provided OOB.
        met, quality, code = "No", 1, "GAP"
    elif s < 0.4:
        met, quality, code = "Partial", 2, "ROADMAP" if is_hard else "CONFIG"
    elif s < 0.55:
        met, quality, code = "Partial", 3, "CONFIG"
    elif s < 0.75:
        met, quality, code = "Yes", 3, "CONFIG"
    elif s < 0.9:
        met, quality, code = "Yes", 4, "CONFIG"
    else:
        # Even a market-leading rating earns "strong/4 OOB" on a written pass, not a
        # perfect 5 — a 5 should require live, evidenced proof in the demo. Keeps totals
        # in a believable band rather than producing an implausible ~98/100.
        met, quality, code = "Yes", 4, "OOB"

    if s >= 0.75 and coverage >= 0.25:
        conf = "High"
    elif s < 0.4 or coverage < 0.12:
        conf = "Low"
    else:
        conf = "Medium"

    rationale = (f"[demo] {cap} strength {s:.2f} (from external-research rating); "
                 f"proposal term coverage {coverage:.0%} → {met}/{quality}.")
    gap = "" if conf == "High" else (
        f"Confirm {cap} depth in the Charlotte demo / references"
        + (" — hard requirement (AIA/WIP/ASC-606 or CBA/certified-payroll)." if is_hard else "."))
    return RequirementScore(
        rid=r["rid"], domain=r["domain"], capability=cap, priority=r["priority"],
        met=met, quality=quality, vendor_code=code, confidence=conf,
        rationale=rationale, evidence_gap=gap,
    )


# --------------------------------------------------------------------------- #
# 2) Gating (deterministic)                                                   #
# --------------------------------------------------------------------------- #
def _compute_gating(scores: List[RequirementScore], proposal_text: str) -> GatingResult:
    unmet = []
    for s in scores:
        if s.priority != "Must":
            continue
        # A Must answered ROADMAP/GAP (and not 'Yes') is effectively unmet for gating.
        if s.met == "No" or (s.vendor_code in _WEAK_CODES_FOR_MUST and s.met != "Yes"):
            unmet.append({
                "rid": s.rid, "capability": s.capability,
                "reason": f"Must requirement is {s.met} via {s.vendor_code}",
            })
    # Architectural hard gates — look for explicit negatives in the text.
    flags = []
    low = (proposal_text or "").lower()
    if "multi-tenant" in low and "single-tenant" not in low and "single tenant" not in low:
        flags.append("Single-tenant architecture not confirmed (RFP requires dedicated single-tenant).")
    if not any(k in low for k in ("union", "cba", "prevailing wage", "certified payroll")):
        flags.append("Union / CBA / prevailing-wage handling not evidenced in proposal text.")

    disqualified = len(unmet) > 0
    summary = (
        f"DISQUALIFIED — {len(unmet)} unmet 'Must' requirement(s)."
        if disqualified else
        "Passes the Must gate. " + (f"{len(flags)} architectural flag(s) to confirm." if flags else "No architectural flags.")
    )
    return GatingResult(
        disqualified=disqualified, unmet_must_count=len(unmet),
        unmet_musts=unmet[:50], architectural_gate_flags=flags, summary=summary,
    )


# --------------------------------------------------------------------------- #
# 3) Category rollup (six SSA scorecard categories)                           #
# --------------------------------------------------------------------------- #
def _leverage_mean(scores: List[RequirementScore]) -> float:
    """Priority-weighted mean of quality (Musts dominate)."""
    num = den = 0.0
    for s in scores:
        if s.met == "N/A":
            continue
        w = _PRIORITY_WEIGHT.get(s.priority, 1.0)
        num += w * s.quality
        den += w
    return round(num / den, 2) if den else 0.0


def _rollup_confidence(scores: List[RequirementScore]) -> str:
    levels = [s.confidence for s in scores if s.met != "N/A"]
    if not levels:
        return "Low"
    low = levels.count("Low") / len(levels)
    high = levels.count("High") / len(levels)
    if low >= 0.4:
        return "Low"
    if high >= 0.5:
        return "High"
    return "Medium"


def _rollup_categories(scores: List[RequirementScore]) -> List[CategoryScore]:
    kb = get_kb()
    cats = []
    for c in kb.scorecard["categories"]:
        cid = c["id"]
        if cid == "requirement_alignment":
            subset = scores  # spans every functional requirement
        elif cid == "architecture":
            hints = _CATEGORY_DOMAIN_HINTS["architecture"]
            subset = [s for s in scores if any(h in s.domain for h in hints)]
        else:
            # Understanding / Completeness / Qualifications / Financials are response-level
            # judgments. With requirement-level data only, proxy them from the relevant
            # slices so the headline math is complete and auditable:
            #   understanding  -> overall leverage mean (does the response reflect the reqs)
            #   completeness   -> share of requirements actually addressed (not No/GAP)
            #   qualifications -> EVG+SCL+RLC slices (enterprise/compliance credibility)
            #   financials     -> W2C slice as a proxy for commercial value alignment
            if cid == "qualifications":
                subset = [s for s in scores if s.capability in ("EVG", "SCL", "RLC")]
            elif cid == "financials":
                subset = [s for s in scores if s.capability == "W2C"]
            else:
                subset = scores

        if cid == "completeness":
            scorable = [s for s in scores if s.met != "N/A"]
            answered = [s for s in scorable if s.met != "No" and s.vendor_code != "GAP"]
            raw = round(5.0 * len(answered) / max(1, len(scorable)), 2)
        else:
            raw = _leverage_mean(subset)

        weighted = round(c["weight"] * (raw / 5.0) * 100, 2)
        conf = _rollup_confidence(subset)
        gaps = sorted({s.evidence_gap for s in subset if s.evidence_gap})[:6]
        rationale = _category_rationale(cid, raw, subset)
        cats.append(CategoryScore(
            id=cid, name=c["name"], weight=c["weight"], raw_1_5=raw,
            weighted_points=weighted, confidence=conf, rationale=rationale, evidence_gaps=gaps,
        ))
    return cats


def _category_rationale(cid: str, raw: float, subset: List[RequirementScore]) -> str:
    n = len([s for s in subset if s.met != "N/A"])
    no = len([s for s in subset if s.met == "No"])
    oob = len([s for s in subset if s.vendor_code in ("OOB", "CONFIG")])
    band = "strong" if raw >= 4 else "adequate" if raw >= 3 else "weak"
    return (f"{band.title()} ({raw}/5) across {n} scored items; "
            f"{oob} answered OOB/CONFIG, {no} unmet. Weighted by decision leverage (Musts 3x).")


# --------------------------------------------------------------------------- #
# 4) Capability rollup (eight RFP capabilities)                               #
# --------------------------------------------------------------------------- #
def _rollup_capabilities(scores: List[RequirementScore]) -> List[CapabilityScore]:
    kb = get_kb()
    by_code: Dict[str, List[RequirementScore]] = {}
    for s in scores:
        by_code.setdefault(s.capability, []).append(s)

    out = []
    for cap in kb.capabilities["capabilities"]:
        code = cap["code"]
        subset = by_code.get(code, [])
        raw = _leverage_mean(subset)
        unmet_must = len([s for s in subset if s.priority == "Must" and
                          (s.met == "No" or (s.vendor_code in _WEAK_CODES_FOR_MUST and s.met != "Yes"))])
        rationale = (f"{cap['name']}: {raw}/5 over {len(subset)} reqs"
                     f"{f'; {unmet_must} unmet Must(s)' if unmet_must else ''}. {cap['what_matters'][:120]}")
        out.append(CapabilityScore(
            code=code, name=cap["name"], weight=cap["weight"], score_1_5=raw,
            n_requirements=len(subset), n_unmet_must=unmet_must, rationale=rationale,
        ))
    return out


# --------------------------------------------------------------------------- #
# 5) OpCo-segment fit                                                         #
# --------------------------------------------------------------------------- #
def _segment_fit(capabilities: List[CapabilityScore]) -> List[SegmentFit]:
    """
    For each OpCo archetype, weight the capability scores by that segment's emphasis
    multipliers (segments.json) and renormalize to a 1-5 fit. This is what lets the
    agent say 'great for the big project shops, risky for the small low-maturity ones'.
    """
    kb = get_kb()
    cap_by_code = {c.code: c for c in capabilities}
    out = []
    for seg in kb.segments["archetypes"]:
        emph = seg["fit_emphasis"]
        num = den = 0.0
        for code, mult in emph.items():
            cap = cap_by_code.get(code)
            if cap:
                num += mult * cap.score_1_5
                den += mult
        fit = round(num / den, 2) if den else 0.0
        # Identify the strongest and weakest emphasized capability for a crisp rationale.
        ranked = sorted(
            [(code, cap_by_code[code].score_1_5) for code in emph if code in cap_by_code],
            key=lambda x: x[1],
        )
        weak = ranked[0] if ranked else None
        strong = ranked[-1] if ranked else None
        top_emph = ", ".join(k for k, v in sorted(emph.items(), key=lambda x: -x[1])[:3])
        rationale = (
            f"Weighted to this archetype's priorities ({top_emph}). "
            + (f"Strongest: {strong[0]} {strong[1]}/5. " if strong else "")
            + (f"Watch: {weak[0]} {weak[1]}/5." if weak else "")
        )
        out.append(SegmentFit(
            segment_id=seg["id"], segment_name=seg["name"], fit_1_5=fit, rationale=rationale,
        ))
    return out


# --------------------------------------------------------------------------- #
# 6) Agentic-future assessment                                                #
# --------------------------------------------------------------------------- #
def _agentic_future(vendor, product, proposal_text, model_id) -> AgenticFuture:
    """
    Score fit into an agentic/AI future. Per the persona doctrine, OPENNESS and
    DATA CONTROL outweigh shipped AI features ('AI is transient and disposable;
    the platform's data access matters more'). Augmented with the external dossier.
    """
    kb = get_kb()
    research = kb.vendor_profile(vendor)
    dossier_ai = research.get("agentic_ai", "")
    citations = [{"title": s.get("title", ""), "url": s.get("url", "")}
                 for s in research.get("sources", [])][:4]

    if is_mock(model_id):
        text = (proposal_text or "").lower()
        openness = 4.0 if any(k in text for k in ("open api", "rest api", "webhook",
                              "data export", "event-driven", "data lake")) else 2.5
        # AI capability is driven primarily by the external-research rating (scaled to
        # 1-5), blended with whether the proposal text actually claims AI/agent features.
        rating = str((research.get("ratings", {}) or {}).get("agentic_ai", "Medium"))
        rating_norm = rating.split("(")[0].strip().lower()  # drop notes like "(restricted)"
        rating_score = _RATING_SCALE.get(rating_norm, 0.6) * 5.0
        text_ai = 4.0 if any(k in text for k in ("agent", "copilot", "genai",
                             "machine learning", "autonomous")) else 2.5
        ai_cap = round(0.7 * rating_score + 0.3 * text_ai, 2)
        # A "(restricted)" note in the rating signals closed data access -> dock openness.
        if "restricted" in rating.lower():
            openness = min(openness, 3.0)
        score = round(0.6 * openness + 0.4 * ai_cap, 2)  # openness weighted higher
        risk = "Low" if openness >= 3.5 else "High" if openness < 2.5 else "Medium"
        rationale = (
            f"[demo] Openness/data-access {openness}/5 (weighted 60%) over shipped AI {ai_cap}/5 (40%): "
            f"the platform's data access matters more than any single AI feature today. "
            f"External research (cited): {dossier_ai or 'n/a'}"
        )
        return AgenticFuture(
            score_1_5=score, openness_1_5=openness, ai_capability_1_5=ai_cap,
            data_control_risk=risk, rationale=rationale, citations=citations,
        )

    system = kb.persona_system_prompt()
    user = (
        f"Assess how well {vendor} ({product}) fits an AGENTIC / AI future for a ~60-OpCo "
        f"HVAC rollup that wants to control its own AI destiny.\n\n"
        f"DOCTRINE: openness and data access outweigh shipped AI features — AI is transient and "
        f"almost disposable; a black-box/locked platform is a major negative.\n\n"
        f"EXTERNAL RESEARCH (use and treat as cited evidence, distinct from the proposal):\n{dossier_ai}\n\n"
        f"PROPOSAL EXCERPTS:\n\"\"\"\n{relevant_passages(proposal_text, ['api','data','ai','agent','integration','export'], 6)[:5000]}\n\"\"\"\n\n"
        f"Return ONLY JSON with keys: openness_1_5 (number), ai_capability_1_5 (number), "
        f"score_1_5 (number, weight openness 60% / ai 40%), data_control_risk (Low|Medium|High), "
        f"rationale (2-3 sentences in your voice)."
    )
    resp = client.generate(system, user, model_id, expect_json=True, max_tokens=1200, temperature=0.2)
    try:
        d = extract_json(resp["text"]) if resp["ok"] else {}
    except Exception:
        d = {}
    return AgenticFuture(
        score_1_5=float(d.get("score_1_5", 3.0)),
        openness_1_5=float(d.get("openness_1_5", 3.0)),
        ai_capability_1_5=float(d.get("ai_capability_1_5", 3.0)),
        data_control_risk=str(d.get("data_control_risk", "Medium")).title(),
        rationale=str(d.get("rationale", "")) or f"External research (cited): {dossier_ai}",
        citations=citations,
    )
