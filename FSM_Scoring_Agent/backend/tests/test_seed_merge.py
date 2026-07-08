"""Boot-time result precedence: curated committee results are git-authoritative and
win over a stale disk store; demo seed is flag-gated; real runs win over demo seed."""
import unittest

from app import _merge_results


def _r(vendor, score, curated=False):
    d = {"vendor": vendor, "weighted_total": score}
    if curated:
        d["curated"] = True
    return d


class MergeResultsTests(unittest.TestCase):
    def test_curated_seed_wins_over_stale_store(self):
        seed = [_r("IFS", 77.8, curated=True)]
        store = {"IFS": _r("IFS", 20.0)}          # stale all-DQ style store entry
        out = _merge_results(seed, store, demo_on=False)
        self.assertEqual(out["IFS"]["weighted_total"], 77.8)

    def test_curated_loads_even_when_demo_off(self):
        seed = [_r("IFS", 77.8, curated=True)]
        out = _merge_results(seed, {}, demo_on=False)
        self.assertIn("IFS", out)
        self.assertEqual(out["IFS"]["weighted_total"], 77.8)

    def test_non_curated_demo_suppressed_when_demo_off(self):
        seed = [_r("DemoCo", 50.0)]               # no curated marker
        out = _merge_results(seed, {}, demo_on=False)
        self.assertNotIn("DemoCo", out)

    def test_non_curated_demo_loads_when_demo_on_but_store_wins(self):
        seed = [_r("DemoCo", 50.0)]
        out_on = _merge_results(seed, {}, demo_on=True)
        self.assertEqual(out_on["DemoCo"]["weighted_total"], 50.0)
        # a real run in the store overrides the demo seed
        out_store = _merge_results(seed, {"DemoCo": _r("DemoCo", 61.0)}, demo_on=True)
        self.assertEqual(out_store["DemoCo"]["weighted_total"], 61.0)

    def test_new_store_vendor_included(self):
        out = _merge_results([], {"Acme": _r("Acme", 45.6)}, demo_on=False)
        self.assertEqual(out["Acme"]["weighted_total"], 45.6)


if __name__ == "__main__":
    unittest.main()
