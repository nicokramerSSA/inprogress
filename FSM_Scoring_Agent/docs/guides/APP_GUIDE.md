# How the app works — a plain-language guide

This guide explains what the FSM RFP Evaluation Agent does and how to use it. You don't need to know anything about software or scoring to follow along. Read it top to bottom and you'll understand the whole thing.

## What this is, in one paragraph

A company is choosing a software vendor to run its field-service business — the systems that schedule technicians, track jobs, and handle billing. To choose well, the company wrote down everything the software must do (that document is called an **RFP**) and asked each vendor to explain how their product meets it. This app reads a vendor's answers, scores how well they line up with what the company needs, and casts its own vote on whether to pick that vendor. Think of it as an extra evaluator who reads every page, never gets tired, applies the same yardstick to everyone, and shows exactly why it landed where it did. Its vote is **advisory**: it's there to inform the people making the decision, not to make that call for them.

## The words you'll see

- **RFP** — the company's list of everything it needs the software to do.
- **Requirement** — one item on that list. This RFP has 422 of them.
- **Vendor** — a company offering a product to buy.
- **Proposal** — a vendor's written answers explaining how their product meets the RFP.
- **Met?** — for each requirement, whether the vendor's product does it: yes, partly, no, or not applicable.
- **Quality (1–5)** — how well they do it, from a bare minimum (1) to excellent (5).
- **Gate** — a pass/fail rule. Some things aren't negotiable; failing one can knock a
  vendor out no matter how good the rest looks.
- **Vote** — the app's overall call on a vendor. One of four: **Recommend**,
  **Shortlist**, **Reject**, or **Disqualified**.

## Opening the app

Go to the app's web address and sign in with your email and password. The first thing you see is the **Dashboard**: the vendors, ranked by score. Click any vendor to open its full detail page.

There's also an offline version — a single file you can double-click to open in a browser
with no login and no internet. It shows pre-loaded results, which is handy for a quick
look, but scoring a new vendor or asking questions needs the full app.

## Getting around: the tabs

Across the top are eight tabs. Here's what each is for:

- **Dashboard** — every vendor ranked by score, with its vote. Your starting point.
- **Vendor detail** — the full scorecard for one vendor. This is where the real reading
  happens.
- **Compare** — put two vendors side by side and see exactly where they differ.
- **Batch evaluate** — score several vendors in one go.
- **Methodology & rubric** — the rules of the game: how scoring works and what counts.
- **Ask the agent** — a chat box where you can ask questions in plain English.
- **Committee scores** — the results as presented to the selection committee.
- **Account** — change your password or log out.

## Reading a vendor's scorecard

Open a vendor and you'll see several things, each answering a different question:

- **Headline score (0–100)** — one number for "how good is this vendor overall," weighted toward the things that matter most to the decision.
- **A second score, by capability** — the same underlying answers viewed a different way: grouped by business capability instead of by category. Two lenses on the same evidence.
- **Gates: passed or not** — whether the vendor cleared the non-negotiable rules. A vendor can score well and still be knocked out here.
- **Fit by operating-company type** — the company runs several kinds of operating
  companies, big and small, mature and new. This shows how well the vendor suits each.
- **Future-readiness** — a read on how open and adaptable the product is, and how much control you keep over your own data, rather than just which features ship today.
- **The vote, with its reasoning** — the final call, a written explanation of why, a
  deliberate counter-argument (the strongest case *against* the app's own conclusion), and the top risks to watch.
- **Every requirement, one by one** — a table of all 422 requirements with the met/quality call on each. You can open a row to see the exact quote from the proposal the app relied on, so you can check its work.

## Scoring a new vendor

To score a vendor the app hasn't seen, give it the proposal. You can upload a file (PDF,
Word, Excel, or plain text), paste a web link, or paste the text directly. Pick which AI
model should do the reading, then run it. The app reads the proposal and builds the full scorecard described above. If you have several vendors to do at once, the **Batch
evaluate** tab runs them together.

## Asking the agent questions

The **Ask the agent** tab is a chat box. Ask anything about the evaluation in plain
English — "why did this vendor get a Reject?", "which product fits our smaller operating
companies?", "how does the pass/fail gate work?" It answers using the RFP knowledge and the results already on screen, so its replies stay grounded in this specific evaluation rather than general opinion.

## How it works under the hood

Here's the whole process, start to finish, in five steps:

1. **It reads the proposal.** The app pulls the text out of whatever you gave it and gets
   it ready to work with.
2. **It scores each requirement, one at a time.** For all 422 requirements, it finds the
   relevant part of the proposal, decides whether the vendor meets it and how well, and writes a short reason plus what evidence is missing.
3. **It rolls those answers up into scores.** Thousands of individual calls become the
   headline number and the capability view. Answers that matter more to the decision carry more weight.
4. **It applies the pass/fail gates automatically.** The non-negotiable rules are checked by fixed logic, not by the AI. This keeps disqualifications consistent and auditable.
5. **It writes the vote.** The recommendation itself comes from fixed rules based on the scores and gates. The AI writes the *explanation* around that decision.

Two points worth holding onto:

- **The gates can't be talked out of.** The AI never decides who passes or fails a
  non-negotiable rule — plain logic does. That's on purpose, so no clever wording changes the outcome.
- **The AI explains; the rules decide.** The final Recommend / Shortlist / Reject /
  Disqualified comes from the numbers and gates. The AI's job is to make the reasoning clear and to argue the other side.

## How the weights and confidence work

Two ideas sit underneath every score: not everything counts equally, and the app keeps
track of how sure it is. This is what turns 422 yes/no answers into one meaningful number.

### Weights: what counts more

The app never treats all 422 requirements as equal. It weights them by how much they
matter to the decision, in a few layers:

- **How important the requirement is.** Every requirement is a Must, a Should, or a Could.
  A **Must counts three times** as much as a Could, and a Should counts twice as much. Miss
  a nice-to-have and the score barely moves; fall short on a Must and it shows.
- **How the vendor delivers it.** A "yes" isn't always worth the same. Something that works
  out of the box gets full credit. If it needs setup and configuration, it counts a little
  less. Heavy custom development or a bolt-on from a partner counts less again, and "it's on
  our roadmap" counts less still. A flat gap counts for nothing. So two vendors can both
  answer "yes" and score differently, based on what that yes would actually cost you.
- **Which part of the business it touches.** In the capability view, the bigger areas of
  the business carry more of the score than the smaller ones. Strength where it matters most
  moves the number more than strength at the edges.

Add all of that up and you get the headline score: quality, tilted toward the requirements
and areas that carry the most weight in the decision.

### Confidence: how sure the app is

For every requirement the app also records how confident it is — **High, Medium, or Low** —
based on how clearly the proposal actually proves the claim. A specific, well-evidenced
answer earns High. A vague or missing one earns Low.

Confidence then does two things:

- **It trims shaky credit.** A "yes" the app isn't sure about is worth less than one it can
  point to chapter and verse for. A Low-confidence answer keeps only about three-quarters of
  its credit, so unproven claims can't quietly inflate a score.
- **It flags where to dig.** Each part of the scorecard carries its own overall confidence.
  When enough of a section's answers are Low, the whole section reads Low — the app's way of
  saying "check this in person rather than take it off the page."

Low confidence is not the same as a low score. A vendor can look strong on paper and still
carry Low confidence, which means: promising, but make them prove it.

## Why it's called "advisory"

The app is one more voice at the table, not the final say. It reads everything the same
way for every vendor, shows its work down to the quote it relied on, and even argues
against its own conclusion so you can pressure-test it. Use it to sharpen the decision andcatch what a tired human reader might miss, then challenge it.

## Where its opinions come from

The app's priorities, its red flags, and the rules it scores by aren't buried in code.
They live in a set of plain settings files that read like a description of a careful
evaluator: what it cares about most, what worries it, and how it weighs things. That means the way it thinks can be adjusted and reviewed without rebuilding the app. And anyone can open those files to see the standard it's holding vendors to.
