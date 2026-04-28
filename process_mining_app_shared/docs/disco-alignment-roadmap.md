# FlowScope Miner: Disco Alignment Roadmap

## Goal
Close the remaining gap with Fluxicon Disco by focusing on workflow, not just diagrams. The biggest product difference is still the speed of going from:

`map -> filter -> compare -> inspect cases -> export`

This roadmap splits that work across focused surfaces so the main dashboard does not become overloaded.

## Product Surfaces

### 1. Analysis Workspace
- Primary process map and handoff maps
- Visual simplification controls
- Map-driven filtering
- Active filter stack and filter history

### 2. Statistics and Cases Workspace
- Activity statistics
- Variant explorer
- Case list and trace inspector
- Start/end activity analysis
- Rework and bottleneck tables

### 3. Comparison Workspace
- Split current subset by attribute
- Side-by-side cohort maps
- Before/after filter comparison
- Saved comparison presets

### 4. Presentation and Export Workspace
- Animation playback modes
- Export package builder
- HTML report preview
- Mermaid / BPMN / image export options

## Phase Plan

### Phase 1: Filter Workflow Foundation
Status: in progress

Scope:
- Visible active filter stack
- Remove-one-filter interactions
- Map click shortcuts for activities and direct-follow paths
- Case-level activity filters
- Start/end activity filters
- Case-level direct-follow path filters

Why first:
- This is the highest-leverage Disco behavior gap.
- It improves every existing view immediately without forcing a full redesign.

### Phase 2: Statistics and Case Inspection
Scope:
- Dedicated statistics page instead of crowding the map page
- Variant-to-case drill-down
- Click a variant to filter the map and case list together
- Trace detail panel per case
- First/last activity panels

### Phase 3: Comparison and Cohorts
Scope:
- Split by actor, channel, payer, site, queue, or other attributes
- Side-by-side process maps with shared scaling
- Before vs after filter snapshots
- Saved analysis bookmarks

### Phase 4: Advanced Filtering
Scope:
- Follower filter modes: directly followed, eventually followed, never directly, never eventually
- Performance filters on waiting time, active time, case duration, and events per case
- Endpoint filters for incomplete cases and specific start/end combinations
- Actor-aware controls such as 4-eyes and handoff-specific filters

### Phase 5: Animation and Storytelling
Scope:
- Relative case time animation
- Actual log time animation
- Backlog / active cases timeline
- Animation presets for export and presentation

## Immediate Implementation Notes

### What now lives on the main page
- Map
- Basic filters
- Filter stack
- Map-driven quick filters

### What should move off the main page next
- Variant exploration
- Detailed statistics tables
- Case-by-case trace inspection
- Side-by-side cohort comparison

## Acceptance Criteria For Phase 1
- Users can click an activity in the process map and keep or exclude cases containing that activity.
- Users can click a path and keep or exclude cases containing that direct-follow relation.
- Users can click an activity and constrain case starts or case ends.
- Active filters are visible as a stack with one-click removal.
- Coverage feedback shows how much of the log remains after filtering.
