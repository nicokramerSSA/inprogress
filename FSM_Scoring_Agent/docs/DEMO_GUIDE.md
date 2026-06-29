# FSM Evaluation Agent — Demo Talking Script

*A one-sitting guide to walk the team through the tool. Read top-to-bottom before the
demo; the headers double as your demo beats. Audience: consultants, not engineers.*

---

## The 20-second version (say this first)

This tool reads a vendor's RFP response and scores it the way Nick Kramer would — across all 422 requirements — then casts a vote: **Recommend, Shortlist, Reject, or Disqualified.**


It is **advisory**. It does not pick the winner. It gives the selection committee a fast,
consistent, fully-explained second opinion that you can argue with. The whole point is that it shows its work, so when you disagree you can see exactly where and why.

One line to land it: *"It's a tireless analyst who read all 422 requirements for every
vendor and will defend every score to your face."*

---

## What's on the screen right now (how to read the output)

Open on the **Dashboard**. The team sees five vendors ranked. Here is what the current
run says — lead with this:

| Vendor       | Score (/100) | Verdict        |
| ------------ | ------------ | -------------- |
| IFS          | 81.1         | ✅ Recommend    |
| Salesforce   | 74.1         | ❌ Disqualified |
| ServiceMax   | 74.1         | ❌ Disqualified |
| BuildOps     | 70.8         | ◆ Shortlist    |
| ServiceTitan | 70.8         | ◆ Shortlist    |

**Make them stare at the Salesforce row.** It scored a 74 — higher than both shortlisted vendors — and it's still *disqualified*. That contradiction is the most important thing in the demo. Salesforce failed a **Must** requirement, and a failed Must ends the conversation regardless of how strong everything else is. The score tells you how good a vendor is; the **verdict** tells you whether they're allowed to win.

So the reading order is always: **verdict first, score second, rationale third.** A high
score with a Disqualified verdict is not a near-miss — it's out.

When you click into a vendor, the two numbers you'll narrate are:

- **The headline score (0–100)** — quality across the whole RFP, weighted toward the
  requirements that carry the most decision leverage.
- **The verdict** — and right next to it, the *steel-manned dissent*: the strongest case
  *against* the agent's own recommendation. Point this out. A tool that argues with itself
  is one you can trust to bring you the bad news.

Below that: the top risks and "evidence to close in the Charlotte demos" — the specific
things to make each vendor prove in person.

---

## Why it's "Nick in a box," not a rules engine (the digital-twin angle)

This is the part that makes the tool different from a spreadsheet, so spend a minute here.

The agent's judgment lives in a set of plain-English **JSON files** — a "digital twin" of
Nick's decision style: what he prioritizes, what he treats as a red flag, how he weighs
architecture against price, even his voice. Nothing about *how to judge a vendor* is buried
in code. If the committee says "Nick would never weight financials that lightly," we open
the file, change the number, and re-run. No developer, no rebuild.

Two consequences worth saying out loud:

- **It's tunable by us, not just by engineers.** The persona is a document, not a black box.
- **It's auditable.** Every score comes with a rationale and an evidence gap, so "the model
  said so" is never the answer. The answer is always a sentence you can check.

One deliberate exception: **the disqualification gates are hard-coded math, and the model
cannot override them.** Single-tenant deployment, union/non-union data isolation, and any
failed Must are computed from the scores themselves — not left to the model's mood. We made
gating deterministic on purpose, so a disqualification is always defensible.

---

## How we'd actually use it in the engagement

Frame the tool's place in the real process so no one thinks we're handing the decision to a
robot:

1. **Before Charlotte** — run every vendor, read the verdicts and the dissents, and walk in with a ranked starting point and a list of exactly what to pressure-test in each demo.
2. **As a committee member that never gets tired** — it votes alongside the humans. When it disagrees with the room, that's the signal to slow down and look at the rationale.
3. **After the demos** — feed in what we learned, re-run, and watch what moves. If a vendor's verdict flips, the tool tells you which requirement changed it.
4. **Ask the agent anything** — there's a chat tab. "Why is Salesforce disqualified?"
   "Which platform fits the small low-maturity OpCos?" It answers grounded in the actual evaluation, citing what it's drawing from. Good for the live Q&A moment in the room.

The two scoring lenses are worth a sentence: the tool reports both the **SSA scorecard**
(our six evaluation categories) and the **RFP §30 business-capability** view (work-to-cash, technician productivity, project execution, and so on). Same underlying requirement scores, two ways to look at them — pick the lens that matches who's asking.

It also reads fit against our **six OpCo archetypes** — from the large project-heavy
divisions down to the small newly-tucked-in shops under $15M. A platform that's right for the national accounts may be wrong for the 44% plurality of mid-size manual shops, and the tool will say so.

---

## What to admit before someone asks (limits & caveats)

Get ahead of the obvious objections — it builds credibility:

- **It's advisory. It does not decide.** It augments the committee and expects to be
  challenged. If we ever treat its vote as the answer, we're using it wrong.
- **Today's numbers run on synthetic proposals.** Real vendor responses are due **July 2, 2026.** Until then, the inputs are realistic mock-ups grounded in our external research dossier — good enough to demo the machinery, not the verdict. Say "demo data" out loud.
- **It shows its work so you can find its mistakes.** Every score has a rationale and a named evidence gap. When it's wrong, you'll be able to point at where.
- **It reasons in Nick's voice, which is a strength and a bias.** That's the design. The
  persona is explicit and editable precisely so the bias is visible and adjustable, not
  hidden.

---

## If the demo breaks (quick recovery lines)

- **No internet / locked-down laptop?** Open `FSM_Evaluation_Agent_Standalone.html` —
  double-click, no install, all five vendors pre-evaluated. Live re-scoring and chat need the server, but everything else is browsable.
- **"Can it score a vendor we add?"** Yes — upload their proposal (PDF/DOCX/XLSX) or paste a URL on the Batch tab. On the offline file it'll show the pre-computed result instead.
- **"How long did this take to build / who maintains the logic?"** The judgment is in editable config files — a consultant can change a priority or a red flag without touching code.

---

*Bottom line for the room: this doesn't replace the committee's judgment — it makes the
committee faster and harder to fool, and it never gets tired of reading requirement #417.*
