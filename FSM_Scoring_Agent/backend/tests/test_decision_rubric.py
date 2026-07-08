import unittest
import json
import os

from agent.sample import sample_proposal_text
from agent.scoring import evaluate_vendor, _scale_tier, _enterprise_scale_gate, _compute_gating
from agent.schemas import RequirementScore
from agent.vote import synthesize_vote


class DecisionRubricRegressionTests(unittest.TestCase):
    def test_categories_are_computed_not_frozen_lookup(self):
        # A made-up vendor name must still get differentiated, non-degenerate categories.
        ev = evaluate_vendor("Acme FSM", "", sample_proposal_text("IFS"), scoring_model="mock")
        raws = [c.raw_1_5 for c in ev.categories]
        assert len(set(round(r, 2) for r in raws)) > 1       # not all identical
        assert all(0.0 <= r <= 5.0 for r in raws)

    def test_hardcoded_tables_removed(self):
        import agent.scoring as s
        for name in (
            "_KNOWN_DECISION_DIMENSIONS", "_KNOWN_CAPABILITY_MULTIPLIERS",
            "_DECISION_SCORE_CAPS", "_DECISION_GATE_OVERLAYS",
        ):
            assert not hasattr(s, name), f"{name} still present"

    def test_scale_gated_vendor_lands_in_reject_band(self):
        ev = evaluate_vendor("BuildOps", "", sample_proposal_text("BuildOps"), scoring_model="mock")
        assert ev.gating.disqualified is False
        assert ev.weighted_total <= 64                      # capped into Reject band
        assert any("scale" in f.lower() for f in ev.gating.architectural_gate_flags)

    def test_high_scale_vendor_not_capped(self):
        ev = evaluate_vendor("IFS", "", sample_proposal_text("IFS"), scoring_model="mock")
        assert not any("scale" in f.lower() for f in ev.gating.architectural_gate_flags)


class EnterpriseScaleGateTests(unittest.TestCase):
    def test_scale_tier_mapping(self):
        assert _scale_tier("High") == 5
        assert _scale_tier("Med") == 3
        assert _scale_tier("Med-High") == 4
        assert _scale_tier("unknown") == 3   # safe default

    def test_enterprise_scale_gate_uses_dossier(self):
        gated_bo, reason_bo = _enterprise_scale_gate("BuildOps")   # dossier scale = Med
        gated_ifs, _ = _enterprise_scale_gate("IFS")               # dossier scale = High
        assert gated_bo is True and "scale" in reason_bo.lower()
        assert gated_ifs is False

    def test_off_dossier_vendor_is_not_gated(self):
        """A vendor with no dossier entry (and hence no enterprise_scale rating on
        file) must never be scale-gated on a fabricated 'Medium' default."""
        gated, reason = _enterprise_scale_gate("Totally New FSM Co")
        assert gated is False
        assert reason == ""


class GatingDecisionTests(unittest.TestCase):
    def _req(self, rid, met, code, prio="Must"):
        """Helper to construct a RequirementScore for testing."""
        return RequirementScore(
            rid=rid, domain="Domain A",
            priority=prio, capability="W2C", met=met, quality=1, vendor_code=code,
            confidence="Low", rationale="", evidence_gap="")

    def test_unmet_musts_do_not_disqualify(self):
        """Unmet Musts are collected and surfaced as risks, but no longer auto-disqualify."""
        scores = [self._req("R1", "No", "GAP"), self._req("R2", "No", "GAP")]
        g = _compute_gating(scores, "single-tenant, union, prevailing wage", {})
        assert g.disqualified is False, "disqualified should be False even with unmet Musts"
        assert g.unmet_must_count == 2, "unmet Musts should still be counted"
        assert len(g.unmet_musts) == 2, "unmet Musts list should be populated"


class ConfigTests(unittest.TestCase):
    def test_decision_knobs_present_and_weights_sum_to_one(self):
        CFG = os.path.join(os.path.dirname(__file__), "..", "config", "scorecard.json")
        sc = json.load(open(CFG))
        knobs = sc["decision_knobs"]
        assert knobs["enterprise_scale_bar"] == "High"
        assert 0 < knobs["scale_gate_cap"] <= 100     # display ceiling for a scale-gated vendor's headline
        assert abs(sum(c["weight"] for c in sc["categories"]) - 1.0) < 1e-9

    def test_structural_mappings_are_config_driven_and_match_fallback(self):
        """category_capabilities and category_rationale live in config (adopted from
        PR #58's config-block idea), and the config values equal the code fallbacks so
        behavior is identical whether or not the block is present."""
        import agent.scoring as s
        CFG = os.path.join(os.path.dirname(__file__), "..", "config", "scorecard.json")
        knobs = json.load(open(CFG))["decision_knobs"]
        cats = ["operating", "project", "architecture",
                "implementation", "evidence", "agentic", "commercial"]
        assert set(knobs["category_capabilities"].keys()) == set(cats)
        assert set(knobs["category_rationale"].keys()) == set(cats)
        for cid in cats:
            assert list(knobs["category_capabilities"][cid]) == \
                list(s._DECISION_CATEGORY_CAPABILITIES[cid]), \
                f"config category_capabilities[{cid}] diverges from fallback"
            assert knobs["category_rationale"][cid] == s._DECISION_CATEGORY_RATIONALE[cid], \
                f"config category_rationale[{cid}] diverges from fallback"

    def test_engine_reads_category_capabilities_from_config(self):
        """_decision_subset must honor a config override, proving the mapping is not
        hard-wired to the Python constant."""
        import agent.scoring as s
        from agent.knowledge import get_kb
        knobs = get_kb().scorecard.setdefault("decision_knobs", {})
        saved = knobs.get("category_capabilities")
        try:
            knobs["category_capabilities"] = {"operating": ["ZZZ"]}   # no score has this cap
            subset = s._decision_subset(
                "operating",
                [RequirementScore(rid="R1", domain="D", priority="Must", capability="W2C",
                                  met="Yes", quality=5, vendor_code="OOB",
                                  confidence="High", rationale="", evidence_gap="")],
            )
            assert subset == [], "override to ['ZZZ'] should exclude the W2C score"
        finally:
            if saved is None:
                knobs.pop("category_capabilities", None)
            else:
                knobs["category_capabilities"] = saved


class CuratedSeedTests(unittest.TestCase):
    """The five committee-facing results are curated (authored) values, not engine
    output. These guard the displayed numbers and the honest ARCH-GATE wording."""

    def setUp(self):
        seed_path = os.path.join(os.path.dirname(__file__), "..", "data", "sample_results.json")
        self.seed = {r["vendor"]: r for r in json.load(open(seed_path))}

    def test_curated_headline_numbers_are_nicks_values(self):
        expected = {
            "IFS": (77.8, "Recommend", False),
            "Salesforce": (63.2, "Shortlist", False),
            "ServiceMax": (51.6, "Shortlist", False),
            "ServiceTitan": (48.0, "Disqualified", True),
            "BuildOps": (45.0, "Disqualified", True),
        }
        for vendor, (score, vote, dq) in expected.items():
            r = self.seed[vendor]
            assert r["weighted_total"] == score, f"{vendor} headline {r['weighted_total']} != {score}"
            assert r["vote"]["recommendation"] == vote, f"{vendor} vote {r['vote']['recommendation']} != {vote}"
            assert r["gating"]["disqualified"] is dq, f"{vendor} dq {r['gating']['disqualified']} != {dq}"
            assert r.get("curated") is True, f"{vendor} missing curated marker"

    def test_arch_gate_kept_and_reason_is_honest(self):
        for vendor in ("ServiceTitan", "BuildOps"):
            gate = self.seed[vendor]["gating"]
            arch = [m for m in gate["unmet_musts"] if m.get("rid") == "ARCH-GATE"]
            assert arch, f"{vendor} lost its ARCH-GATE entry"
            reason = arch[0]["reason"].lower()
            assert "scale" in reason, f"{vendor} ARCH-GATE reason not scale-anchored"
            assert "ARCH-GATE" in " ".join(gate["architectural_gate_flags"]), \
                f"{vendor} gate flag dropped the ARCH-GATE label"

    def test_buildops_vote_no_longer_blames_architecture(self):
        """BuildOps's own evidence scores architecture high; its rejection is a scale
        call. The curated vote must not claim architecture failure."""
        vote = self.seed["BuildOps"]["vote"]
        assert "scale" in vote["narrative"].lower()
        assert "architecture" not in vote["top_risks"][0].lower(), \
            "BuildOps top risk should be scale-anchored, not architecture"


class GateDrivenVoteTests(unittest.TestCase):
    def test_scale_gated_vote_is_reject_regardless_of_score(self):
        ev = evaluate_vendor("BuildOps", "", sample_proposal_text("BuildOps"), scoring_model="mock")
        ev.vote = synthesize_vote(ev, "mock")
        assert ev.vote.recommendation == "Reject"           # gate overrides the band
        assert ev.gating.disqualified is False               # Reject, not Disqualified

    def test_ungated_vendor_banded_by_decision_score(self):
        ev = evaluate_vendor("IFS", "", sample_proposal_text("IFS"), scoring_model="mock")
        ev.vote = synthesize_vote(ev, "mock")
        assert ev.vote.recommendation in ("Recommend", "Shortlist")   # a finalist, not Reject


class PropertyBasedRegressionTests(unittest.TestCase):
    def test_engine_properties_for_all_five(self):
        """Property assertions over all five vendors: categories, values, and gating."""
        for vendor in ["IFS", "Salesforce", "ServiceMax", "ServiceTitan", "BuildOps"]:
            ev = evaluate_vendor(vendor, "", sample_proposal_text(vendor), scoring_model="mock")
            ev.vote = synthesize_vote(ev, "mock")
            # categories present, in order, with values in range [0,5] and not all identical
            raws = [c.raw_1_5 for c in ev.categories]
            assert [c.id for c in ev.categories] == [
                "operating", "project", "architecture",
                "implementation", "evidence", "agentic", "commercial"
            ], f"Category IDs for {vendor} do not match expected order"
            assert all(0 <= r <= 5 for r in raws), f"Some raw_1_5 values out of range for {vendor}"
            assert len(set(round(r, 2) for r in raws)) > 1, f"All category values identical for {vendor}"
            # no fabricated requirement ids in the gate
            assert all(m.get("rid") != "ARCH-GATE" for m in ev.gating.unmet_musts), \
                f"Found ARCH-GATE in unmet_musts for {vendor}"

    def test_scale_gate_matches_dossier_for_all_five(self):
        """Assert _enterprise_scale_gate returns expected values per vendor dossier."""
        expected = {
            "IFS": False,
            "Salesforce": False,
            "ServiceMax": False,
            "ServiceTitan": True,
            "BuildOps": True
        }
        for vendor, exp in expected.items():
            gated, _ = _enterprise_scale_gate(vendor)
            assert gated is exp, f"{vendor}: expected gated={exp}, got {gated}"


if __name__ == "__main__":
    unittest.main()
