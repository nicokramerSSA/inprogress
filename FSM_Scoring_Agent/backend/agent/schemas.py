"""
schemas.py — typed result objects passed between the scoring, vote, and API layers.

These are plain dataclasses (no heavy ORM). Every object has a .to_dict() so the
Flask API can serialize results to JSON for the React front-end, and so results can
be cached to disk (data/sample_results.json) for offline "demo mode".
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class RequirementScore:
    """One scored RFP requirement for one vendor."""
    rid: str                      # e.g. "FSM-001"
    domain: str
    capability: str               # normalized 8-capability code (W2C, TPA, ...)
    priority: str                 # Must / Should / Could / Won't
    met: str                      # Yes / Partial / No / N/A
    quality: int                  # 1-5 (0 if N/A)
    vendor_code: str              # OOB / CONFIG / EXTENSION / CUSTOM / PARTNER / ROADMAP / GAP
    confidence: str               # High / Medium / Low
    rationale: str                # short justification in the agent's voice
    evidence_gap: str = ""        # what still must be proven (demo / references)
    evidence: Dict[str, Any] = field(default_factory=dict)  # {quote, source, locator}; {} if none

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CategoryScore:
    """One of the six SSA scorecard categories."""
    id: str
    name: str
    weight: float                 # 0..1
    raw_1_5: float                # category quality on the 1-5 scale
    weighted_points: float        # weight * (raw_1_5/5) * 100, contribution to total
    confidence: str
    rationale: str
    evidence_gaps: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityScore:
    """One of the eight RFP business capabilities (W2C, TPA, ...)."""
    code: str
    name: str
    weight: float
    score_1_5: float
    n_requirements: int
    n_unmet_must: int
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SegmentFit:
    """How well the platform fits one OpCo archetype."""
    segment_id: str
    segment_name: str
    fit_1_5: float
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GatingResult:
    """MoSCoW + architectural gate outcome."""
    disqualified: bool
    unmet_must_count: int
    unmet_musts: List[Dict[str, str]] = field(default_factory=list)  # [{rid, capability, reason}]
    architectural_gate_flags: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgenticFuture:
    """Assessment of fit into an agentic/AI future (openness > shipped features)."""
    score_1_5: float
    openness_1_5: float           # API / data-access openness
    ai_capability_1_5: float      # shipped AI / agent products & roadmap
    data_control_risk: str        # Low / Medium / High — can the OpCo control its own AI destiny?
    rationale: str
    citations: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Vote:
    """The agent's final, independent vote."""
    recommendation: str           # Recommend / Shortlist / Reject / Disqualified
    confidence: str               # High / Medium / Low
    narrative: str                # in the panel's reconciled voice
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


@dataclass
class VendorEvaluation:
    """The complete evaluation of one vendor."""
    vendor: str
    product: str
    model_used: str               # which LLM/provider produced this evaluation
    is_demo: bool                 # True if the numbers came from the offline mock engine
                                  # (explicit 'mock' selection OR a live model that fully
                                  #  fell back — see engine_warning)
    evaluated_at: str

    weighted_total: float         # 0-100, headline SSA-category score
    capability_weighted_total: float  # 0-100, RFP Section-30 capability lens
    gating: GatingResult = None
    categories: List[CategoryScore] = field(default_factory=list)
    capabilities: List[CapabilityScore] = field(default_factory=list)
    segment_fit: List[SegmentFit] = field(default_factory=list)
    agentic_future: AgenticFuture = None
    vote: Vote = None
    external_research: Dict[str, Any] = field(default_factory=dict)
    requirement_scores: List[RequirementScore] = field(default_factory=list)

    # Live-vs-fallback bookkeeping (non-mock runs only). When a live model is selected
    # but some/all per-requirement scoring calls fail, those requirements fall back to
    # the deterministic offline engine. These fields make that visible instead of silent.
    scoring_live_count: int = 0       # requirements actually scored by the live model
    scoring_fallback_count: int = 0   # requirements that fell back to the offline engine
    engine_warning: str = ""          # human-readable warning when fallback occurred

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d
