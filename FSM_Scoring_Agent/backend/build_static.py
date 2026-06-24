"""
build_static.py — bundle the app into ONE self-contained, server-free HTML file.

It inlines the model registry, knowledge base, vendor research, and the precomputed
sample evaluations into the page as window.__BOOT__, so the result is a single
double-clickable file that runs the full UI (browse scores, vote, segments, agentic
future, methodology) with no Python and no API keys. Live evaluate/chat require the
Flask server; the standalone build clearly says so.

Usage:  python build_static.py   ->  writes ../FSM_Evaluation_Agent_Standalone.html
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRONT = os.path.join(ROOT, "frontend")

import sys
sys.path.insert(0, HERE)
from agent.knowledge import get_kb
from agent.providers import available_models

kb = get_kb()
with open(os.path.join(HERE, "data", "sample_results.json")) as f:
    results = json.load(f)
with open(os.path.join(FRONT, "ssa_logo_long_white_b64.txt")) as f:
    logo = f.read().strip()
with open(os.path.join(FRONT, "ssa_logo_long_b64.txt")) as f:
    logo_dark = f.read().strip()

boot = {
    "models": available_models(),
    "results": results,
    "vendors": kb.vendor_research["vendors"],
    "knowledge": {"persona": kb.persona, "scorecard": kb.scorecard,
                  "capabilities": kb.capabilities, "segments": kb.segments},
    "logo": logo,
    "logo_dark": logo_dark,
}

html = open(os.path.join(FRONT, "index.html"), encoding="utf-8").read()
inject = "<script>window.__BOOT__=" + json.dumps(boot) + ";</script>\n"
# Insert the boot payload just before the babel app script.
html = html.replace('<script type="text/babel">', inject + '<script type="text/babel">', 1)

out = os.path.join(ROOT, "FSM_Evaluation_Agent_Standalone.html")
open(out, "w", encoding="utf-8").write(html)
print("Wrote", out, f"({os.path.getsize(out)//1024} KB)")
