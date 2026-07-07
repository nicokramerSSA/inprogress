import unittest
import json
import os

from agent.sample import sample_proposal_text
from agent.scoring import evaluate_vendor, _scale_tier, _enterprise_scale_gate, _compute_gating
from agent.schemas import RequirementScore


class DecisionRubricRegressionTests(unittest.TestCase):
    def test_categories_are_computed_not_frozen_lookup(self):
        # A made-up vendor name must still get differentiated, non-degenerate categories.
        ev = evaluate_vendor("Acme FSM", "", sample_proposal_text("IFS"), scoring_model="mock")
        raws = [c.raw_1_5 for c in ev.categories]
        assert len(set(round(r, 2) for r in raws)) > 1       # not all identical
        assert all(0.0 <= r <= 5.0 for r in raws)

    def test_hardcoded_tables_removed(self):
        import agent.scoring as s
        for name in (
            "_KNOWN_DECISION_DIMENSIONS", "_KNOWN_CAPABILITY_MULTIPLIERS",
            "_DECISION_SCORE_CAPS", "_DECISION_GATE_OVERLAYS",
        ):
            assert not hasattr(s, name), f"{name} still present"

    def test_scale_gated_vendor_lands_in_reject_band(self):
        ev = evaluate_vendor("BuildOps", "", sample_proposal_text("BuildOps"), scoring_model="mock")
        assert ev.gating.disqualified is False
        assert ev.weighted_total <= 64                      # capped into Reject band
        assert any("scale" in f.lower() for f in ev.gating.architectural_gate_flags)

    def test_high_scale_vendor_not_capped(self):
        ev = evaluate_vendor("IFS", "", sample_proposal_text("IFS"), scoring_model="mock")
        assert not any("scale" in f.lower() for f in ev.gating.architectural_gate_flags)


class EnterpriseScaleGateTests(unittest.TestCase):
    def test_scale_tier_mapping(self):
        assert _scale_tier("High") == 5
        assert _scale_tier("Med") == 3
        assert _scale_tier("Med-High") == 4
        assert _scale_tier("unknown") == 3   # safe default

    def test_enterprise_scale_gate_uses_dossier(self):
        gated_bo, reason_bo = _enterprise_scale_gate("BuildOps")   # dossier scale = Med
        gated_ifs, _ = _enterprise_scale_gate("IFS")               # dossier scale = High
        assert gated_bo is True and "scale" in reason_bo.lower()
        assert gated_ifs is False


class GatingDecisionTests(unittest.TestCase):
    def _req(self, rid, met, code, prio="Must"):
        """Helper to construct a RequirementScore for testing."""
        return RequirementScore(
            rid=rid, domain="Domain A",
            priority=prio, capability="W2C", met=met, quality=1, vendor_code=code,
            confidence="Low", rationale="", evidence_gap="")

    def test_unmet_musts_do_not_disqualify(self):
        """Unmet Musts are collected and surfaced as risks, but no longer auto-disqualify."""
        scores = [self._req("R1", "No", "GAP"), self._req("R2", "No", "GAP")]
        g = _compute_gating(scores, "single-tenant, union, prevailing wage", {})
        assert g.disqualified is False, "disqualified should be False even with unmet Musts"
        assert g.unmet_must_count == 2, "unmet Musts should still be counted"
        assert len(g.unmet_musts) == 2, "unmet Musts list should be populated"


class ConfigTests(unittest.TestCase):
    def test_decision_knobs_present_and_weights_sum_to_one(self):
        CFG = os.path.join(os.path.dirname(__file__), "..", "config", "scorecard.json")
        sc = json.load(open(CFG))
        knobs = sc["decision_knobs"]
        assert knobs["enterprise_scale_bar"] == "High"
        assert knobs["scale_gate_cap"] <= 64          # below the Shortlist floor (65)
        assert abs(sum(c["weight"] for c in sc["categories"]) - 1.0) < 1e-9


if __name__ == "__main__":
    unittest.main()
