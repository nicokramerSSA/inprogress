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

    def test_content_match_fallback_with_section_row_between_header_and_data(self):
        # RID column header is unrecognized ("Ref"), and a section row sits
        # between the real header row and the first data row — a realistic
        # vendor-matrix shape. The content-matching fallback must still find
        # the header row (not the section row) so response columns resolve.
        # Response columns are NOT the last two columns, so the header-keyword
        # match ("response" in header text) must be used to find them — the
        # trailing "Notes" column would be picked instead if the fallback
        # (last-two-filled-columns) logic kicks in due to reading the wrong
        # (section) row as the header.
        header = ["Ref", "Domain", "Requirement", "Priority", "Cap.",
                  "Vendor Response", "Vendor RFP Response", "Notes"]
        rows = [
            ["Domain A: FSM", None, None, None, None, None, None, None],   # section row
            ["FSM-001", "A", "create work orders", "Must", "W2C", "OOB", "Generally available in base", "n/a"],
            ["FSM-003", "A", "configurable types", "Must", "W2C", "CONFIG", "Supported via configuration", "n/a"],
            ["PJM-050", "A", "flag prevailing wage", "Should", "PJE", "OOB", "Supported natively", "n/a"],
        ]
        _make_xlsx(self.path, header, rows)
        m = ingest.extract_requirement_matrix([self.path], REQS)
        self.assertEqual(set(m), {"FSM-001", "FSM-003", "PJM-050"})
        self.assertEqual(m["FSM-001"]["code"], "OOB")
        self.assertEqual(m["FSM-001"]["response"], "Generally available in base")
        self.assertEqual(m["FSM-003"]["code"], "CONFIG")

    def test_no_matrix_returns_empty(self):
        _make_xlsx(self.path, ["Some", "Other", "Columns"], [["a", "b", "c"]])
        self.assertEqual(ingest.extract_requirement_matrix([self.path], REQS), {})

    def test_non_xlsx_and_empty_paths(self):
        self.assertEqual(ingest.extract_requirement_matrix([], REQS), {})
        txt = os.path.join(self.tmp, "x.txt"); open(txt, "w").write("hi")
        self.assertEqual(ingest.extract_requirement_matrix([txt], REQS), {})


class MatrixTextFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.path = os.path.join(self.tmp, "resp.xlsx")

    def test_text_fallback_when_no_rid_column(self):
        # No 'Req ID' column and values don't match RIDs -> join on requirement text.
        header = ["Requirement", "Vendor Response", "Vendor RFP Response"]
        rows = [
            ["Ability to create work orders from inbound calls", "OOB", "Available"],
            ["Ability to support configurable work order types", "CONFIG", "Configurable"],
            ["Ability to flag projects as prevailing wage", "OOB", "Supported natively"],
        ]
        _make_xlsx(self.path, header, rows)
        m = ingest.extract_requirement_matrix([self.path], REQS)
        self.assertEqual(m["FSM-001"]["code"], "OOB")
        self.assertEqual(m["FSM-003"]["code"], "CONFIG")
        self.assertEqual(m["PJM-050"]["code"], "OOB")


class CodeColumnDetectionTests(unittest.TestCase):
    """A vendor may title its code column 'Code' (no 'response' in the header),
    with a single 'response'-titled narrative column beside it (the Salesforce
    layout). The extractor must still capture the code, not blank it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.path = os.path.join(self.tmp, "resp.xlsx")

    def test_code_column_named_code_is_captured(self):
        # Salesforce layout: one 'response' narrative column + a separate 'Code' column.
        header = ["Req ID", "Requirement", "Priority", "Cap.", "Notes",
                  "Vendor Response (Finalized)", "Code"]
        rows = [
            ["FSM-001", "create work orders", "Must", "W2C", "note",
             "Yes, Salesforce natively supports this.", "CONFIG"],
        ]
        _make_xlsx(self.path, header, rows)
        m = ingest.extract_requirement_matrix([self.path], REQS)
        self.assertEqual(m["FSM-001"]["code"], "CONFIG")
        self.assertTrue(m["FSM-001"]["response"].startswith("Yes, Salesforce"))

    def test_two_response_headers_still_split_code_vs_narrative(self):
        # BuildOps layout regression: 'Response Code' (short) + 'Vendor Response'
        # (long narrative). Both contain 'response'; the code stays the short one.
        header = ["Req ID", "Requirement", "Priority", "Cap.", "Notes",
                  "Response Code", "Vendor Response"]
        rows = [
            ["FSM-001", "create work orders", "Must", "W2C", "note",
             "OOB", "Jobs are created directly from the inbound call intake screen."],
        ]
        _make_xlsx(self.path, header, rows)
        m = ingest.extract_requirement_matrix([self.path], REQS)
        self.assertEqual(m["FSM-001"]["code"], "OOB")
        self.assertTrue(m["FSM-001"]["response"].startswith("Jobs are created"))
