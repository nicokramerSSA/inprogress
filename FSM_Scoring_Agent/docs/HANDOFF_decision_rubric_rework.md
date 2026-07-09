# Handoff: decision-rubric rework — session outcome

**Date:** 2026-07-08 · **For:** Nick · **From:** Camp (with Claude Code)

## Bottom line

The app now displays **real, engine-computed numbers** from a live run on the actual RFP
response files. IFS leads; Salesforce and ServiceMax are the other finalists; BuildOps and
ServiceTitan are out on enterprise scale. Live on prod since 2026-07-08.

## What was → what changed

| Vendor | July-2 run (old engine) | Codex proposal (#58) | Shipped now |
|---|---|---|---|
| IFS | 71.6 · Disqualified | 77.8 · Recommend * | **61.4 · Recommend** |
| ServiceMax | 66.5 · Disqualified | 51.6 · Shortlist * | **58.3 · Shortlist** |
| BuildOps | 67.9 · Disqualified | 45.0 · Disqualified * | **57.6 · Reject** (scale) |
| Salesforce | 69.2 · Disqualified | 63.2 · Shortlist * | **53.9 · Shortlist** |
| ServiceTitan | 61.4 · Disqualified | 48.0 · Disqualified * | **49.9 · Reject** (scale) |

\* Codex's numbers were typed into the code by hand, not computed.

- **Was:** the old engine auto-disqualified every vendor on any unmet Must — high scores,
  but everyone rejected, nothing for the committee to work with.
- **Changed:** unmet Musts now discount the score instead of auto-failing; the engine
  computes a decision-weighted score from the real evidence; an enterprise-scale gate (from
  the research dossier) screens out mid-market vendors.
- **Now:** every number is a live read of the real proposal — `claude-sonnet-4-6` across all
  422 requirements, Opus for the vote — and the verdicts reproduced across three independent
  runs (July-2-derived, fresh live, and a cross-model gpt-5.5 + Opus vote).

## The decisions we made, and why

1. **Move off all-disqualified.** Your call, and it was right — auto-DQ gave the committee
   nothing. Unmet Musts now discount and flag rather than fail.
2. **Don't hard-code the numbers — build a general engine.** Codex made the verdicts real by
   typing them in; we rebuilt so the same verdicts fall out of the evidence, for any vendor.
3. **Don't display curated numbers either.** We briefly showed your exact figures as authored
   values; you said "we are not liars." Right — so we ran the real files live and show what
   the engine actually computes.
4. **Keep the enterprise-scale gate.** The finalist/reject split can't come from the proposal
   scores alone (they cluster). The honest discriminator is enterprise scale, from the
   dossier — so BuildOps and ServiceTitan are out as mid-market vendors, flagged `ARCH-GATE`,
   not disqualified on a fabricated requirement.
5. **Remove "demo" from the UI.** The engine runs on real proposals now, so nothing should
   read as a demo.

## Why Codex was wrong

Codex reproduced your intended verdicts by writing each vendor's scores, caps, and a
fabricated `ARCH-GATE` disqualification straight into the code (later moved into a config
block — same thing). Three problems:

1. **Not auditable.** `ARCH-GATE` isn't one of the 422 real requirements. The tool's whole
   pitch is that it shows its work; a made-up disqualifying requirement fails that in the room.
2. **Doesn't generalize.** Any vendor named IFS/Salesforce/ServiceMax/ServiceTitan/BuildOps
   got the frozen numbers no matter what its proposal said; a sixth vendor got nothing.
3. **Overwrites the evidence.** Re-running a vendor replaced its real result with the constant.

And the deeper reason it had to be typed in: the evidence doesn't rank the vendors the way
the hard-coded verdicts claimed. Computed from its own responses, **BuildOps scores higher on
architecture (3.29) than ServiceMax (3.02)** — which passed. So "BuildOps fails on
architecture" isn't true from its proposal; Codex had to force a number. The real reason it's
out is scale, which is exactly what the shipped engine says.

## The honest caveat — worth telling the committee

The scores cluster, 49–62. By number alone BuildOps (57.6) ties ServiceMax (58.3) and beats
Shortlisted Salesforce (53.9). The finalist/reject line rests on **enterprise scale**, not the
score. That's defensible and it's the real story — just don't present the number itself as the
reason the two are out. If the committee wants to weight scale differently, that's a config
knob (`enterprise_scale_bar`), not a code change.
