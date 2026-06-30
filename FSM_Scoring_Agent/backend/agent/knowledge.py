"""
knowledge.py — loads the JSON knowledge base that constitutes the agent's "character".

Everything the agent believes lives in backend/config/*.json and backend/data/*.json.
This module reads those once and exposes them through a single KnowledgeBase object,
plus helpers used by the prompt builders (e.g. compact persona summary, capability map).

Keeping the "character" in editable JSON (not hard-coded) means SSA can tune the
persona, weights, segment emphasis, and vendor research WITHOUT touching the engine.
"""
from __future__ import annotations
import json
import os
from functools import lru_cache
from typing import Dict, Any, List

# Resolve config/data relative to this file so the app runs from any working dir.
_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(os.path.dirname(_HERE), "config")
DATA_DIR = os.path.join(os.path.dirname(_HERE), "data")


def _load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class KnowledgeBase:
    """In-memory view of the agent's character + the RFP requirement set."""

    def __init__(self, config_dir: str = CONFIG_DIR, data_dir: str = DATA_DIR):
        self.persona = _load(os.path.join(config_dir, "persona.json"))
        self.scorecard = _load(os.path.join(config_dir, "scorecard.json"))
        self.capabilities = _load(os.path.join(config_dir, "capabilities.json"))
        self.segments = _load(os.path.join(config_dir, "segments.json"))
        self.vendor_research = _load(os.path.join(config_dir, "vendor_research.json"))
        self.models = _load(os.path.join(config_dir, "models.json"))
        self.requirements = _load(os.path.join(data_dir, "requirements.json"))

    # ---- convenience accessors -------------------------------------------------

    @property
    def capability_map(self) -> Dict[str, Dict[str, Any]]:
        """code -> capability dict (name, weight, ...)."""
        return {c["code"]: c for c in self.capabilities["capabilities"]}

    @property
    def category_weights(self) -> Dict[str, float]:
        return {c["id"]: c["weight"] for c in self.scorecard["categories"]}

    def requirement_list(self) -> List[Dict[str, Any]]:
        return self.requirements["requirements"]

    def vendor_profile(self, vendor_name: str) -> Dict[str, Any]:
        """Case-insensitive lookup of the external-research dossier for a vendor."""
        for v in self.vendor_research["vendors"]:
            if v["name"].lower() == vendor_name.strip().lower():
                return v
        return {}

    # ---- prompt fragments ------------------------------------------------------

    def persona_system_prompt(self) -> str:
        """
        Compact, prompt-ready rendering of the persona. Injected as the system prompt
        for every scoring / vote / chat call so each LLM interaction reasons from the same evidence-first doctrine.
        """
        p = self.persona
        lines = []
        lines.append(f"You are {p['display_name']}.")
        lines.append(p["one_line"])
        lines.append("\nDECISION STYLE: " + p["decision_style"]["summary"])
        lines.append("\nPRIORITIES (ranked):")
        for pr in p["priorities_ranked"]:
            lines.append(f"  {pr['rank']}. {pr['name']} — {pr['why']}")
        lines.append("\nRED FLAGS you actively penalize:")
        for rf in p["red_flags"]:
            lines.append(f"  - {rf['flag']}: {rf['trigger']} ({rf['penalty']})")
        lines.append("\nWEIGHTING DOCTRINE: " + p["weighting_doctrine"]["principle"])
        lines.append("AGENTIC-FUTURE DOCTRINE: " + p["agentic_future_doctrine"]["summary"])
        lines.append("OPCO-DIVERSITY DOCTRINE: " + p["opco_diversity_doctrine"]["summary"])
        if p.get("process_lessons"):
            lines.append("\nPROCESS LESSONS (hard-won; apply when weighing evidence and sequencing):")
            for lesson in p["process_lessons"]:
                lines.append("  - " + lesson)
        v = p["voice"]
        lines.append("\nVOICE: " + v["register"])
        lines.append("Signature phrases you may use sparingly: " + "; ".join(v["signature_phrases"][:5]))
        if v.get("do"):
            lines.append("ALWAYS: " + " ".join(v["do"]))
        if v.get("dont"):
            lines.append("NEVER: " + " ".join(v["dont"]))
        if v.get("house_style"):
            lines.append("\nHOUSE STYLE — applies to every rationale, narrative, and answer you write:")
            for rule in v["house_style"]:
                lines.append("  - " + rule)
        lines.append(
            "\nGround every judgment in evidence. Reward proven OOB/CONFIG over CUSTOM/ROADMAP. "
            "Treat scale, single-tenancy, data access, union/non-union isolation, and SOX as gates. "
            "Be decisive, name the single biggest risk, and flag what must be proven in the demo."
        )
        return "\n".join(lines)

    def scoring_context(self) -> str:
        """Shared RFP scoring rules injected into scoring prompts."""
        sc = self.scorecard
        out = ["RFP SCORING RULES:"]
        out.append("Quality scale (1-5): " + "; ".join(f"{k}={v}" for k, v in sc["quality_scale"].items()))
        out.append("Met values: " + "; ".join(f"{k}={v}" for k, v in sc["met_values"].items()))
        out.append("Response codes: " + ", ".join(sc["response_codes"].keys()))
        out.append("MoSCoW: " + "; ".join(f"{k}={v}" for k, v in sc["moscow"].items()))
        out.append("GATING: " + sc["gating_rules"]["description"])
        return "\n".join(out)


@lru_cache(maxsize=1)
def get_kb() -> KnowledgeBase:
    """Singleton accessor — the KB is read-only at runtime, so load it once."""
    return KnowledgeBase()
