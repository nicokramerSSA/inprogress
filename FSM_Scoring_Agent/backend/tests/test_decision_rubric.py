import unittest
import json
import os

from agent.sample import sample_proposal_text
from agent.scoring import evaluate_vendor, _scale_tier, _enterprise_scale_gate, _compute_gating
from agent.schemas import RequirementScore


class DecisionRubricRegressionTests(unittest.TestCase):
    def test_mock_engine_uses_revised_decision_rubric_for_five_respondents(self):
        expected = {
            "IFS": (77.8, 75.5, False),
            "Salesforce": (63.2, 52.3, False),
            "ServiceMax": (51.6, 45.0, False),
            "ServiceTitan": (48.0, 58.9, True),
            "BuildOps": (45.0, 59.5, True),
        }

        for vendor, (decision_score, oob_score, disqualified) in expected.items():
            with self.subTest(vendor=vendor):
                ev = evaluate_vendor(
                    vendor,
                    "",
                    sample_proposal_text(vendor),
                    scoring_model="mock",
                )
                self.assertEqual(ev.weighted_total, decision_score)
                self.assertEqual(ev.capability_weighted_total, oob_score)
                self.assertEqual(ev.gating.disqualified, disqualified)
                self.assertEqual(
                    [c.id for c in ev.categories],
                    [
                        "operating", "project", "architecture", "implementation",
                        "evidence", "agentic", "commercial",
                    ],
                )


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
