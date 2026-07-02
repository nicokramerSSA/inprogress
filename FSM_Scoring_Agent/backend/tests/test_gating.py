import unittest
from agent import scoring
from agent.schemas import RequirementScore


def _score(rid, priority, met, quality, code):
    return RequirementScore(
        rid=rid, domain="A", capability="W2C", priority=priority,
        met=met, quality=quality, vendor_code=code, confidence="High",
        rationale="t",
    )


class GatingContractTests(unittest.TestCase):
    def test_custom_must_does_not_disqualify(self):
        # CUSTOM on a Must scores Partial and must NOT disqualify.
        scores = [_score("FSM-001", "Must", "Partial", 2, "CUSTOM")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertFalse(g.disqualified)
        self.assertEqual(g.unmet_must_count, 0)

    def test_gap_must_disqualifies(self):
        scores = [_score("FSM-002", "Must", "No", 1, "GAP")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertTrue(g.disqualified)

    def test_roadmap_must_disqualifies(self):
        # ROADMAP on a Must (not answered Yes) is still disqualifying.
        scores = [_score("FSM-003", "Must", "Partial", 2, "ROADMAP")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertTrue(g.disqualified)

    def test_no_must_disqualifies_regardless_of_code(self):
        scores = [_score("FSM-004", "Must", "No", 1, "CONFIG")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertTrue(g.disqualified)

    def test_should_gap_does_not_gate(self):
        # Only Musts gate; a GAP on a Should does not disqualify.
        scores = [_score("FSM-005", "Should", "No", 1, "GAP")]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertFalse(g.disqualified)


if __name__ == "__main__":
    unittest.main()
