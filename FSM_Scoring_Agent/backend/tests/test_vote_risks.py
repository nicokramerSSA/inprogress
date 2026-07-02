import unittest
from agent import vote
from agent.schemas import RequirementScore


def _score(rid, priority, code):
    return RequirementScore(
        rid=rid, domain="A", capability="W2C", priority=priority,
        met="Partial", quality=2, vendor_code=code, confidence="High",
        rationale="t",
    )


class CustomizationRiskTests(unittest.TestCase):
    def test_none_when_no_custom_musts(self):
        scores = [_score("FSM-001", "Must", "OOB"), _score("FSM-002", "Should", "CUSTOM")]
        n, msg = vote._customization_risk(scores)
        self.assertEqual(n, 0)
        self.assertIsNone(msg)

    def test_counts_only_custom_musts(self):
        scores = [
            _score("FSM-001", "Must", "CUSTOM"),
            _score("FSM-002", "Must", "CUSTOM"),
            _score("FSM-003", "Must", "OOB"),
            _score("FSM-004", "Should", "CUSTOM"),  # not a Must -> not counted
        ]
        n, msg = vote._customization_risk(scores)
        self.assertEqual(n, 2)
        self.assertIn("2 Must requirement", msg)
        self.assertIn("custom", msg.lower())

    def test_empty_scores_safe(self):
        n, msg = vote._customization_risk([])
        self.assertEqual(n, 0)
        self.assertIsNone(msg)


class CustomizationRiskIntegrationTests(unittest.TestCase):
    def test_custom_musts_surface_in_vote(self):
        from agent import scoring
        from agent.knowledge import get_kb
        reqs = get_kb().requirement_list()
        must_rids = [r["rid"] for r in reqs if r["priority"] == "Must"][:4]
        self.assertGreaterEqual(len(must_rids), 3, "fixture needs >=3 Must requirements")
        matrix = {rid: {"code": "CUSTOM", "response": "Custom build required",
                        "source": "r.xlsx", "sheet": "Requirements"} for rid in must_rids}
        ev = scoring.evaluate_vendor("TestVendor", "", "proposal text",
                                     scoring_model="mock", requirement_sample=None,
                                     requirement_matrix=matrix)
        ev.vote = vote.synthesize_vote(ev, model_id="mock")
        self.assertTrue(any("Heavy customization" in r for r in ev.vote.top_risks),
                        f"customization risk missing from {ev.vote.top_risks}")


if __name__ == "__main__":
    unittest.main()
