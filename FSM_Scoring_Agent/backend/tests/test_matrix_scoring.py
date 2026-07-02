import unittest
from agent import scoring

REQ = {"rid": "FSM-001", "domain": "A", "epic": "", "requirement": "create work orders",
       "priority": "Must", "capability": "W2C", "capability_raw": "W2C", "rfp_notes": ""}

class MatrixVerdictTests(unittest.TestCase):
    def test_code_mapping(self):
        self.assertEqual(scoring._matrix_verdict("OOB"), ("Yes", 4))
        self.assertEqual(scoring._matrix_verdict("CONFIG"), ("Yes", 3))
        self.assertEqual(scoring._matrix_verdict("EXTENSION"), ("Partial", 3))
        self.assertEqual(scoring._matrix_verdict("PARTNER"), ("Partial", 2))
        self.assertEqual(scoring._matrix_verdict("ROADMAP"), ("Partial", 2))
        self.assertEqual(scoring._matrix_verdict("CUSTOM"), ("Partial", 2))
        self.assertEqual(scoring._matrix_verdict("GAP"), ("No", 1))
        self.assertEqual(scoring._matrix_verdict(""), ("No", 1))
        self.assertEqual(scoring._matrix_verdict("wat"), ("Partial", 2))

    def test_mock_uses_matrix_when_present(self):
        m = {"FSM-001": {"code": "OOB", "response": "Available in base release",
                          "source": "resp.xlsx", "sheet": "Requirements"}}
        s = scoring._mock_score_requirement(REQ, "", {}, "", None, m)
        self.assertEqual(s.met, "Yes")
        self.assertEqual(s.quality, 4)
        self.assertEqual(s.vendor_code, "OOB")
        self.assertEqual(s.confidence, "High")
        self.assertEqual(s.evidence.get("locator"), "Requirements / FSM-001")

    def test_mock_falls_back_without_matrix(self):
        s = scoring._mock_score_requirement(REQ, "", {}, "", None, {})
        self.assertIn(s.met, ("Yes", "Partial", "No"))  # dossier path still works


class BatchPromptTests(unittest.TestCase):
    BATCH = [REQ]

    def test_prompt_includes_matrix_block(self):
        m = {"FSM-001": {"code": "OOB", "response": "Available in base",
                          "source": "resp.xlsx", "sheet": "Requirements"}}
        p = scoring._batch_prompt("ServiceTitan", "", self.BATCH, "some excerpt", m)
        self.assertIn("VENDOR'S DIRECT ANSWERS", p)
        self.assertIn("[FSM-001]", p)
        self.assertIn("OOB", p)
        self.assertIn("Available in base", p)
        self.assertIn("some excerpt", p)   # fuzzy excerpts still present

    def test_prompt_omits_block_without_matrix(self):
        p = scoring._batch_prompt("ServiceTitan", "", self.BATCH, "some excerpt", {})
        self.assertNotIn("VENDOR'S DIRECT ANSWERS", p)
        self.assertIn("some excerpt", p)


class EndToEndMockTests(unittest.TestCase):
    def test_matrix_flows_into_mock_scores(self):
        from agent.knowledge import get_kb
        reqs = get_kb().requirement_list()
        rid = reqs[0]["rid"]
        matrix = {rid: {"code": "GAP", "response": "Not supported", "source": "r.xlsx",
                        "sheet": "Requirements"}}
        ev = scoring.evaluate_vendor("TestVendor", "", "proposal text",
                                     scoring_model="mock", requirement_sample=3,
                                     requirement_matrix=matrix)
        row = next(s for s in ev.requirement_scores if s.rid == rid)
        self.assertEqual(row.met, "No")
        self.assertEqual(row.vendor_code, "GAP")
        self.assertEqual(row.confidence, "High")
