# Handoff: the decision-rubric rework

**Started:** 2026-07-07 · **Shipped:** 2026-07-08 · **For:** Nick · **From:** Camp (with Claude Code)

## What shipped — the current state

The app shows **real, engine-computed numbers** from a live run on the actual RFP
response files. Nothing authored, nothing labeled demo.

| Vendor | Score (0–100) | Vote |
|---|---|---|
| IFS | 61.4 | Recommend |
| ServiceMax | 58.3 | Shortlist |
| BuildOps | 57.6 | Reject (enterprise-scale gate) |
| Salesforce | 53.9 | Shortlist |
| ServiceTitan | 49.9 | Reject (enterprise-scale gate) |

- Scored by `claude-sonnet-4-6` across all 422 requirements per vendor (422/422 live, 0
  fallback), Opus for the vote. `is_demo` is false — these are genuine reads of the real
  proposals, joined to each vendor's response matrix.
- The **enterprise-scale gate is kept**: BuildOps and ServiceTitan are screened out
  because the research dossier rates them mid-market on enterprise scale — not on a
  fabricated requirement. The gate is labeled `ARCH-GATE` in the flag; they are **not**
  hard-disqualified.
- The verdicts reproduced across three independent runs — re-derived from the July-2
  scores, a fresh live run, and a fresh run with a cross-model (gpt-5.5 + Opus) vote — so
  this is stable, not one lucky pass.
- All "demo" / "offline demo" language is out of the UI now that the engine runs on real
  proposals.

Live on prod since 2026-07-08. PRs #59, #60, #62 merged; #58 (your Codex PR) closed as
superseded, with its config-reframe and config-block ideas carried forward.

## How we got here

You revised the rubric because the July-2 run disqualified all five vendors — the old
rule auto-disqualified on any unmet Must, so the tool rejected everyone and gave the
committee nothing to work with. That call was right, and it's preserved: unmet Musts now
discount the score and surface as risks instead of auto-failing.

To make the live engine reproduce your intended numbers, Codex hard-coded each vendor's
scores and a fabricated `ARCH-GATE` disqualification into the code (later relocated into a
config block — same thing). That couldn't ship: it isn't auditable (`ARCH-GATE` isn't one
of the 422 real requirements), it doesn't generalize to a new vendor or a re-run, and it
overwrites the real evidence with a constant.

We briefly displayed your exact figures as curated values while sorting this out. You
flagged the obvious problem — "we are not liars" — and you were right. Presenting authored
numbers as tool output is the one thing an advisory tool can't do.

So we did it properly: ran all five vendors' real files through the current engine, live.
The numbers above fall out of the evidence.

## The honest caveat — worth saying to the committee

The scores cluster tightly, 49–62. Ranked by number alone, BuildOps (57.6) essentially
ties ServiceMax (58.3) and outscores Shortlisted Salesforce (53.9). What separates the two
rejects from the finalists is **enterprise scale**, from the dossier — not the proposal
score. That's the honest read: BuildOps and ServiceTitan are strong products but
mid-market vendors, not enterprise platforms for a 40–80 OpCo rollup. ServiceTitan is
doubly out — it also carries the most requirement gaps, 35 against the others' handful.

We checked whether the evidence supports rejecting BuildOps on architecture instead, and
it doesn't: computed from its own responses, BuildOps scores *higher* on architecture
(3.29) than ServiceMax (3.02), which passed. That's exactly why the split has to rest on
scale, and why Codex had to hard-code a number to make architecture the reason. If the
committee wants to weight scale differently, that's a config knob (`enterprise_scale_bar`),
not a code change.

## What this means for you

- Nothing required. The numbers are live and hold up line by line.
- The five are a committed snapshot in git (`backend/data/sample_results.json`). Re-running
  one through the live engine recomputes it (within a point or two); we treat them as the
  locked committee set. To refresh them, re-run and commit the new snapshot.
- The tool is now genuinely general: upload any vendor's proposal and it scores from the
  evidence, with no vendor names in the code.
