# FlowScope Miner (Go Version)

A Go port of the FlowScope Miner process mining web application. This version reimplements the Python/FastAPI backend in pure Go with no external dependencies beyond the standard library and `github.com/google/uuid`.

## What's included

All core features from the Python version are ported:

- CSV event log import with auto-column detection
- Interactive filtering (time window, activities, attribute filters, frequency thresholds, case duration, top variants)
- Process map (DFG-style) computation with frequency and performance metrics
- Animated process playback with time-binned transition frames
- Actor-aware handoff analytics (actor-focused and activity-focused views)
- Swimlane diagram data
- Sankey flow diagram data
- Rework hotspot analysis
- Summary metrics (cases, events, activities, durations, rework ratio)
- Variant ranking
- Bottleneck detection
- Export to ZIP (with CSVs, JSON, Mermaid diagrams)
- Export to self-contained HTML report
- Mermaid diagram generation (process map, handoffs, swimlane, sankey, rework)
- Same frontend UI (shared `index.html`, `app.js`, `styles.css`)

## What's different from the Python version

- **No XES support**: XES parsing requires pm4py. This Go version supports CSV only.
- **No conformance checking**: Petri net discovery and token-based replay require pm4py. The endpoint returns a message directing users to the Python version.
- **No BPMN export**: BPMN model discovery requires pm4py.
- **Pure Go**: No Python, pandas, or pm4py dependency. Single binary deployment.

## Project layout

```
go version/
  main.go          - Entry point, HTTP server, router, middleware
  handlers.go      - API endpoint handlers, in-memory log store
  analytics.go     - CSV parsing, filtering, transitions, metrics, dashboard computation
  report.go        - HTML report builder, SVG process map renderer
  mermaid.go       - Mermaid diagram generators
  go.mod           - Go module definition
  frontend/        - Shared frontend files (identical to Python version)
    index.html
    app.js
    styles.css
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/logs/upload` | Upload CSV event log |
| POST | `/api/logs/suggest-mapping` | Auto-detect CSV column mapping |
| GET | `/api/logs` | List uploaded logs |
| GET | `/api/logs/{id}/overview` | Log overview with default filters |
| POST | `/api/logs/{id}/dashboard` | Filtered dashboard data |
| POST | `/api/logs/{id}/conformance` | Conformance check (stub) |
| POST | `/api/logs/{id}/animation` | Animation frames |
| POST | `/api/logs/{id}/export` | Export ZIP archive |
| POST | `/api/logs/{id}/export/html` | Export HTML report |

## Run locally

### Prerequisites

- Go 1.21+

### Build and run

```bash
cd "go version"
go mod tidy
go build -o flowscope .
./flowscope
```

Or run directly:

```bash
cd "go version"
go run .
```

The server starts on `http://127.0.0.1:8000` by default. Set the `PORT` environment variable to change the port.

### Open the dashboard

Navigate to [http://127.0.0.1:8000](http://127.0.0.1:8000)

## CSV format expectations

Same as the Python version. Default column mapping values:

- `case_id` / `case:concept:name`
- `activity` / `concept:name`
- `start_timestamp` / `time:start_timestamp`
- `stop_timestamp` / `time:end_timestamp`
- `actor` / `org:resource`

The upload form supports column mapping overrides and auto-suggestion.
