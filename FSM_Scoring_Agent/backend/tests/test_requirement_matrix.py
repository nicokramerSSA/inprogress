import os, tempfile, unittest
import openpyxl
from agent import ingest

def _make_xlsx(path, header, rows):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Requirements"
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(path)

REQS = [
    {"rid": "FSM-001", "requirement": "Ability to create work orders from inbound calls"},
    {"rid": "FSM-003", "requirement": "Ability to support configurable work order types"},
    {"rid": "PJM-050", "requirement": "Ability to flag projects as prevailing wage"},
]

class MatrixRidJoinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "resp.xlsx")

    def test_rid_column_join(self):
        header = ["Req ID", "Domain", "Requirement", "Priority", "Cap.",
                  "Vendor Response", "Vendor RFP Response"]
        rows = [
            ["Domain A: FSM", None, None, None, None, None, None],   # section row, ignored
            ["FSM-001", "A", "create work orders", "Must", "W2C", "OOB", "Generally available in base"],
            ["FSM-003", "A", "configurable types", "Must", "W2C", "CONFIG", "Supported via configuration"],
            ["ZZZ-999", "A", "not a real rid", "Must", "W2C", "OOB", "ignored"],  # unknown rid
        ]
        _make_xlsx(self.path, header, rows)
        m = ingest.extract_requirement_matrix([self.path], REQS)
        self.assertEqual(set(m), {"FSM-001", "FSM-003"})
        self.assertEqual(m["FSM-001"]["code"], "OOB")
        self.assertEqual(m["FSM-001"]["response"], "Generally available in base")
        self.assertEqual(m["FSM-003"]["code"], "CONFIG")
        self.assertEqual(m["FSM-001"]["source"], "resp.xlsx")
        self.assertEqual(m["FSM-001"]["sheet"], "Requirements")

    def test_no_matrix_returns_empty(self):
        _make_xlsx(self.path, ["Some", "Other", "Columns"], [["a", "b", "c"]])
        self.assertEqual(ingest.extract_requirement_matrix([self.path], REQS), {})

    def test_non_xlsx_and_empty_paths(self):
        self.assertEqual(ingest.extract_requirement_matrix([], REQS), {})
        txt = os.path.join(self.tmp, "x.txt"); open(txt, "w").write("hi")
        self.assertEqual(ingest.extract_requirement_matrix([txt], REQS), {})
