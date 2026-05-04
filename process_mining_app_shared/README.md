# FlowScope Miner (pm4py)

FlowScope Miner is a Disco-style process mining web app built on top of `pm4py`.

## What this app includes

- Event log import for `.csv` and `.xes`
- Light UI with black/white + `#003399` accents
- Column mapping for CSV import:
  - Auto-detect/suggest mapping from CSV headers + sample values
  - Case ID
  - Activity
  - Start timestamp
  - Stop/complete timestamp
  - Actor/resource
  - Additional informational columns (multi-select)
  - Additional filter-only columns (multi-select)
- Interactive filtering:
  - Time window
  - Include/exclude activities
  - Dynamic filter-only attribute filters (for user-selected columns)
  - Activity frequency threshold
  - Path frequency threshold
  - Case duration bounds
  - Top-variant retention
- Process map (DFG-style network) with two display modes:
  - Frequency labels
  - Performance labels (median waiting time between activities)
- Animated process playback:
  - Time-binned transition animation
  - Play/pause, restart, step forward/back, speed control, frame scrubber
- Actor-aware handoff analytics (when actor/resource is present):
  - Actor-focused handoff graph
  - Activity-focused handoff graph (handoffs only where actor changes)
- Alternate diagram views:
  - BPMN-style flowchart with normalized activities and gateway-like branch/merge markers
  - Sankey flow diagram
  - Rework hotspot view
  - Queue age heatmap
  - Rework treemap
  - Variant duration boxplot
- Metrics and diagnostics:
  - Cases, events, activities, case durations, rework ratio
  - Variant ranking with volume/share and durations
  - Bottleneck transitions (median and p90 waiting time)
  - Activity-level coverage
  - Informational column profiles (top values and distinct counts)
- Conformance run (inductive miner + token-based replay metrics where supported)
- Export package:
  - `summary.json`
  - `nodes.csv`, `edges.csv`, `variants.csv`, `bottlenecks.csv`, `activity_stats.csv`
  - Disco-style summary metric exports under `summary_metrics/`: `Activities.csv` plus relation matrices for absolute frequency, case frequency, case coverage, maximum repetition, and duration statistics
  - `handoff_actor_edges.csv`, `handoff_activity_edges.csv`
  - `bpmn_flowchart_nodes.csv`, `bpmn_flowchart_edges.csv`, `sankey_links.csv`
  - `rework_activity.csv`, `rework_self_loops.csv`
  - `informational_columns_profile.json`
  - `filtered_events.csv`
  - `animation_frames.json`
  - Mermaid diagrams (`*.mmd`) for process map, handoff views, BPMN flowchart, sankey, and rework (when available)
  - BPMN model export (`process_model.bpmn`) when supported by your pm4py version
- Self-contained HTML report export:
  - Single downloadable `.html` file with summary metrics, process map snapshot, handoff/BPMN flowchart/sankey/rework sections, Mermaid blocks, and BPMN XML

## Project layout

- `backend/main.py`: FastAPI service and endpoints
- `backend/analytics.py`: pm4py ingestion + process mining calculations
- `frontend/index.html`: dashboard UI shell
- `frontend/styles.css`: visual design
- `frontend/app.js`: frontend logic and process map rendering

## Run locally

1. Create and activate a Python 3.10+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
uvicorn backend.main:app --reload --app-dir .
```

4. Open: [http://127.0.0.1:8000](http://127.0.0.1:8000)

## CSV format expectations

Default CSV mapping values in the upload form:

- `case_id`
- `activity`
- `start_timestamp`
- `stop_timestamp`
- `actor`

Use **Suggest Mapping from CSV** to auto-populate likely case/activity/timestamp/actor fields.
You can override any suggestion before clicking **Load Log**.
If only one timestamp column is available, map it to the start timestamp field.
At least one timestamp column (start or stop) must be resolvable.

Actor/resource-aware handoff features are enabled automatically when one of these columns is present and populated:

- `org:resource`
- `resource`
- `actor`
- `user`
- `assignee`

## Logging and Debugging

### Backend logging

The backend uses Python's `logging` module under the `flowscope` logger hierarchy. Every HTTP request is automatically logged with method, path, status code, elapsed time, and a unique request ID (also returned in the `X-Request-Id` response header).

Key analytics operations (filter application, transition computation, dashboard assembly, conformance, animation) emit timing and data-flow metrics at `DEBUG` level.

To increase verbosity, set the log level before starting the server:

```bash
LOG_LEVEL=DEBUG uvicorn backend.main:app --reload --app-dir .
```

Or adjust at runtime in Python:

```python
import logging
logging.getLogger("flowscope").setLevel(logging.DEBUG)
```

### Frontend logging

The browser console receives structured log messages from the `FlowScope` logger. Messages are tagged by subsystem (`UPLOAD`, `API`, `FILTER`, `EXPORT`, `CONFORM`, `RENDER`, `VIEW`, `ANIM`) and include elapsed-time measurements for all API calls and render cycles.

To enable verbose debug-level logging in the browser console:

```js
FlowScope.debug = true;
```

### Performance notes

- The analytics layer computes activity transitions once per dashboard request and shares the result across all sub-computations (edges, handoffs, BPMN flowchart, sankey, rework), avoiding redundant passes over the event log.
- Edge and activity-stat payloads are built using vectorized pandas operations rather than row-by-row iteration.
- The health endpoint (`/api/health`) reports the number of logs currently held in memory.

## Notes

- The app keeps uploaded logs in process memory for the running backend instance.
- For large logs, start with stricter filter thresholds to keep rendering responsive.
- Some conformance metrics vary by `pm4py` version; the endpoint returns whichever metrics are supported by your installed version.
