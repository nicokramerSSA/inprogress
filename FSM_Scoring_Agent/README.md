# FSM RFP Evaluation Agent

An AI agent that scores vendor responses to the **Service Logic FSM platform RFP** and casts
an independent, well-reasoned **advisory vote** in vendor selection. It reasons like Nick Kramer
(SSA & Company), augmented with deep HVAC/mechanical field-service domain experience.

Built for SSA & Company. See **`docs/DESIGN.md`** for the full logic & design write-up.

---

## Two ways to run it

### A. Zero-install demo (no Python, no keys)
Open **`FSM_Evaluation_Agent_Standalone.html`** in any browser. The full UI runs with the
five vendors pre-evaluated on synthetic sample proposals (offline demo engine). Browse the
head-to-head ranking, each vendor's scorecard, OpCo-segment fit, agentic-future read, the
agent's vote with dissent, and the methodology. *(Live re-evaluation and chat synthesis
require the server below.)*

### B. Full app (server + live models)
```bash
cd backend
pip install -r requirements.txt          # flask required; LLM SDKs optional
python app.py                            # → http://127.0.0.1:8000
```
The app runs immediately on the **offline "mock" engine** with no keys. To use a live model,
set one or more keys and pick the model from the **top-right selector**:
```bash
export ANTHROPIC_API_KEY=sk-...          # Claude Opus / Sonnet / Haiku
export OPENAI_API_KEY=sk-...             # GPT-4o / GPT-4o mini
# Azure: AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT
```

Rebuild the standalone file after changes:
```bash
cd backend && python build_static.py     # → ../FSM_Evaluation_Agent_Standalone.html
```

### Environment variables
- `PORT` (default 8000) — override the default port the Flask server binds to.
- `ANTHROPIC_API_KEY` — enable Claude models (Opus, Sonnet, Haiku).
- `OPENAI_API_KEY` — enable GPT-4o and GPT-4o mini.
- `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` — enable Azure OpenAI models.
- `RESULTS_MAX_CONCURRENCY` (default 6) — caps how many LLM calls run at once across the whole app (scoring batches + vendors share it); raise it if your provider rate limit has headroom, lower it if you see 429s.

---

## What it does

- **Scores all 422 RFP requirements** per vendor (Met? + Quality 1–5 + response code +
  confidence + rationale + evidence gap), in the persona's voice.
- **Two scoring lenses:** the SSA scorecard categories (headline 0–100) and the RFP §30
  business-capability weighting (0–100).
- **MoSCoW + architectural gating:** any unmet *Must* disqualifies (RFP §8).
- **Per-OpCo-segment fit** across six OpCo archetypes (size/maturity/product-mix/talent).
- **"Fit into an agentic future"** — openness/data-control weighted over shipped AI features.
- **A vote:** Recommend / Shortlist / Reject / Disqualified, with narrative, steel-manned
  dissent, top risks, and evidence to close in the Charlotte demos.
- **Confidence + evidence gaps** on every rollup.
- **Head-to-head ranking** and a **grounded chat assistant**.
- **Per-interaction model selection** for scoring, vote, and each chat message.

## Per-interaction model selection
Every LLM step takes an explicit model id. The registry (`config/models.json`) covers
Anthropic, OpenAI, Azure OpenAI, and a keyless offline engine. API keys are read from the
environment at call time and never stored. Models without a present key are greyed out in the UI.

## Loading vendor responses
In the **"Evaluate a vendor"** panel: pick the vendor, then either **upload proposal files**
(drag-and-drop or browse — **PDF, DOCX, XLSX, TXT, MD**, multiple files OK) and/or **paste one
or more URLs** (portal link, shared doc, hosted PDF), pick a live model, and **Run on uploaded
sources**. The agent reads the documents against all 422 requirements itself — you don't map
answers to requirements. "Run on sample" uses the synthetic placeholder until July 2.

## Key endpoints
`GET /api/models · /api/knowledge · /api/vendors · /api/results` ·
`POST /api/evaluate {vendor, use_sample|proposal_text|file_paths|urls, scoring_model, vote_model}` ·
`POST /api/evaluate_upload (multipart: vendor, files[], urls, scoring_model, vote_model)` ·
`POST /api/chat {question, model_id, history}`

## Status & caveats
Vendor proposals are due **July 2, 2026**; until then the app runs on synthetic sample
proposals and the offline engine grounds scores in the external-research dossier (clearly
labelled "demo"). The agent is **advisory** — it augments, not replaces, the human committee.
See `docs/DESIGN.md` §9 for the full caveats.
