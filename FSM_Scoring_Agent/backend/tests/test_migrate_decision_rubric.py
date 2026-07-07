"""
test_migrate_decision_rubric.py — migration mechanics only (idempotency + evidence
preservation). The verdict test (whether the five land at the committee's outcomes)
is deliberately NOT written here — it is Task 9's calibration target.
"""
import json
import os
import unittest

from agent.migrate_decision_rubric import rederive_result

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "july2_store_snapshot.json")


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.results = {v["vendor"]: v for v in json.load(open(FIX))}

    def test_rederive_is_idempotent(self):
        once = rederive_result(self.results["IFS"])
        twice = rederive_result(once)
        self.assertEqual(once["weighted_total"], twice["weighted_total"])
        self.assertEqual(once["capability_weighted_total"], twice["capability_weighted_total"])
        self.assertEqual([c["id"] for c in once["categories"]],
                         [c["id"] for c in twice["categories"]])
        self.assertEqual([c["weighted_points"] for c in once["categories"]],
                         [c["weighted_points"] for c in twice["categories"]])
        self.assertEqual([c["score_1_5"] for c in once["capabilities"]],
                         [c["score_1_5"] for c in twice["capabilities"]])
        self.assertEqual(once["gating"], twice["gating"])
        self.assertEqual(once["vote"]["recommendation"], twice["vote"]["recommendation"])

    def test_rederive_preserves_requirement_scores(self):
        once = rederive_result(self.results["IFS"])
        self.assertEqual(len(once["requirement_scores"]), 422)   # evidence untouched
        self.assertEqual(once["requirement_scores"], self.results["IFS"]["requirement_scores"])

    def test_rederive_preserves_agentic_future_and_external_research(self):
        original = self.results["IFS"]
        once = rederive_result(original)
        self.assertEqual(once["agentic_future"], original["agentic_future"])
        self.assertEqual(once["external_research"], original["external_research"])

    def test_rederive_updates_evaluated_at(self):
        original = self.results["IFS"]
        once = rederive_result(original)
        self.assertNotEqual(once["evaluated_at"], original["evaluated_at"])

    def test_rederive_runs_for_all_five_vendors(self):
        for vendor, result in self.results.items():
            out = rederive_result(result)
            self.assertEqual(out["vendor"], vendor)
            self.assertIsInstance(out["weighted_total"], (int, float))
            self.assertIsInstance(out["capability_weighted_total"], (int, float))
            self.assertIn("vote", out)
            self.assertIn("recommendation", out["vote"])

    def test_rederive_carries_over_real_flags_non_scale_gated(self):
        """IFS is not enterprise-scale-gated. Its migrated architectural_gate_flags
        must equal the ORIGINAL result's real (July-2, proposal-derived) flags —
        not the spurious union/CBA flag an empty-text keyword scan would fire."""
        original = self.results["IFS"]
        original_flags = original["gating"]["architectural_gate_flags"]
        once = rederive_result(original)
        self.assertEqual(once["gating"]["architectural_gate_flags"], original_flags)
        self.assertFalse(
            any("Union" in f or "CBA" in f for f in once["gating"]["architectural_gate_flags"]),
            "spurious empty-text union/CBA flag leaked into migrated gating",
        )

    def test_rederive_carries_over_real_flags_scale_gated(self):
        """BuildOps IS enterprise-scale-gated. Migrated flags must equal the
        original real flags plus exactly one scale-gate reason, and re-deriving an
        already-migrated result must not append a second copy of that reason."""
        original = self.results["BuildOps"]
        original_flags = original["gating"]["architectural_gate_flags"]

        once = rederive_result(original)
        once_flags = once["gating"]["architectural_gate_flags"]
        scale_flags = [f for f in once_flags if "scale" in f.lower()]
        self.assertEqual(len(scale_flags), 1, once_flags)
        self.assertEqual(once_flags, original_flags + scale_flags)

        twice = rederive_result(once)
        twice_flags = twice["gating"]["architectural_gate_flags"]
        self.assertEqual(twice_flags, once_flags)  # idempotent — no double scale flag
        self.assertEqual(len([f for f in twice_flags if "scale" in f.lower()]), 1)


if __name__ == "__main__":
    unittest.main()
