import unittest
import json
import os

from agent.sample import sample_proposal_text
from agent.scoring import evaluate_vendor


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
