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


class UnmetMustEnrichmentTests(unittest.TestCase):
    def test_unmet_entry_includes_requirement_detail(self):
        scores = [_score("FSM-002", "Must", "No", 1, "GAP")]
        req_text = {"FSM-002": "Support prevailing-wage certified payroll."}
        g = scoring._compute_gating(scores, "proposal text", req_text)
        self.assertEqual(len(g.unmet_musts), 1)
        entry = g.unmet_musts[0]
        self.assertEqual(entry["rid"], "FSM-002")
        self.assertEqual(entry["requirement"], "Support prevailing-wage certified payroll.")
        self.assertEqual(entry["priority"], "Must")
        self.assertEqual(entry["vendor_code"], "GAP")
        self.assertEqual(entry["met"], "No")

    def test_missing_req_text_defaults_empty(self):
        scores = [_score("FSM-002", "Must", "No", 1, "GAP")]
        g = scoring._compute_gating(scores, "proposal text")  # no req_text
        self.assertEqual(g.unmet_musts[0]["requirement"], "")

    def test_unmet_list_not_truncated(self):
        scores = [_score(f"FSM-{i:03d}", "Must", "No", 1, "GAP") for i in range(60)]
        g = scoring._compute_gating(scores, "proposal text")
        self.assertEqual(len(g.unmet_musts), 60)
        self.assertEqual(g.unmet_must_count, 60)


if __name__ == "__main__":
    unittest.main()
