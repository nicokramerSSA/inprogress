import json
import unittest
from pathlib import Path

from agent.knowledge import get_kb
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

    def test_decision_engine_inputs_live_in_scorecard_config(self):
        scorecard = get_kb().scorecard
        engine = scorecard["decision_engine"]
        category_ids = {c["id"] for c in scorecard["categories"]}
        self.assertEqual(set(engine["category_capabilities"]), category_ids)
        self.assertIn("operating_capability_weights", engine)
        self.assertIn("category_rationale", engine)
        self.assertEqual(
            set(engine["vendor_overrides"]),
            {"IFS", "Salesforce", "ServiceMax", "ServiceTitan", "BuildOps"},
        )

    def test_cached_sample_results_match_recomputed_engine_scores(self):
        data_path = Path(__file__).resolve().parents[1] / "data" / "sample_results.json"
        cached = {r["vendor"]: r for r in json.loads(data_path.read_text())}

        for vendor, cached_row in cached.items():
            with self.subTest(vendor=vendor):
                ev = evaluate_vendor(
                    vendor,
                    "",
                    sample_proposal_text(vendor),
                    scoring_model="mock",
                )
                self.assertEqual(ev.weighted_total, cached_row["weighted_total"])
                self.assertEqual(
                    ev.capability_weighted_total,
                    cached_row["capability_weighted_total"],
                )
                self.assertEqual(
                    ev.gating.disqualified,
                    cached_row["gating"]["disqualified"],
                )
                self.assertEqual(
                    {c.id: c.raw_1_5 for c in ev.categories},
                    {c["id"]: c["raw_1_5"] for c in cached_row["categories"]},
                )
                self.assertEqual(
                    {c.code: c.score_1_5 for c in ev.capabilities},
                    {c["code"]: c["score_1_5"] for c in cached_row["capabilities"]},
                )


if __name__ == "__main__":
    unittest.main()
