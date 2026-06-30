"""
FSM RFP Evaluation Agent — an evidence-first, multi-analyst FSM evaluator with
deep HVAC field-service domain experience, used to score vendor RFP responses and
cast an independent, well-reasoned vote in the Service Logic FSM platform selection.

Package layout
--------------
  schemas.py    Typed result objects (dataclasses) shared across the pipeline.
  knowledge.py  Loads the JSON knowledge base (persona, scorecard, capabilities,
                segments, vendor research, models, requirements) = the agent's "character".
  providers.py  Pluggable LLM provider layer (Anthropic / OpenAI / Azure / offline mock).
                Enables per-interaction model/API selection.
  ingest.py     Parses vendor proposal files (pdf / docx / xlsx / txt / md) into text.
  scoring.py    The scoring engine: per-requirement LLM scoring, category & capability
                rollups, MoSCoW gating, OpCo-segment fit, and agentic-future assessment.
  vote.py       Synthesizes the agent's final vote (recommendation + rationale + dissent).
  chat.py       Retrieval-grounded chat assistant over the knowledge base + results.
"""

__version__ = "1.0.0"
