import unittest
from agent import matrix_llm

REQS = [{"rid": "FSM-001"}, {"rid": "FSM-003"}, {"rid": "PJM-050"}]


def _ok(text):
    return {"ok": True, "text": text}


class FakeClient:
    """Stand-in for providers.client — returns canned generate() responses."""
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = 0

    def generate(self, system, user, model_id, **kw):
        p = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return p


class MatrixLLMTests(unittest.TestCase):
    def setUp(self):
        self._orig = matrix_llm.client

    def tearDown(self):
        matrix_llm.client = self._orig

    def test_mock_returns_empty_without_calling_model(self):
        fc = FakeClient([_ok('{"rows":[]}')])
        matrix_llm.client = fc
        self.assertEqual(matrix_llm.extract_matrix("some text", REQS, "mock"), {})
        self.assertEqual(fc.calls, 0)  # no API call on the offline engine

    def test_extracts_and_filters_to_known_rids(self):
        payload = _ok('{"rows":['
                      '{"rid":"FSM-001","code":"OOB","response":"Supported OOB."},'
                      '{"rid":"ZZZ-999","code":"GAP","response":"unknown rid"},'
                      '{"rid":"FSM-003","code":"CONFIG","response":"Configurable."}]}')
        matrix_llm.client = FakeClient([payload])
        m = matrix_llm.extract_matrix("text", REQS, "claude-sonnet-4-6")
        self.assertEqual(set(m), {"FSM-001", "FSM-003"})  # ZZZ-999 dropped
        self.assertEqual(m["FSM-001"]["code"], "OOB")
        self.assertEqual(m["FSM-003"]["code"], "CONFIG")
        self.assertTrue(m["FSM-001"]["source"].startswith("LLM-extracted"))
        self.assertEqual(m["FSM-001"]["sheet"], "LLM extraction")

    def test_code_normalization(self):
        payload = _ok('{"rows":['
                      '{"rid":"FSM-001","code":"OOB I L","response":"x"},'
                      '{"rid":"FSM-003","code":"PARTNER SOLUTION","response":"y"},'
                      '{"rid":"PJM-050","code":"gibberish","response":"z"}]}')
        matrix_llm.client = FakeClient([payload])
        m = matrix_llm.extract_matrix("text", REQS, "claude-sonnet-4-6")
        self.assertEqual(m["FSM-001"]["code"], "OOB")
        self.assertEqual(m["FSM-003"]["code"], "PARTNER")
        self.assertEqual(m["PJM-050"]["code"], "")  # unrecognized -> blank, not invented

    def test_soft_fail_when_not_ok(self):
        matrix_llm.client = FakeClient([{"ok": False, "error": "rate limit"}])
        self.assertEqual(matrix_llm.extract_matrix("text", REQS, "claude-sonnet-4-6"), {})

    def test_soft_fail_on_exception(self):
        class Boom:
            def generate(self, *a, **k):
                raise RuntimeError("kaboom")
        matrix_llm.client = Boom()
        self.assertEqual(matrix_llm.extract_matrix("text", REQS, "claude-sonnet-4-6"), {})

    def test_dedup_prefers_row_with_a_code(self):
        payload = _ok('{"rows":['
                      '{"rid":"FSM-001","code":"","response":"first, no code"},'
                      '{"rid":"FSM-001","code":"OOB","response":"second, coded"}]}')
        matrix_llm.client = FakeClient([payload])
        m = matrix_llm.extract_matrix("text", REQS, "claude-sonnet-4-6")
        self.assertEqual(m["FSM-001"]["code"], "OOB")

    def test_empty_text_returns_empty(self):
        matrix_llm.client = FakeClient([_ok('{"rows":[]}')])
        self.assertEqual(matrix_llm.extract_matrix("   ", REQS, "claude-sonnet-4-6"), {})


if __name__ == "__main__":
    unittest.main()
