# FSM RFP Evaluation Agent — Design & Logic Documentation

**Client:** Service Logic (Bain Capital portfolio) · **Engagement:** SSA & Company
**Purpose:** An AI agent that scores vendor responses to the Service Logic Field Service
Management (FSM) platform RFP and casts an **independent, well-reasoned advisory vote** in
the vendor-selection process. It is built to reason like Nick Kramer (SSA), augmented with
deep HVAC/mechanical field-service domain experience.

> The agent is **advisory** — one more seat at the table, not the decision-maker. Its job is
> to be the most prepared, most consistent, least fatigued evaluator in the room, and to show
> its work so humans can challenge it.

---

## 1. What the agent produces

For each vendor the agent outputs, all visible in the UI and the API:

1. **A weighted total score (0–100)** on the SSA scorecard category weighting (the headline).
2. **A capability-weighted score (0–100)** on the RFP Section-30 business-capability lens.
3. **A MoSCoW + architectural gate result** — any unmet *Must* requirement disqualifies.
4. **Per-OpCo-segment fit (1–5)** across the six OpCo archetypes.
5. **A "fit into an agentic future" assessment** (openness/data-control weighted over shipped AI).
6. **A vote**: Recommend / Shortlist / Reject / Disqualified, with narrative, **dissent**,
   top risks, and the evidence to close in the July 13–16 Charlotte demos.
7. **Confidence levels and explicit evidence gaps** on every rollup.
8. **Requirement-level detail** — Met?, Quality (1–5), response code, confidence, rationale,
   and evidence gap for all 422 requirements.

A **head-to-head ranking** and a **grounded chat assistant** sit on top of these.

---

## 2. The "character" — how the agent reasons like Nick

The agent's personality and judgment live entirely in editable JSON (`backend/config/`),
not in code, so SSA can tune the agent without touching the engine. The persona was mined
from ~3 months of Service Logic engagement transcripts and the RFP scorecard. Its core
doctrines, each of which changes the math or the narrative:

| Doctrine | Source (Nick, verbatim) | How it's encoded |
|---|---|---|
| **Weight by decision leverage, not nominal importance** | "the weighting really is not how important each one is, it's how much it factors into our decision" | Musts weighted 3×, Shoulds 2× in every rollup; capabilities everyone meets equally barely move the score. |
| **Data/integration & a clean common model first** | "the only thing you can really commonalize is the data" | Openness/data-access dominates the agentic-future score (60/40 over shipped AI). |
| **Anti-black-box is near-disqualifying** | "if I don't have access to all the data… we don't need to keep talking" | A "(restricted)" data-access signal docks openness and raises data-control risk. |
| **Raise the floor across OpCos, don't race the ceiling** | "the company's health is better served by raising the floor" | Per-segment fit weights low-maturity archetypes toward simplicity/onboarding (TPA, ACQ). |
| **Reward proven OOB/CONFIG over CUSTOM/ROADMAP** | "requirements theater… come on" | ROADMAP/GAP on a Must is treated as unmet for gating; quality penalised. |
| **Lead with the verdict, name the single biggest risk, flag what to prove in the demo** | voice profile | Vote narrative structure + `evidence_to_close`. |

The persona is injected as the **system prompt** on every LLM call (scoring, vote, chat) via
`KnowledgeBase.persona_system_prompt()`, so each interaction reasons in-voice.

---

## 3. Knowledge base (the agent's grounding)

All under `backend/config/` and `backend/data/`:

- **`persona.json`** — decision style, ranked priorities, red flags, weighting/agentic/OpCo
  doctrines, voice. (The "digital twin".)
- **`scorecard.json`** — the six SSA categories + weights, quality scale, Met? values,
  response codes, MoSCoW, **gating rules**, confidence model. (From the SSA Vendor Scorecard.)
- **`capabilities.json`** — the eight RFP business capabilities + weights + what-good-looks-like.
- **`segments.json`** — OpCo segmentation dimensions, six archetypes, and each archetype's
  **capability emphasis multipliers** (the per-segment fit lens).
- **`vendor_research.json`** — the external-research dossier for each vendor (ownership,
  analyst position, HVAC fit, project financials, agentic AI, risks) with **source URLs**.
  Used as cited evidence, kept distinct from internal scoring.
- **`models.json`** — the provider/model registry (per-interaction model selection).
- **`data/requirements.json`** — the authentic 422-row requirement set (RID, domain, epic,
  text, priority, capability), normalised to the eight-capability scheme.

---

## 4. Scoring pipeline (`agent/scoring.py`)

```
proposal text ──▶ [1] per-requirement scoring (LLM, batched)  ─┐
                                                               ├─▶ [2] gating (deterministic)
                                                               ├─▶ [3] SSA category rollup
                                                               ├─▶ [4] capability rollup
                                                               ├─▶ [5] OpCo-segment fit
                                                               └─▶ [6] agentic-future
                                          ▼
                               VendorEvaluation ──▶ vote.py (synthesize vote)
```

### [1] Per-requirement scoring
Requirements are scored in **batches of 12** to control tokens/latency. For each batch, the
engine localises the most relevant passages of the vendor's proposal (simple term-overlap
retrieval — no vector store needed) and asks the selected model to return, per requirement:
`met` (Yes/Partial/No/N/A), `quality` (1–5), `vendor_code` (OOB/CONFIG/…/GAP), `confidence`,
a one-line `rationale`, and an `evidence_gap`. Outputs are validated/coerced; any row the
model skips falls back to the deterministic engine so the rollups never have holes.

### [2] Gating (deterministic, not the model's opinion)
A *Must* requirement marked **No**, or answered **ROADMAP/GAP** and not "Yes", counts as
**unmet** → **disqualifying** (RFP §8). Architectural hard-gate flags (single-tenant,
union/CBA isolation) are raised when the proposal text fails to evidence them. Gating is
computed from the scores directly so it is reproducible and auditable.

### [3] SSA category rollup → headline 0–100
Each of the six categories gets a 1–5 score = **priority-leverage-weighted mean** of its
requirements' quality (Must 3× / Should 2× / Could 1×). `weighted_points = weight × (raw/5) ×
100`; the headline total is their sum. Category→requirement mapping:
*Requirement Alignment* spans all functional reqs; *Architecture* draws on domains H/I/K/NFR;
*Completeness* = share of requirements actually addressed (not No/GAP); *Qualifications* uses
the EVG/SCL/RLC slices; *Financials* uses the W2C slice; *Understanding* uses the overall mean.
(These proxies are explicit and documented; when real proposals arrive they can be scored
directly from the response narrative.)

### [4] Capability rollup → 0–100 (RFP §30 lens)
Same leverage-weighted mean, grouped by the eight capability codes (W2C 25%, TPA 20%, PJE 15%,
ACQ 10%, EVG 10%, RLC 10%, CXR 5%, SCL 5%), plus an unmet-Must count per capability.

### [5] OpCo-segment fit (1–5 per archetype)
For each of the six archetypes, capability scores are re-weighted by that archetype's
**emphasis multipliers** (`segments.json`) and renormalised. This is what lets the agent say
"strong for the large project-heavy OpCos, thin for the small low-maturity tuck-ins."

### [6] Agentic-future assessment
`score = 0.6 × openness + 0.4 × ai_capability`. Openness (API/data-access) is weighted higher
because, per doctrine, the platform's data access matters more than any single AI feature —
"AI is transient and almost disposable." A restricted-data signal raises **data-control risk**.
Augmented with the cited external-research AI rating.

### Confidence & evidence gaps
Every rollup carries a confidence (High/Medium/Low) by worst-case/majority of its
requirements, and surfaces the concrete **evidence gaps to close in Charlotte**.

---

## 5. The vote (`agent/vote.py`)

The vote is deliberately separate from the arithmetic. A **deterministic rubric** maps the
0–100 total to a band (≥78 Recommend, ≥65 Shortlist, else Reject), with a disqualifying gate
overriding everything. The selected model then writes the verdict-first **narrative** and the
strongest honest **dissent** against its own recommendation; risks and evidence-to-close are
assembled from the structured findings. The offline engine composes these from the findings so
the vote is always present.

---

## 6. Per-interaction model selection (`agent/providers.py`, `config/models.json`)

Every LLM-touching step — requirement scoring, vote synthesis, and each chat message —
accepts an explicit `model_id`. The registry supports **Anthropic, OpenAI, Azure OpenAI**, and
a keyless **offline "mock" engine**. The UI's top-right selector exposes the registry and greys
out models whose API key is absent. Keys are read from environment variables **at call time and
never stored**. Task defaults (`scoring → Sonnet`, `vote → Opus`, `chat → Haiku`) are suggested
but fully overridable per interaction.

### The offline "mock" engine
So the entire app runs with **zero API keys** (for demos and tests), a deterministic engine
grounds each requirement's score in the vendor's **external-research capability ratings** mapped
onto the eight capabilities, with genuine gaps (Met=No) appearing only where a *weak* capability
meets a *hard* requirement it cannot satisfy out of the box (e.g. AIA G702/G703, WIP, ASC 606 for
a vendor weak on project financials; CBA/certified-payroll for a vendor weak on labor compliance).
Every mock output is clearly labelled **"[demo]"**. It is **not** a substitute for a real model on
live proposals.

---

## 7. Chat assistant (`agent/chat.py`)

A retrieval-grounded assistant lets a user interrogate the agent: "Why is Salesforce
disqualified?", "Which platform fits the small low-maturity OpCos?", "How does the Must gate
work?". It assembles context from (1) the static knowledge base, (2) this session's
evaluations, and (3) the question's keywords (auto-including a vendor's dossier when named),
then answers **as the persona, citing what it used**. Model is chosen per message. The offline
mode returns the grounded evidence transparently rather than fabricating an answer.

---

## 8. Loading real proposals (`agent/ingest.py`)

Proposals are due **July 2**. There are three ways to load a vendor's responses; all feed the
same pipeline (just select a live model instead of `mock`):

1. **Upload in the UI** — the "Evaluate a vendor" panel takes drag-and-drop or browse of
   **PDF / DOCX / XLSX / TXT / MD** (multiple files per vendor). Files post to
   `POST /api/evaluate_upload` (multipart), are saved under `data/uploads/<vendor>/`, parsed by
   `extract_text()` (tables included), and scored. Unsupported types are rejected with a message.
2. **Point at a URL** — the same panel accepts one or more vendor URLs (portal link, shared doc,
   hosted PDF). `fetch_url()` downloads each, extracts document text or strips HTML, and the
   passages are scored alongside any uploaded files. (This is the locally-run app fetching a link
   the operator supplied.)
3. **API** — `POST /api/evaluate` with `file_paths`, `urls`, or raw `proposal_text` for scripted/
   batch runs.

`extract_sources(paths, urls)` merges any mix of files and URLs into one delimited blob so
retrieval can attribute passages back to their source. Until proposals arrive, the app runs on
synthetic sample proposals (`agent/sample.py`) shaped to each vendor's real-world profile.

---

## 9. Limitations & honest caveats

- **The mock engine is illustrative, not evaluative.** Sample scores reflect dossier ratings,
  not a real reading of a real proposal. Treat the demo numbers as plausible placeholders.
- **Category proxies.** Understanding/Completeness/Qualifications/Financials are proxied from
  requirement slices until full proposal narratives exist; this is documented and adjustable.
- **External research has a knowledge cut-off** and should be refreshed before the live round;
  several dossier items are flagged "verify in RFP."
- **The agent votes; it does not decide.** Its highest value is consistency, full-coverage
  diligence, a steel-manned dissent, and a clear list of what to prove in the demos.
- **Disqualification is strict by design.** A high-scoring vendor can still be disqualified on a
  single unmet Must (see Salesforce/ServiceMax on project-financials in the sample) — that is the
  RFP rule, surfaced loudly so humans can decide whether to waive it.

---

## 10. File map

```
FSM-RFP-Evaluation-Agent/
├─ backend/
│  ├─ app.py                  Flask API + serves the React SPA
│  ├─ build_static.py         Bundles a server-free standalone HTML
│  ├─ requirements.txt
│  ├─ agent/
│  │  ├─ knowledge.py         Loads the JSON knowledge base ("character")
│  │  ├─ providers.py         Multi-provider LLM layer + per-call model selection
│  │  ├─ scoring.py           The scoring engine (steps 1–6)
│  │  ├─ vote.py              Vote synthesis (recommendation + dissent + risks)
│  │  ├─ chat.py              Grounded chat assistant
│  │  ├─ ingest.py            Proposal file parsing + lightweight retrieval
│  │  ├─ sample.py            Synthetic sample proposals (demo)
│  │  └─ schemas.py           Typed result objects
│  ├─ config/                 persona, scorecard, capabilities, segments, vendor_research, models
│  └─ data/                   requirements.json (422), sample_results.json
├─ frontend/
│  ├─ index.html              The React single-page app (SSA-branded)
│  └─ ssa_logo_*_b64.txt      SSA logo assets
├─ docs/DESIGN.md             (this file)
└─ FSM_Evaluation_Agent_Standalone.html   Double-clickable, server-free demo build
```
