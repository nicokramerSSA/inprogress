"""
chat.py — retrieval-grounded chat assistant over the agent's knowledge base + results.

Lets a user interrogate the agent in natural language:
  * "Why did you reject vendor X?"  -> grounded in that vendor's evaluation
  * "How does the Must gate work?"  -> grounded in the scorecard rules
  * "Which platform fits the small low-maturity OpCos best?" -> grounded in segment fit
  * "What's the agentic-future read on ServiceTitan?" -> grounded in agentic + dossier

It assembles a compact CONTEXT from three sources — (1) the static knowledge base
(persona, scorecard, capabilities, segments, vendor research), (2) any completed
vendor evaluations passed in, and (3) the chat question's keywords — then asks the
selected model to answer AS the persona, citing what it used. The mock engine returns
a transparent, retrieval-only answer so chat works with no API key.

The model is chosen PER MESSAGE (model_id argument), satisfying the per-interaction
model-selection requirement for the chat surface too.
"""
from __future__ import annotations

import json
from typing import List, Dict, Any, Optional

from .knowledge import get_kb
from .providers import client, is_mock


# --------------------------------------------------------------------------- #
# Context assembly                                                            #
# --------------------------------------------------------------------------- #
def _kb_context(question: str) -> str:
    """Pull the most relevant static knowledge for the question's keywords."""
    kb = get_kb()
    q = question.lower()
    parts: List[str] = []

    # Always include the scoring rules + capability map — they're small and central.
    parts.append("SCORECARD CATEGORIES & WEIGHTS: " + ", ".join(
        f"{c['name']} {int(c['weight']*100)}%" for c in kb.scorecard["categories"]))
    parts.append("GATING: " + kb.scorecard["gating_rules"]["description"])
    parts.append("CAPABILITIES & WEIGHTS: " + ", ".join(
        f"{c['code']} {c['name']} {int(c['weight']*100)}%" for c in kb.capabilities["capabilities"]))

    # Conditionally include the heavier sections when the question implicates them.
    if any(k in q for k in ("segment", "opco", "archetype", "residential", "project", "small",
                            "maturity", "yale", "tolin", "fit")):
        parts.append("OPCO ARCHETYPES: " + "; ".join(
            f"{s['name']} (needs: {', '.join(s['needs'][:3])})" for s in kb.segments["archetypes"]))
    if any(k in q for k in ("ai", "agent", "agentic", "openness", "data", "future")):
        parts.append("AGENTIC DOCTRINE: " + kb.persona["agentic_future_doctrine"]["summary"])
    # Vendor dossiers if a vendor is named.
    for v in kb.vendor_research["vendors"]:
        if v["name"].lower() in q:
            parts.append(
                f"EXTERNAL RESEARCH — {v['name']} ({v.get('product','')}): "
                f"stability {v.get('stability','')}; analyst {v.get('analyst','')}; "
                f"HVAC fit {v.get('hvac_fit','')}; project financials {v.get('project_financials','')}; "
                f"agentic {v.get('agentic_ai','')}; risks {v.get('risks','')}. "
                f"Sources: {', '.join(s.get('url','') for s in v.get('sources',[])[:3])}")
    return "\n".join(parts)


def _results_context(results: Optional[List[Dict[str, Any]]], question: str) -> str:
    """Summarize completed evaluations relevant to the question."""
    if not results:
        return "No vendor evaluations have been run yet in this session."
    q = question.lower()
    lines = ["COMPLETED EVALUATIONS (this session):"]
    # Rank for the head-to-head context.
    ranked = sorted(results, key=lambda r: (-(not r.get("gating", {}).get("disqualified", False)),
                                            -r.get("weighted_total", 0)))
    for r in ranked:
        v = r.get("vendor", "?")
        g = r.get("gating", {})
        gate = "DISQUALIFIED" if g.get("disqualified") else "PASS"
        unmet = g.get("unmet_must_count", 0)
        # State verdict and Must-gate as explicit, citable facts. The model was
        # conflating a disqualified vendor's status onto a passing one and inventing
        # Must counts; giving it a hard token + number per vendor removes the gap.
        line = (f"- {v}: verdict={r.get('vote',{}).get('recommendation','?')}; "
                f"must_gate={gate} ({unmet} unmet Must(s)); "
                f"score {r.get('weighted_total')}/100 "
                f"(capability {r.get('capability_weighted_total')}/100). "
                f"{g.get('summary','')}")
        lines.append(line)
        # If this vendor is named in the question, include richer detail.
        if v.lower() in q:
            caps = sorted(r.get("capabilities", []), key=lambda c: c["score_1_5"])
            lines.append("    weakest caps: " + ", ".join(
                f"{c['code']} {c['score_1_5']}/5" for c in caps[:3]))
            lines.append("    segment fit: " + ", ".join(
                f"{s['segment_name'].split(',')[0]} {s['fit_1_5']}/5" for s in r.get("segment_fit", [])))
            v_obj = r.get("vote", {})
            if v_obj.get("narrative"):
                lines.append("    vote narrative: " + v_obj["narrative"][:600])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
def answer(question: str, results: Optional[List[Dict[str, Any]]] = None,
           model_id: str = "mock", history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """
    Answer a chat question grounded in the KB + results.
    Returns {"answer": str, "model": str, "is_demo": bool, "grounding": [labels]}.
    """
    kb_ctx = _kb_context(question)
    res_ctx = _results_context(results, question)
    grounding = ["scorecard", "capabilities"]
    if results:
        grounding.append("evaluations")
    for v in get_kb().vendor_research["vendors"]:
        if v["name"].lower() in question.lower():
            grounding.append(f"research:{v['name']}")

    if is_mock(model_id):
        return {"answer": _mock_answer(question, kb_ctx, res_ctx),
                "model": "mock", "is_demo": True, "grounding": grounding}

    kb = get_kb()
    system = (
        kb.persona_system_prompt() +
        "\n\nYou are answering questions about your own FSM vendor evaluation. "
        "Answer ONLY from the provided context; if it isn't there, say so plainly. "
        "State each vendor's verdict and Must-gate exactly as its results line gives them: "
        "a vendor is disqualified ONLY if its line says must_gate=DISQUALIFIED. When comparing "
        "vendors, never carry one vendor's disqualification onto another. Never invent counts or "
        "scores — cite only numbers that appear in the context. "
        "Be concise and decisive, and name your evidence."
    )
    hist = ""
    if history:
        hist = "\n".join(f"{h['role'].upper()}: {h['content']}" for h in history[-6:]) + "\n"
    user = (
        f"CONTEXT — KNOWLEDGE BASE:\n{kb_ctx}\n\n"
        f"CONTEXT — RESULTS:\n{res_ctx}\n\n"
        f"{hist}"
        f"QUESTION: {question}"
    )
    resp = client.generate(system, user, model_id, expect_json=False, max_tokens=900, temperature=0.3)
    text = resp["text"] if resp["ok"] else f"(model error: {resp.get('error')})"
    return {"answer": text, "model": resp.get("model", model_id),
            "is_demo": False, "grounding": grounding}


def _mock_answer(question: str, kb_ctx: str, res_ctx: str) -> str:
    """
    Transparent retrieval-only answer (no generation). Returns the grounded context
    the agent WOULD reason over, so the chat surface is useful and honest with no key.
    """
    return (
        "[demo chat — no model key set; showing the grounded evidence the agent would reason over]\n\n"
        f"You asked: \"{question}\"\n\n"
        f"FROM THE KNOWLEDGE BASE:\n{kb_ctx}\n\n"
        f"FROM THIS SESSION'S RESULTS:\n{res_ctx}\n\n"
        "Select a real model (top-right) to get a synthesized, in-voice answer."
    )
