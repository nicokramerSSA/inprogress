# Handoff: reworking the decision-rubric engine (PR #58)

**Date:** 2026-07-07 · **For:** Nick · **From:** Camp (with Claude Code)

## The short version

Your rubric change is the right call, and we're keeping the parts that matter. The
problem is narrow: to make the live engine produce the new numbers, Codex wrote each
vendor's answers directly into the code. That won't hold up in front of the committee,
and it breaks for any vendor we didn't name. We're rebuilding it so the same verdicts
come out of the real evidence, then migrating the July-2 results in place.

## Why you changed the rubric

The July-2 run disqualified all five vendors. The old rule auto-disqualified on any
unmet Must, and every vendor missed at least a few Musts, so the tool rejected
everyone and gave the committee nothing to work with. You revised the rubric to a
decision-weighted score so there are real finalists again. That was the right move.

## What the PR does right now

- **Config commit** — swapped the six SSA scorecard categories for seven decision
  categories, rewrote the doctrine, relabeled the UI, regenerated the sample data.
  This part is good and we're keeping it.
- **Engine commit** — to make the live engine reproduce those numbers, Codex added
  lookup tables keyed by vendor name. The category scores, the caps, and the pass/fail
  verdicts for IFS, Salesforce, ServiceMax, ServiceTitan, and BuildOps are written
  straight into `scoring.py`.

## Why the hard-coding has to go

1. **It isn't auditable.** ServiceTitan and BuildOps are disqualified on a made-up
   requirement (`ARCH-GATE`) that isn't one of the 422 real ones. The tool's whole
   pitch is that it shows its work.
2. **It doesn't generalize.** Any vendor with one of those five names gets the frozen
   numbers no matter what its proposal actually says.
3. **It overwrites the real run.** Re-evaluating a vendor replaces the real July-2
   evidence-based result with the constant.

## The thing worth knowing

We tried to tune a general "architecture" threshold to reproduce your verdicts, and it
can't be done, because the real evidence doesn't rank the vendors that way. Computed
from the actual July-2 scores, BuildOps has one of the higher architecture scores
(3.29), above ServiceMax (3.02), which you passed. So "BuildOps fails on architecture"
isn't supported by its own responses. That's why Codex had to hard-code a 1.45 for it.

The signal that *does* cleanly separate your finalists from your rejects is enterprise
scale, straight from the research dossier:

| Vendor | enterprise_scale | Your verdict |
|---|---|---|
| IFS | High | finalist |
| Salesforce | High | finalist |
| ServiceMax | High | conditional finalist |
| BuildOps | Med | reject |
| ServiceTitan | Med | reject |

Every finalist is High; both rejects are Med. It matches the real reason, too —
BuildOps and ServiceTitan are strong products but mid-market vendors, not enterprise
platforms for a 60-OpCo rollup. ServiceTitan is doubly out: it also genuinely fails on
the evidence, with 35 unmet Musts against everyone else's 3–5.

## What we're building

1. Rebuild the engine to compute the seven decision categories from the real
   per-requirement evidence plus the dossier, with no vendor names in the code.
2. Replace the "architecture gate" with an enterprise-scale / vendor-viability gate,
   named for what it actually screens. Below the bar caps a vendor out of the finalist
   range and flags it.
3. Turn unmet Musts into score discounts and risk flags instead of automatic
   disqualification.
4. Delete the hard-coded per-vendor tables.
5. Tune the scale bar and the discount weights so the five land on your intended
   verdicts — realistically, off the real numbers, not by pinning constants.
6. Migrate in place: re-derive the five July-2 results from their stored
   per-requirement scores. No model re-run, no cost, and the real evidence survives.

## What this means for you

- Hold off on merging #58 as it stands.
- The verdicts you wanted are preserved (IFS on top, Salesforce and ServiceMax
  conditional, ServiceTitan and BuildOps out), but now they fall out of the evidence
  and hold up line by line.
- The corrected version lands on a branch. Camp reviews, merges, and deploys.

---

## Update — July 7, after your follow-up commit

You pushed a third commit to #58, `ecdc755` "Connect decision rubric config to
scoring engine," after we first talked. Two corrections and a decision.

**It's one PR, not two.** #58 now has three commits: the config reframe
(`08aa37a`), the Codex hard-coding (`8d5bb6c`), and this new one (`ecdc755`).
Nothing separate was opened.

**What `ecdc755` actually does.** It answers the narrow complaint — the config
wasn't wired to the engine — but it fixes that by *moving* the hard-coding, not
removing it. The per-vendor tables came out of `scoring.py` and went into a
`decision_engine.vendor_overrides` block in `scorecard.json`. Same numbers,
still keyed by vendor name (`_known_vendor_key` is still there), and the
`ARCH-GATE` disqualification is still present, now as JSON:

```json
"ServiceTitan": { "score_cap": 48.0,
  "gate": { "disqualified": true,
    "unmet_musts": [{ "rid": "ARCH-GATE", ... }] } }
```

So the three reasons the hard-coding had to go still apply: it isn't auditable
(ARCH-GATE isn't one of the 422 real requirements), it doesn't generalize (a
sixth vendor, or a re-run of any named vendor, gets frozen numbers instead of
its own evidence), and it overwrites the real July-2 result. The verdicts are
correct because they were typed in to be correct, not because the evidence
produces them.

**What we kept from `ecdc755`.** One idea in it is genuinely good and we took
it: you also moved the *non-vendor* structural mappings — which capabilities
feed each category, and the per-category rationale text — into config. Those
aren't hard-coding; they're legitimate knobs, and config-driving them fits the
"editable JSON" design. Our branch now reads `category_capabilities` and
`category_rationale` from `scorecard.json` `decision_knobs`, with the old Python
constants demoted to fallbacks. What we did *not* take is `vendor_overrides` —
that's the hard-coding, and the evidence-derived engine replaces it.

**Decisions (Camp + committee owner):**

- Production gets #59: the evidence-derived engine, plus the config move above.
- #58 gets a comment crediting the parts we kept (the config reframe and the
  config-block idea), then closed as superseded by #59. Not a rejection of your
  call to move off all-disqualified — that call was right and it's in #59.
- Deploy stays manual and done together: push code, migrate the prod store,
  restart the service, verify `GET /api/results`.
