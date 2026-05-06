// ---------------------------------------------------------------------------
// Frontend controller
// ---------------------------------------------------------------------------
// This file is intentionally framework-free. The app keeps a small state object,
// talks to the FastAPI backend with fetch(), and renders all diagrams as SVG.
// The main flow is:
// 1. Upload or inspect a log.
// 2. Build the current filter payload from the UI.
// 3. Fetch dashboard + animation payloads.
// 4. Render metrics, tables, filter stack, and whichever diagram tab is active.

// ---------------------------------------------------------------------------
// Lightweight logger
// ---------------------------------------------------------------------------
// Writes structured messages to the browser console. Toggle verbose logging by
// setting FlowScope.debug = true in DevTools.
const FlowScope = {
  debug: false,
  _ts() {
    return new Date().toISOString().slice(11, 23);
  },
  info(tag, message, ...data) {
    console.log(
      `%c[${this._ts()}] ${tag}%c ${message}`,
      "color:#003399;font-weight:600",
      "color:inherit",
      ...data
    );
  },
  warn(tag, message, ...data) {
    console.warn(`[${this._ts()}] ${tag} ${message}`, ...data);
  },
  error(tag, message, ...data) {
    console.error(`[${this._ts()}] ${tag} ${message}`, ...data);
  },
  debug_log(tag, message, ...data) {
    if (this.debug) {
      console.debug(`[${this._ts()}] ${tag} ${message}`, ...data);
    }
  },
  /** Measure async operation. Returns { result, elapsedMs }. */
  async time(tag, label, asyncFn) {
    const t0 = performance.now();
    try {
      const result = await asyncFn();
      const elapsedMs = (performance.now() - t0).toFixed(1);
      this.info(tag, `${label} completed in ${elapsedMs} ms`);
      return result;
    } catch (err) {
      const elapsedMs = (performance.now() - t0).toFixed(1);
      this.error(tag, `${label} FAILED after ${elapsedMs} ms`, err);
      throw err;
    }
  },
};

// Central mutable UI state. Keeping this in one object makes view switches,
// filter changes, and animation frame updates predictable without a framework.
const state = {
  logId: null,
  projectId: null,
  projectName: null,
  activities: [],
  baseSummary: null,
  dashboard: null,
  columnMapping: null,
  informationalColumns: [],
  filterOnlyColumns: [],
  attributeFilterOptions: {},
  availableColumns: [],
  mode: "frequency",
  currentView: "process",
  mapZoom: 0.78,
  quickFilters: [],
  nextQuickFilterId: 1,
  mapSelection: null,
  animation: {
    payloads: {},
    frames: [],
    frameIndex: 0,
    maxEdgeCount: 0,
    overlayVisible: false,
    isPlaying: false,
    timerId: null,
  },
};

// Cached DOM references. This avoids repeated document lookups and also makes
// it easy to see which HTML ids are part of the JavaScript contract.
const els = {
  projectSelect: document.getElementById("project-select"),
  projectNameInput: document.getElementById("project-name-input"),
  createProjectBtn: document.getElementById("create-project-btn"),
  projectStatus: document.getElementById("project-status"),
  projectLogsSection: document.getElementById("project-logs-section"),
  projectLogsList: document.getElementById("project-logs-list"),
  uploadForm: document.getElementById("upload-form"),
  uploadStatus: document.getElementById("upload-status"),
  logFile: document.getElementById("log-file"),
  caseCol: document.getElementById("case-col"),
  activityCol: document.getElementById("activity-col"),
  startTimestampCol: document.getElementById("start-timestamp-col"),
  stopTimestampCol: document.getElementById("stop-timestamp-col"),
  actorCol: document.getElementById("actor-col"),
  suggestMapping: document.getElementById("suggest-mapping"),
  mappingStatus: document.getElementById("mapping-status"),
  informationalCols: document.getElementById("informational-cols"),
  filterOnlyCols: document.getElementById("filter-only-cols"),
  dashboard: document.getElementById("dashboard"),
  metrics: document.getElementById("metrics"),
  startTime: document.getElementById("start-time"),
  endTime: document.getElementById("end-time"),
  minActivityFrequency: document.getElementById("min-activity-frequency"),
  minEdgeFrequency: document.getElementById("min-edge-frequency"),
  variantTopK: document.getElementById("variant-top-k"),
  retainTopVariants: document.getElementById("retain-top-variants"),
  minCaseDuration: document.getElementById("min-case-duration"),
  maxCaseDuration: document.getElementById("max-case-duration"),
  includeActivities: document.getElementById("include-activities"),
  excludeActivities: document.getElementById("exclude-activities"),
  attributeFilters: document.getElementById("attribute-filters"),
  filterStack: document.getElementById("filter-stack"),
  filterStackSummary: document.getElementById("filter-stack-summary"),
  clearFilterStack: document.getElementById("clear-filter-stack"),
  applyFilters: document.getElementById("apply-filters"),
  resetFilters: document.getElementById("reset-filters"),
  runConformance: document.getElementById("run-conformance"),
  exportAnalysis: document.getElementById("export-analysis"),
  exportHtmlReport: document.getElementById("export-html-report"),
  conformanceOutput: document.getElementById("conformance-output"),
  processMap: document.getElementById("process-map"),
  processMapViewport: document.getElementById("process-map-viewport"),
  viewDescription: document.getElementById("view-description"),
  viewProcess: document.getElementById("view-process"),
  viewHandoffActor: document.getElementById("view-handoff-actor"),
  viewHandoffActivity: document.getElementById("view-handoff-activity"),
  viewSwimlane: document.getElementById("view-swimlane"),
  viewSankey: document.getElementById("view-sankey"),
  viewRework: document.getElementById("view-rework"),
  viewQueueHeatmap: document.getElementById("view-queue-heatmap"),
  viewReworkTreemap: document.getElementById("view-rework-treemap"),
  viewVariantBoxplot: document.getElementById("view-variant-boxplot"),
  edgesBody: document.getElementById("edges-body"),
  variantsBody: document.getElementById("variants-body"),
  bottlenecksBody: document.getElementById("bottlenecks-body"),
  activitiesBody: document.getElementById("activities-body"),
  reworkBody: document.getElementById("rework-body"),
  recommendationsList: document.getElementById("recommendations-list"),
  informationalBody: document.getElementById("informational-body"),
  modeFrequency: document.getElementById("mode-frequency"),
  modePerformance: document.getElementById("mode-performance"),
  toggleAnimation: document.getElementById("toggle-animation"),
  restartAnimation: document.getElementById("restart-animation"),
  stepBackAnimation: document.getElementById("step-back-animation"),
  stepForwardAnimation: document.getElementById("step-forward-animation"),
  animationSpeed: document.getElementById("animation-speed"),
  animationFrame: document.getElementById("animation-frame"),
  animationTime: document.getElementById("animation-time"),
  activityDetail: document.getElementById("activity-detail"),
  activityDetailValue: document.getElementById("activity-detail-value"),
  pathDetail: document.getElementById("path-detail"),
  pathDetailValue: document.getElementById("path-detail-value"),
  zoomOut: document.getElementById("zoom-out"),
  zoomReset: document.getElementById("zoom-reset"),
  zoomIn: document.getElementById("zoom-in"),
  zoomValue: document.getElementById("zoom-value"),
  processMapSummary: document.getElementById("process-map-summary"),
  mapSelectionPanel: document.getElementById("map-selection-panel"),
  mapSelectionTitle: document.getElementById("map-selection-title"),
  mapSelectionSubtitle: document.getElementById("map-selection-subtitle"),
  mapSelectionActions: document.getElementById("map-selection-actions"),
};

const SVG_NS = "http://www.w3.org/2000/svg";

// View descriptions are shown under the diagram controls and double as quick
// documentation for the analyst using the app.
const VIEW_DESCRIPTIONS = {
  process:
    "Stage-based activity map with start/end anchors, relative-case-time animation, and Disco-style detail sliders.",
  handoff_actor:
    "Actor-focused handoff graph showing work transfer between resources with the same staged layout and synchronized animation.",
  handoff_activity:
    "Activity-focused handoff graph highlighting transitions where actor changes occur, using the same staged layout and synchronized animation.",
  swimlane:
    "BPMN-style flowchart with normalized activities, start/end events, gateway-style branch points, and frequency-weighted variations.",
  sankey: "Sankey flow emphasizing dominant transition volume between activities.",
  rework: "Rework-focused view showing repeated activities and self-loop intensity.",
  queue_heatmap:
    "Queue age heatmap showing median waits by activity and time slice to surface bottleneck drift.",
  rework_treemap:
    "Treemap showing which repeated activities consume the most rework volume.",
  variant_boxplot:
    "Variant duration boxplot comparing cycle-time spread across dominant paths.",
};

// Keep diagram colors centralized so the process map, handoff maps, and
// animation overlays stay visually consistent.
const FLOW_COLORS = {
  edgeMarker: "#003399",
  anchorStroke: (alpha) => `rgba(0, 136, 161, ${alpha})`,
  backboneStroke: (alpha) => `rgba(10, 124, 193, ${alpha})`,
  secondaryStroke: (alpha) => `rgba(140, 163, 178, ${alpha})`,
  activeStroke: (alpha) => `rgba(10, 124, 193, ${alpha})`,
  caseBallFill: "#DE4702",
  caseBallStroke: "rgba(255, 255, 255, 0.3)",
  frequencyNodeLow: "#C5E7FC",
  frequencyNodeMid: "#50B7F6",
  frequencyNodeHigh: "#053E60",
  frequencyEdgeLow: "#8ACFF9",
  frequencyEdgeMid: "#0A7CC1",
  frequencyEdgeHigh: "#085D91",
  performanceNodeLow: "#CFE2EB",
  performanceNodeMid: "#70A7C3",
  performanceNodeHigh: "#19303C",
  performanceEdgeLow: "#A0C4D7",
  performanceEdgeMid: "#336179",
  performanceEdgeHigh: "#26495B",
};

function emptyAnimationPayload() {
  // The backend returns this shape even for views with no animation data. The
  // same default keeps disabled controls and empty states simple on first load.
  return {
    timeline_mode: "relative_case_start",
    normalized_case_start: true,
    frame_count: 0,
    frame_interval_seconds: 0,
    max_edge_count_per_frame: 0,
    max_total_transitions_per_frame: 0,
    frames: [],
  };
}

function detailControlContext(viewKey = state.currentView) {
  // Detail sliders say "activity/path" for process views and "actor/handoff"
  // for actor-focused handoff views.
  if (viewKey === "handoff_actor") {
    return {
      nodeSingular: "actor",
      nodePlural: "actors",
      edgeSingular: "handoff",
      edgePlural: "handoffs",
    };
  }
  if (viewKey === "handoff_activity") {
    return {
      nodeSingular: "activity",
      nodePlural: "activities",
      edgeSingular: "handoff",
      edgePlural: "handoffs",
    };
  }
  return {
    nodeSingular: "activity",
    nodePlural: "activities",
    edgeSingular: "path",
    edgePlural: "paths",
  };
}

function usesStructuredFlowView(viewKey = state.currentView) {
  return ["process", "handoff_actor", "handoff_activity", "swimlane"].includes(viewKey);
}

function viewSupportsAnimation(viewKey = state.currentView) {
  return ["process", "handoff_actor", "handoff_activity"].includes(viewKey);
}

function updateViewButtons() {
  // All diagram buttons share one state key. New views only need an element id,
  // a VIEW_DESCRIPTIONS entry, an availability check, and a render case.
  const viewButtons = [
    [els.viewProcess, "process"],
    [els.viewHandoffActor, "handoff_actor"],
    [els.viewHandoffActivity, "handoff_activity"],
    [els.viewSwimlane, "swimlane"],
    [els.viewSankey, "sankey"],
    [els.viewRework, "rework"],
    [els.viewQueueHeatmap, "queue_heatmap"],
    [els.viewReworkTreemap, "rework_treemap"],
    [els.viewVariantBoxplot, "variant_boxplot"],
  ];
  viewButtons.forEach(([button, viewKey]) => {
    if (!button) {
      return;
    }
    button.classList.toggle("active", state.currentView === viewKey);
  });
  if (els.viewDescription) {
    els.viewDescription.textContent = VIEW_DESCRIPTIONS[state.currentView] || "";
  }
  updateProcessDetailLabels();
}

function setStatus(message, isError = false) {
  els.uploadStatus.textContent = message;
  els.uploadStatus.style.color = isError ? "#003399" : "#000000";
}

function setMappingStatus(message, isError = false) {
  if (!els.mappingStatus) {
    return;
  }
  els.mappingStatus.textContent = message;
  els.mappingStatus.style.color = isError ? "#003399" : "#000000";
}

// ---------------------------------------------------------------------------
// Filter state and map-selection helpers
// ---------------------------------------------------------------------------
// The visible form controls and map-click shortcuts both compile into the same
// backend FilterSpec shape. Quick filters are kept in state.quickFilters so map
// interactions can be listed and removed from the Filter Stack.

function sanitizeColumnList(columns) {
  const seen = new Set();
  return (columns || [])
    .map((column) => String(column || "").trim())
    .filter((column) => {
      if (!column || seen.has(column)) {
        return false;
      }
      seen.add(column);
      return true;
    });
}

function uniqueStrings(values) {
  return sanitizeColumnList(values || []);
}

function defaultStartInputValue() {
  return toLocalDateInput(state.baseSummary?.start_time);
}

function defaultEndInputValue() {
  return toLocalDateInput(state.baseSummary?.end_time);
}

function quickFilterKey(filter) {
  // Used for duplicate detection. Two filters with the same semantic target
  // should not create duplicate chips or duplicate backend clauses.
  if (!filter) {
    return "";
  }
  if (filter.activity) {
    return `${filter.kind}|||${filter.activity}`;
  }
  if (filter.source || filter.target) {
    return `${filter.kind}|||${filter.source || ""}|||${filter.target || ""}`;
  }
  return `${filter.kind}`;
}

function quickFilterKindLabel(filter) {
  switch (filter.kind) {
    case "case_include_activity":
      return "Cases With Activity";
    case "case_exclude_activity":
      return "Exclude Activity";
    case "start_activity":
      return "Case Start";
    case "end_activity":
      return "Case End";
    case "direct_follow_include":
      return "Direct Path";
    case "direct_follow_exclude":
      return "Exclude Path";
    default:
      return "Quick Filter";
  }
}

function quickFilterValueLabel(filter) {
  if (filter.activity) {
    return filter.activity;
  }
  if (filter.source || filter.target) {
    return `${filter.source || "?"} -> ${filter.target || "?"}`;
  }
  return "Filter";
}

function buildQuickFilterPayloadParts() {
  // Convert UI-only quick-filter objects into the API payload fields expected
  // by backend.analytics.FilterSpec.
  const payload = {
    case_include_activities: [],
    case_exclude_activities: [],
    start_activities: [],
    end_activities: [],
    direct_follow_include: [],
    direct_follow_exclude: [],
  };

  state.quickFilters.forEach((filter) => {
    if (filter.kind === "case_include_activity" && filter.activity) {
      payload.case_include_activities.push(filter.activity);
    }
    if (filter.kind === "case_exclude_activity" && filter.activity) {
      payload.case_exclude_activities.push(filter.activity);
    }
    if (filter.kind === "start_activity" && filter.activity) {
      payload.start_activities.push(filter.activity);
    }
    if (filter.kind === "end_activity" && filter.activity) {
      payload.end_activities.push(filter.activity);
    }
    if (filter.kind === "direct_follow_include" && filter.source && filter.target) {
      payload.direct_follow_include.push({ source: filter.source, target: filter.target });
    }
    if (filter.kind === "direct_follow_exclude" && filter.source && filter.target) {
      payload.direct_follow_exclude.push({ source: filter.source, target: filter.target });
    }
  });

  payload.case_include_activities = uniqueStrings(payload.case_include_activities);
  payload.case_exclude_activities = uniqueStrings(payload.case_exclude_activities);
  payload.start_activities = uniqueStrings(payload.start_activities);
  payload.end_activities = uniqueStrings(payload.end_activities);
  return payload;
}

function addQuickFilter(filter) {
  // Return false instead of throwing when a map action would duplicate an
  // existing quick filter. The caller can then show a friendly status message.
  const candidate = {
    id: state.nextQuickFilterId,
    kind: String(filter.kind || "").trim(),
    activity: filter.activity ? String(filter.activity).trim() : null,
    source: filter.source ? String(filter.source).trim() : null,
    target: filter.target ? String(filter.target).trim() : null,
  };
  if (!candidate.kind) {
    return false;
  }
  const key = quickFilterKey(candidate);
  if (!key) {
    return false;
  }
  if (state.quickFilters.some((existing) => quickFilterKey(existing) === key)) {
    return false;
  }
  state.nextQuickFilterId += 1;
  state.quickFilters.push(candidate);
  return true;
}

function clearMultiSelect(selectEl) {
  if (!selectEl) {
    return;
  }
  Array.from(selectEl.options).forEach((option) => {
    option.selected = false;
  });
}

function clearMapSelection(rerender = false) {
  state.mapSelection = null;
  renderMapSelectionPanel();
  if (rerender && state.dashboard) {
    renderCurrentMap();
  }
}

function setMapSelection(selection) {
  // Re-rendering immediately keeps selected nodes/paths highlighted and updates
  // the action panel without waiting for a backend round trip.
  state.mapSelection = selection;
  renderMapSelectionPanel();
  if (state.dashboard) {
    renderCurrentMap();
  }
}

function activeFilterDescriptors() {
  // Build user-readable filter chips from both form controls and map-created
  // quick filters. The descriptors are display data; buildFilterPayload is the
  // authoritative API payload.
  const descriptors = [];

  if (els.startTime.value && els.startTime.value !== defaultStartInputValue()) {
    descriptors.push({
      id: "form:start_time",
      kindLabel: "Time Window",
      valueLabel: `Start >= ${els.startTime.value.replace("T", " ")}`,
    });
  }
  if (els.endTime.value && els.endTime.value !== defaultEndInputValue()) {
    descriptors.push({
      id: "form:end_time",
      kindLabel: "Time Window",
      valueLabel: `End <= ${els.endTime.value.replace("T", " ")}`,
    });
  }

  const minActivityFrequency = Math.max(Number(els.minActivityFrequency.value) || 1, 1);
  if (minActivityFrequency > 1) {
    descriptors.push({
      id: "form:min_activity_frequency",
      kindLabel: "Frequency Threshold",
      valueLabel: `Activities appearing at least ${formatNumber(minActivityFrequency)} times`,
    });
  }

  const minEdgeFrequency = Math.max(Number(els.minEdgeFrequency.value) || 1, 1);
  if (minEdgeFrequency > 1) {
    descriptors.push({
      id: "form:min_edge_frequency",
      kindLabel: "Frequency Threshold",
      valueLabel: `Paths appearing at least ${formatNumber(minEdgeFrequency)} times`,
    });
  }

  if (els.retainTopVariants.value) {
    descriptors.push({
      id: "form:retain_top_variants",
      kindLabel: "Variant Filter",
      valueLabel: `Keep top ${els.retainTopVariants.value} variants`,
    });
  }

  if (els.minCaseDuration.value) {
    descriptors.push({
      id: "form:min_case_duration",
      kindLabel: "Case Duration",
      valueLabel: `Minimum ${els.minCaseDuration.value} hours`,
    });
  }

  if (els.maxCaseDuration.value) {
    descriptors.push({
      id: "form:max_case_duration",
      kindLabel: "Case Duration",
      valueLabel: `Maximum ${els.maxCaseDuration.value} hours`,
    });
  }

  const includeActivities = selectedValues(els.includeActivities);
  if (includeActivities.length) {
    descriptors.push({
      id: "form:case_include_activities",
      kindLabel: "Cases With Activities",
      valueLabel: includeActivities.join(", "),
    });
  }

  const excludeActivities = selectedValues(els.excludeActivities);
  if (excludeActivities.length) {
    descriptors.push({
      id: "form:case_exclude_activities",
      kindLabel: "Exclude Cases With Activities",
      valueLabel: excludeActivities.join(", "),
    });
  }

  Object.entries(selectedAttributeFilters()).forEach(([column, values]) => {
    if (!values.length) {
      return;
    }
    descriptors.push({
      id: `form:attribute:${column}`,
      kindLabel: `Attribute ${column}`,
      valueLabel: values.join(", "),
    });
  });

  state.quickFilters.forEach((filter) => {
    descriptors.push({
      id: `quick:${filter.id}`,
      kindLabel: quickFilterKindLabel(filter),
      valueLabel: quickFilterValueLabel(filter),
    });
  });

  return descriptors;
}

function renderFilterStack() {
  if (!els.filterStack || !els.filterStackSummary) {
    return;
  }

  const descriptors = activeFilterDescriptors();
  const baseCases = Number(state.baseSummary?.total_cases || 0);
  const baseEvents = Number(state.baseSummary?.total_events || 0);
  const currentCases = Number(state.dashboard?.summary?.total_cases || 0);
  const currentEvents = Number(state.dashboard?.summary?.total_events || 0);

  if (!descriptors.length) {
    if (state.dashboard && state.baseSummary) {
      els.filterStackSummary.textContent =
        `Showing the full log: ${formatNumber(currentCases)} cases and ${formatNumber(currentEvents)} events.`;
    } else {
      els.filterStackSummary.textContent =
        "No active filters. Load a log or click the map to start narrowing the process.";
    }
  } else {
    // Show the "filter cost" against the originally loaded log so analysts can
    // tell whether a view represents the full population or a small slice.
    const casesPct = baseCases > 0 ? ((currentCases / baseCases) * 100).toFixed(1) : "0.0";
    const eventsPct = baseEvents > 0 ? ((currentEvents / baseEvents) * 100).toFixed(1) : "0.0";
    els.filterStackSummary.textContent =
      `${descriptors.length} active filters | ${casesPct}% of cases (${formatNumber(currentCases)} / ${formatNumber(baseCases)}) | ${eventsPct}% of events (${formatNumber(currentEvents)} / ${formatNumber(baseEvents)})`;
  }

  els.filterStack.innerHTML = "";
  descriptors.forEach((descriptor) => {
    const card = document.createElement("article");
    card.className = "filter-chip";

    const head = document.createElement("div");
    head.className = "filter-chip-head";

    const copy = document.createElement("div");
    const kind = document.createElement("div");
    kind.className = "filter-chip-kind";
    kind.textContent = descriptor.kindLabel;
    const value = document.createElement("div");
    value.className = "filter-chip-value";
    value.textContent = descriptor.valueLabel;
    copy.appendChild(kind);
    copy.appendChild(value);

    const button = document.createElement("button");
    button.className = "btn-ghost";
    button.type = "button";
    button.dataset.filterId = descriptor.id;
    button.textContent = "Remove";

    head.appendChild(copy);
    head.appendChild(button);
    card.appendChild(head);
    els.filterStack.appendChild(card);
  });
}

function mapSelectionActionButtons(selection) {
  // Only process/activity views can safely emit process filters today. Actor
  // shortcuts need a separate actor filter contract, so the UI currently marks
  // actor selection as informational.
  if (!selection) {
    return [];
  }
  if (selection.type === "activity") {
    return [
      { label: "Keep Cases With Activity", filter: { kind: "case_include_activity", activity: selection.value } },
      { label: "Exclude Cases With Activity", filter: { kind: "case_exclude_activity", activity: selection.value } },
      { label: "Keep Case Starts Here", filter: { kind: "start_activity", activity: selection.value } },
      { label: "Keep Case Ends Here", filter: { kind: "end_activity", activity: selection.value } },
    ];
  }
  if (selection.type === "path") {
    return [
      {
        label: "Keep Direct Path",
        filter: { kind: "direct_follow_include", source: selection.source, target: selection.target },
      },
      {
        label: "Exclude Direct Path",
        filter: { kind: "direct_follow_exclude", source: selection.source, target: selection.target },
      },
    ];
  }
  return [];
}

function renderMapSelectionPanel() {
  if (!els.mapSelectionPanel || !els.mapSelectionTitle || !els.mapSelectionActions) {
    return;
  }

  const selection = state.mapSelection;
  const selectionVisible = ["process", "handoff_actor", "handoff_activity", "swimlane"].includes(
    state.currentView
  );
  if (!selection || !selectionVisible) {
    els.mapSelectionPanel.classList.add("hidden");
    els.mapSelectionTitle.textContent = "No map item selected";
    els.mapSelectionSubtitle.textContent = "Click an activity or path to add a focused filter.";
    els.mapSelectionActions.innerHTML = "";
    return;
  }

  els.mapSelectionPanel.classList.remove("hidden");
  if (selection.type === "activity") {
    els.mapSelectionTitle.textContent = `Activity: ${selection.value}`;
    els.mapSelectionSubtitle.textContent =
      "Use this selection to keep, exclude, or constrain case start/end behavior.";
  } else if (selection.type === "path") {
    els.mapSelectionTitle.textContent = `Path: ${selection.source} -> ${selection.target}`;
    els.mapSelectionSubtitle.textContent =
      "Use this selection to keep or exclude cases containing this direct-follow path.";
  } else if (selection.type === "actor") {
    els.mapSelectionTitle.textContent = `Actor: ${selection.value}`;
    els.mapSelectionSubtitle.textContent =
      "Actor-specific shortcuts land in the next slice. The current build focuses on activity and path filters.";
  } else {
    els.mapSelectionTitle.textContent = "Map selection";
    els.mapSelectionSubtitle.textContent = "Use the current selection to add a focused filter.";
  }

  const actions = mapSelectionActionButtons(selection);
  els.mapSelectionActions.innerHTML = "";
  actions.forEach((action, index) => {
    const button = document.createElement("button");
    button.className = index === 0 ? "btn-primary" : "btn-ghost";
    button.type = "button";
    button.dataset.selectionAction = "add-filter";
    button.dataset.filterKind = action.filter.kind || "";
    button.dataset.filterActivity = action.filter.activity || "";
    button.dataset.filterSource = action.filter.source || "";
    button.dataset.filterTarget = action.filter.target || "";
    button.textContent = action.label;
    els.mapSelectionActions.appendChild(button);
  });
  const clearButton = document.createElement("button");
  clearButton.className = "btn-ghost";
  clearButton.type = "button";
  clearButton.dataset.selectionAction = "clear";
  clearButton.textContent = "Clear Selection";
  els.mapSelectionActions.appendChild(clearButton);
}

async function removeFilterById(filterId) {
  // Filter chips remove either a quick filter from state or reset a matching
  // form control, then reload the dashboard if a log is active.
  if (!filterId) {
    return;
  }

  if (filterId.startsWith("quick:")) {
    const quickId = Number(filterId.slice(6));
    state.quickFilters = state.quickFilters.filter((filter) => filter.id !== quickId);
  } else if (filterId === "form:start_time") {
    els.startTime.value = defaultStartInputValue();
  } else if (filterId === "form:end_time") {
    els.endTime.value = defaultEndInputValue();
  } else if (filterId === "form:min_activity_frequency") {
    els.minActivityFrequency.value = "1";
  } else if (filterId === "form:min_edge_frequency") {
    els.minEdgeFrequency.value = "1";
  } else if (filterId === "form:retain_top_variants") {
    els.retainTopVariants.value = "";
  } else if (filterId === "form:min_case_duration") {
    els.minCaseDuration.value = "";
  } else if (filterId === "form:max_case_duration") {
    els.maxCaseDuration.value = "";
  } else if (filterId === "form:case_include_activities") {
    clearMultiSelect(els.includeActivities);
  } else if (filterId === "form:case_exclude_activities") {
    clearMultiSelect(els.excludeActivities);
  } else if (filterId.startsWith("form:attribute:")) {
    const column = filterId.slice("form:attribute:".length);
    const control = Array.from(
      els.attributeFilters?.querySelectorAll("select[data-column]") || []
    ).find((candidate) => candidate.dataset.column === column);
    if (control) {
      clearMultiSelect(control);
    }
  }

  renderFilterStack();
  if (state.logId) {
    await loadDashboard();
    els.conformanceOutput.textContent = "";
  }
}

async function applyMapSelectionFilter(filter) {
  // Applying a map filter is a full dashboard reload because the backend must
  // recompute variants, bottlenecks, animation frames, and all diagram views.
  if (!addQuickFilter(filter)) {
    setStatus("That filter is already active.");
    return;
  }

  clearMapSelection();
  renderFilterStack();
  if (state.logId) {
    await loadDashboard();
    els.conformanceOutput.textContent = "";
  }
}

// ---------------------------------------------------------------------------
// Upload mapping and form serialization
// ---------------------------------------------------------------------------
// CSV uploads can be mapped manually or by backend suggestions. The form also
// lets analysts identify auxiliary columns that should be profiled or exposed
// as dynamic filters without becoming part of the process semantics.

function populateSingleColumnSelect(selectEl, columns, suggestedValue, emptyLabel) {
  if (!selectEl) {
    return;
  }
  const previous = selectEl.value;
  const values = sanitizeColumnList(columns);
  const fragment = document.createDocumentFragment();

  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = emptyLabel;
  fragment.appendChild(emptyOption);

  values.forEach((column) => {
    const option = document.createElement("option");
    option.value = column;
    option.textContent = column;
    fragment.appendChild(option);
  });

  selectEl.innerHTML = "";
  selectEl.appendChild(fragment);

  const nextValue =
    (suggestedValue && values.includes(suggestedValue) && suggestedValue) ||
    (previous && values.includes(previous) && previous) ||
    "";
  selectEl.value = nextValue;
}

function populateMultiColumnSelect(selectEl, columns, selectedValuesList) {
  if (!selectEl) {
    return;
  }

  const previous = new Set(selectedValues(selectEl));
  const values = sanitizeColumnList(columns);
  const selectedSet = new Set(sanitizeColumnList(selectedValuesList));
  const fragment = document.createDocumentFragment();

  values.forEach((column) => {
    const option = document.createElement("option");
    option.value = column;
    option.textContent = column;
    if (selectedSet.has(column) || previous.has(column)) {
      option.selected = true;
    }
    fragment.appendChild(option);
  });

  selectEl.innerHTML = "";
  selectEl.appendChild(fragment);
}

function applyMappingSuggestion(mappingPayload) {
  // Core mapping columns are excluded from the auxiliary lists so a column does
  // not appear both as "activity" and as an informational/filter-only column.
  const columns = sanitizeColumnList(mappingPayload?.columns || []);
  const suggestions = mappingPayload?.suggestions || {};
  state.availableColumns = columns;

  populateSingleColumnSelect(els.caseCol, columns, suggestions.case_id_col, "Auto-detect");
  populateSingleColumnSelect(
    els.activityCol,
    columns,
    suggestions.activity_col,
    "Auto-detect"
  );
  populateSingleColumnSelect(
    els.startTimestampCol,
    columns,
    suggestions.start_timestamp_col,
    "Auto-detect"
  );
  populateSingleColumnSelect(
    els.stopTimestampCol,
    columns,
    suggestions.stop_timestamp_col,
    "None / Auto-detect"
  );
  populateSingleColumnSelect(
    els.actorCol,
    columns,
    suggestions.actor_col,
    "Auto-detect / none"
  );

  const coreColumns = new Set(
    [
      suggestions.case_id_col,
      suggestions.activity_col,
      suggestions.start_timestamp_col,
      suggestions.stop_timestamp_col,
      suggestions.actor_col,
    ].filter(Boolean)
  );
  const auxiliaryColumns = columns.filter((column) => !coreColumns.has(column));
  populateMultiColumnSelect(
    els.informationalCols,
    auxiliaryColumns,
    mappingPayload?.suggested_informational_columns || []
  );
  populateMultiColumnSelect(
    els.filterOnlyCols,
    auxiliaryColumns,
    mappingPayload?.suggested_filter_only_columns || []
  );

  const confidence = mappingPayload?.confidence || {};
  const confidenceParts = [
    confidence.case_id_col !== undefined
      ? `case ${(Number(confidence.case_id_col) * 100).toFixed(0)}%`
      : null,
    confidence.activity_col !== undefined
      ? `activity ${(Number(confidence.activity_col) * 100).toFixed(0)}%`
      : null,
    confidence.start_timestamp_col !== undefined
      ? `start ${(Number(confidence.start_timestamp_col) * 100).toFixed(0)}%`
      : null,
    confidence.actor_col !== undefined
      ? `actor ${(Number(confidence.actor_col) * 100).toFixed(0)}%`
      : null,
  ].filter(Boolean);
  setMappingStatus(
    confidenceParts.length
      ? `Suggested mapping confidence: ${confidenceParts.join(" | ")}`
      : "Mapping suggestions applied."
  );
}

function resetMappingSelectors() {
  state.availableColumns = [];
  populateSingleColumnSelect(els.caseCol, [], "", "Auto-detect");
  populateSingleColumnSelect(els.activityCol, [], "", "Auto-detect");
  populateSingleColumnSelect(els.startTimestampCol, [], "", "Auto-detect");
  populateSingleColumnSelect(els.stopTimestampCol, [], "", "None / Auto-detect");
  populateSingleColumnSelect(els.actorCol, [], "", "Auto-detect / none");
  populateMultiColumnSelect(els.informationalCols, [], []);
  populateMultiColumnSelect(els.filterOnlyCols, [], []);
}

// ---------------------------------------------------------------------------
// Formatting and primitive UI utilities
// ---------------------------------------------------------------------------

function formatNumber(value) {
  return new Intl.NumberFormat().format(value ?? 0);
}

function formatPct(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function hexToRgb(hex) {
  const clean = String(hex || "").replace("#", "");
  const value = parseInt(clean.length === 3
    ? clean.split("").map((char) => char + char).join("")
    : clean, 16);
  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255,
  };
}

function mixColor(startHex, endHex, amount) {
  const t = clamp(Number(amount) || 0, 0, 1);
  const start = hexToRgb(startHex);
  const end = hexToRgb(endHex);
  const r = Math.round(start.r + (end.r - start.r) * t);
  const g = Math.round(start.g + (end.g - start.g) * t);
  const b = Math.round(start.b + (end.b - start.b) * t);
  return `rgb(${r}, ${g}, ${b})`;
}

function twoStopHeat(lowHex, midHex, highHex, amount) {
  const t = clamp(Number(amount) || 0, 0, 1);
  if (t <= 0.55) {
    return mixColor(lowHex, midHex, t / 0.55);
  }
  return mixColor(midHex, highHex, (t - 0.55) / 0.45);
}

function visualStrength(value, maxValue, floor = 0.05) {
  const max = Math.max(Number(maxValue || 0), 0);
  if (max <= 0) {
    return 0;
  }
  return Math.max(Math.sqrt(Math.max(Number(value || 0), 0) / max), floor);
}

function trimMetric(value, decimals = 1) {
  const rounded = Number(value).toFixed(decimals);
  return rounded.replace(/\.0$/, "");
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return "-";
  }

  const totalSeconds = Number(seconds);
  if (!Number.isFinite(totalSeconds)) {
    return "-";
  }

  if (totalSeconds <= 1) {
    return "instant";
  }

  if (totalSeconds < 60) {
    return `${Math.round(totalSeconds)} secs`;
  }

  const totalMinutes = totalSeconds / 60;
  if (totalMinutes < 120) {
    return `${trimMetric(totalMinutes, totalMinutes < 10 ? 1 : 0)} mins`;
  }

  const totalHours = totalMinutes / 60;
  if (totalHours < 72) {
    return `${trimMetric(totalHours)} hrs`;
  }

  const totalDays = totalHours / 24;
  if (totalDays < 14) {
    return `${trimMetric(totalDays)} d`;
  }

  const totalWeeks = totalDays / 7;
  if (totalWeeks < 8) {
    return `${trimMetric(totalWeeks)} wks`;
  }

  const totalMonths = totalDays / 30.4375;
  if (totalMonths < 24) {
    return `${trimMetric(totalMonths)} mths`;
  }

  const totalYears = totalDays / 365.25;
  return `${trimMetric(totalYears)} yrs`;
}

function formatDateTime(isoValue) {
  if (!isoValue) {
    return "-";
  }

  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleString();
}

function toLocalDateInput(isoValue) {
  if (!isoValue) {
    return "";
  }

  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const timezoneOffset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16);
}

function fromLocalDateInput(value) {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return date.toISOString();
}

function selectedValues(selectEl) {
  return Array.from(selectEl.selectedOptions).map((option) => option.value);
}

function selectedAttributeFilters() {
  // Dynamic filter controls are rendered from filter-only columns selected at
  // import time. Their selected values become an attribute_filters object.
  const payload = {};
  if (!els.attributeFilters) {
    return payload;
  }

  const controls = Array.from(els.attributeFilters.querySelectorAll("select[data-column]"));
  controls.forEach((control) => {
    const column = control.dataset.column;
    if (!column) {
      return;
    }
    const values = selectedValues(control);
    if (values.length) {
      payload[column] = values;
    }
  });
  return payload;
}

function renderAttributeFilterControls(columns, optionsByColumn) {
  if (!els.attributeFilters) {
    return;
  }

  const selectedBefore = selectedAttributeFilters();
  els.attributeFilters.innerHTML = "";

  if (!columns.length) {
    return;
  }

  columns.forEach((column) => {
    const label = document.createElement("label");
    label.textContent = `Filter ${column} (optional)`;

    const select = document.createElement("select");
    select.multiple = true;
    select.dataset.column = column;

    const options = optionsByColumn[column] || [];
    options.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      if ((selectedBefore[column] || []).includes(value)) {
        option.selected = true;
      }
      select.appendChild(option);
    });

    label.appendChild(select);
    els.attributeFilters.appendChild(label);
  });
}

function parseOptionalNumber(value) {
  if (value === "" || value === null || value === undefined) {
    return null;
  }

  const parsed = Number(value);
  if (Number.isNaN(parsed)) {
    return null;
  }

  return parsed;
}

function buildFilterPayload() {
  // The backend expects case-preserving activity filters. The older
  // include_activities/exclude_activities fields remain empty so the app does
  // not accidentally remove individual events and create artificial paths.
  const quick = buildQuickFilterPayloadParts();
  const defaultStart = defaultStartInputValue();
  const defaultEnd = defaultEndInputValue();

  return {
    start_time:
      els.startTime.value && els.startTime.value !== defaultStart
        ? fromLocalDateInput(els.startTime.value)
        : null,
    end_time:
      els.endTime.value && els.endTime.value !== defaultEnd
        ? fromLocalDateInput(els.endTime.value)
        : null,
    include_activities: [],
    exclude_activities: [],
    case_include_activities: uniqueStrings([
      ...selectedValues(els.includeActivities),
      ...quick.case_include_activities,
    ]),
    case_exclude_activities: uniqueStrings([
      ...selectedValues(els.excludeActivities),
      ...quick.case_exclude_activities,
    ]),
    start_activities: uniqueStrings(quick.start_activities),
    end_activities: uniqueStrings(quick.end_activities),
    direct_follow_include: quick.direct_follow_include,
    direct_follow_exclude: quick.direct_follow_exclude,
    attribute_filters: selectedAttributeFilters(),
    min_activity_frequency: Math.max(parseInt(els.minActivityFrequency.value, 10) || 1, 1),
    min_edge_frequency: Math.max(parseInt(els.minEdgeFrequency.value, 10) || 1, 1),
    variant_top_k: Math.max(parseInt(els.variantTopK.value, 10) || 20, 1),
    retain_top_variants: parseOptionalNumber(els.retainTopVariants.value),
    min_case_duration_hours: parseOptionalNumber(els.minCaseDuration.value),
    max_case_duration_hours: parseOptionalNumber(els.maxCaseDuration.value),
  };
}

function populateActivityFilters(activities) {
  const includeFragment = document.createDocumentFragment();
  const excludeFragment = document.createDocumentFragment();

  activities.forEach((activity) => {
    const includeOption = document.createElement("option");
    includeOption.value = activity;
    includeOption.textContent = activity;
    includeFragment.appendChild(includeOption);

    const excludeOption = document.createElement("option");
    excludeOption.value = activity;
    excludeOption.textContent = activity;
    excludeFragment.appendChild(excludeOption);
  });

  els.includeActivities.innerHTML = "";
  els.excludeActivities.innerHTML = "";
  els.includeActivities.appendChild(includeFragment);
  els.excludeActivities.appendChild(excludeFragment);
}

function renderMetrics(summary) {
  const metrics = [
    { label: "Cases", value: formatNumber(summary.total_cases) },
    { label: "Events", value: formatNumber(summary.total_events) },
    { label: "Activities", value: formatNumber(summary.activities) },
    {
      label: "Median Case Duration",
      value: `${Number(summary.median_case_duration_hours || 0).toFixed(2)}h`,
    },
    {
      label: "Average Case Duration",
      value: `${Number(summary.avg_case_duration_hours || 0).toFixed(2)}h`,
    },
    {
      label: "Median Events / Case",
      value: Number(summary.median_events_per_case || 0).toFixed(2),
    },
    {
      label: "Rework Case Ratio",
      value: formatPct(summary.rework_case_ratio),
    },
    {
      label: "Time Range",
      value:
        summary.start_time && summary.end_time
          ? `${new Date(summary.start_time).toLocaleDateString()} - ${new Date(summary.end_time).toLocaleDateString()}`
          : "-",
    },
  ];

  els.metrics.innerHTML = metrics
    .map(
      (metric) => `
        <article class="metric">
          <div class="label">${metric.label}</div>
          <div class="value">${metric.value}</div>
        </article>
      `
    )
    .join("");
}

// ---------------------------------------------------------------------------
// SVG helpers and animation state helpers
// ---------------------------------------------------------------------------

function svgElement(tag, attrs = {}) {
  const element = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => {
    element.setAttribute(key, String(value));
  });
  return element;
}

function renderEmptyMap(message) {
  els.processMap.innerHTML = "";
  els.processMap.setAttribute("viewBox", "0 0 1200 760");
  els.processMap.style.aspectRatio = "1200 / 760";
  const text = svgElement("text", {
    x: 600,
    y: 380,
    "text-anchor": "middle",
    fill: "#000000",
    "font-size": 28,
    "font-family": "IBM Plex Mono, monospace",
  });
  text.textContent = message;
  els.processMap.appendChild(text);
  applyMapZoom();
}

function currentAnimationFrameData() {
  // Animation is drawn by re-rendering the base SVG with a transient overlay.
  // If overlayVisible is false, static diagrams stay clean with no case dots.
  if (!state.animation.overlayVisible || !state.animation.frames.length) {
    return null;
  }

  const frame = state.animation.frames[state.animation.frameIndex];
  if (!frame) {
    return null;
  }

  const edgeCounts = new Map();
  (frame.edges || []).forEach((edge) => {
    edgeCounts.set(`${edge.source}|||${edge.target}`, Number(edge.count || 0));
  });

  return {
    frame,
    edgeCounts,
    maxEdgeCount: Math.max(state.animation.maxEdgeCount || 0, 1),
  };
}

function currentAnimationEdgeKeys() {
  const activeFrame = currentAnimationFrameData();
  if (!activeFrame) {
    return new Set();
  }
  return new Set(activeFrame.edgeCounts.keys());
}

function quadraticBezierPoint(t, x0, y0, cx, cy, x1, y1) {
  const mt = 1 - t;
  const x = mt * mt * x0 + 2 * mt * t * cx + t * t * x1;
  const y = mt * mt * y0 + 2 * mt * t * cy + t * t * y1;
  return { x, y };
}

function cubicBezierPoint(t, x0, y0, cx1, cy1, cx2, cy2, x1, y1) {
  const mt = 1 - t;
  const x =
    mt * mt * mt * x0 +
    3 * mt * mt * t * cx1 +
    3 * mt * t * t * cx2 +
    t * t * t * x1;
  const y =
    mt * mt * mt * y0 +
    3 * mt * mt * t * cy1 +
    3 * mt * t * t * cy2 +
    t * t * t * y1;
  return { x, y };
}

// Linearly interpolate along an orthogonal polyline for animation dots.
function waypointPoint(t, waypoints) {
  if (waypoints.length < 2) return waypoints[0] || { x: 0, y: 0 };
  let totalLen = 0;
  const segLens = [];
  for (let i = 1; i < waypoints.length; i++) {
    const dx = waypoints[i].x - waypoints[i - 1].x;
    const dy = waypoints[i].y - waypoints[i - 1].y;
    const len = Math.sqrt(dx * dx + dy * dy);
    segLens.push(len);
    totalLen += len;
  }
  if (totalLen === 0) return waypoints[0];
  const tgt = t * totalLen;
  let cum = 0;
  for (let i = 0; i < segLens.length; i++) {
    if (tgt <= cum + segLens[i] + 0.001) {
      const segT = segLens[i] > 0 ? Math.min((tgt - cum) / segLens[i], 1) : 0;
      return {
        x: waypoints[i].x + segT * (waypoints[i + 1].x - waypoints[i].x),
        y: waypoints[i].y + segT * (waypoints[i + 1].y - waypoints[i].y),
      };
    }
    cum += segLens[i];
  }
  return waypoints[waypoints.length - 1];
}

// Like waypointPoint but also returns the unit tangent (tx, ty) of the segment
// containing parameter t. Used to compute outward perpendicular offsets for labels.
function waypointMidTangent(t, waypoints) {
  if (waypoints.length < 2) return { x: (waypoints[0] || { x: 0 }).x, y: (waypoints[0] || { y: 0 }).y, tx: 0, ty: 1 };
  let totalLen = 0;
  const segLens = [];
  for (let i = 1; i < waypoints.length; i++) {
    const dx = waypoints[i].x - waypoints[i - 1].x;
    const dy = waypoints[i].y - waypoints[i - 1].y;
    segLens.push(Math.sqrt(dx * dx + dy * dy));
    totalLen += segLens[segLens.length - 1];
  }
  if (totalLen === 0) return { x: waypoints[0].x, y: waypoints[0].y, tx: 0, ty: 1 };
  const tgt = t * totalLen;
  let cum = 0;
  for (let i = 0; i < segLens.length; i++) {
    if (tgt <= cum + segLens[i] + 0.001) {
      const len = segLens[i] || 1;
      const segT = len > 0 ? Math.min((tgt - cum) / len, 1) : 0;
      const dx = waypoints[i + 1].x - waypoints[i].x;
      const dy = waypoints[i + 1].y - waypoints[i].y;
      return { x: waypoints[i].x + segT * dx, y: waypoints[i].y + segT * dy, tx: dx / len, ty: dy / len };
    }
    cum += segLens[i];
  }
  const last = waypoints.length - 1;
  const dx = waypoints[last].x - waypoints[last - 1].x;
  const dy = waypoints[last].y - waypoints[last - 1].y;
  const len = segLens[segLens.length - 1] || 1;
  return { x: waypoints[last].x, y: waypoints[last].y, tx: dx / len, ty: dy / len };
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function processEdgeKey(source, target) {
  return `${source}|||${target}`;
}

function isSelectedMapActivity(activityId, viewKey = state.currentView) {
  return (
    state.mapSelection?.type === "activity" &&
    state.mapSelection?.view === viewKey &&
    state.mapSelection?.value === String(activityId)
  );
}

function isSelectedMapPath(source, target, viewKey = state.currentView) {
  return (
    state.mapSelection?.type === "path" &&
    state.mapSelection?.view === viewKey &&
    state.mapSelection?.source === String(source) &&
    state.mapSelection?.target === String(target)
  );
}

function isSelectedMapActor(actorId) {
  return (
    state.mapSelection?.type === "actor" &&
    state.mapSelection?.view === "handoff_actor" &&
    state.mapSelection?.value === String(actorId)
  );
}

function truncateProcessLabel(label, maxChars = 18) {
  const text = String(label || "");
  if (text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, Math.max(maxChars - 3, 1))}...`;
}

// Wraps an activity label into lines that fit within nodeWidth at the given fontSize.
// Breaks on word boundaries; falls back to character-level hyphenation for long single words.
function wrapActivityLabel(text, nodeWidth, fontSize) {
  const avgCharW = fontSize * 0.58;
  const maxLineW = nodeWidth - 28;
  const maxChars = Math.max(Math.floor(maxLineW / avgCharW), 4);
  if (text.length <= maxChars) return [text];
  const words = text.split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    if (word.length > maxChars) {
      if (line) { lines.push(line); line = ""; }
      let rem = word;
      while (rem.length > maxChars) {
        lines.push(rem.slice(0, maxChars - 1) + "-");
        rem = rem.slice(maxChars - 1);
      }
      line = rem;
      continue;
    }
    const test = line ? line + " " + word : word;
    if (test.length > maxChars && line) {
      lines.push(line);
      line = word;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);
  return lines.slice(0, 4);
}

function currentProcessDetailSettings() {
  return {
    activityPercent: clamp(Number(els.activityDetail?.value || 100), 0, 100),
    pathPercent: clamp(Number(els.pathDetail?.value || 50), 0, 100),
  };
}

function updateProcessDetailLabels() {
  const context = detailControlContext();
  const { activityPercent, pathPercent } = currentProcessDetailSettings();
  if (els.activityDetailValue) {
    els.activityDetailValue.textContent = `${activityPercent}% of ${context.nodeSingular} volume`;
  }
  if (els.pathDetailValue) {
    els.pathDetailValue.textContent = `${pathPercent}% of ${context.edgeSingular} volume`;
  }
}

function setProcessMapSummary(message) {
  if (els.processMapSummary) {
    els.processMapSummary.textContent = message || "";
  }
}

function normalizeAnimationPayloadMap(animationPayloads) {
  // Newer backend responses contain { views: { process, handoff_actor, ... } }.
  // Older responses may be a single process payload, so normalize both shapes.
  const base =
    animationPayloads?.views ||
    (animationPayloads?.frames ? { process: animationPayloads } : animationPayloads) ||
    {};

  return {
    process: base.process || emptyAnimationPayload(),
    handoff_actor: base.handoff_actor || emptyAnimationPayload(),
    handoff_activity: base.handoff_activity || emptyAnimationPayload(),
  };
}

function currentAnimationPayload() {
  return state.animation.payloads[state.currentView] || emptyAnimationPayload();
}

function syncActiveAnimationView(resetFrame = false) {
  // Switching between process/handoff views swaps the active frame list while
  // keeping the frame index in range.
  const payload = currentAnimationPayload();
  state.animation.frames = payload.frames || [];
  state.animation.maxEdgeCount = Number(payload.max_edge_count_per_frame || 0);

  const frameCount = state.animation.frames.length;
  if (resetFrame) {
    state.animation.frameIndex = 0;
  } else if (frameCount > 0) {
    state.animation.frameIndex = Math.max(
      0,
      Math.min(state.animation.frameIndex, frameCount - 1)
    );
  } else {
    state.animation.frameIndex = 0;
  }

  els.animationFrame.min = "0";
  els.animationFrame.max = String(Math.max(frameCount - 1, 0));
  els.animationFrame.value = String(Math.min(state.animation.frameIndex, Math.max(frameCount - 1, 0)));
}

function formatTimelineOffset(seconds) {
  const safeSeconds = Math.max(Number(seconds || 0), 0);
  return `T+${formatDuration(safeSeconds)}`;
}

const DEFAULT_MAP_ZOOM = 0.78;

function clampMapZoom(value) {
  return clamp(Number(value) || DEFAULT_MAP_ZOOM, 0.2, 2.4);
}

function updateMapZoomControls() {
  if (els.zoomValue) {
    els.zoomValue.textContent = `${Math.round(state.mapZoom * 100)}%`;
  }
  const animPlaying = state.animation.isPlaying;
  const fullyDisabled = !state.dashboard;
  [els.zoomOut, els.zoomReset, els.zoomIn].forEach((btn) => {
    if (!btn) return;
    btn.disabled = fullyDisabled;
    btn.classList.toggle("zoom-disabled", !fullyDisabled && animPlaying);
  });
}

function applyMapZoom() {
  // Zoom is handled by scaling the SVG element inside a scrollable viewport.
  // Animations disable zoom because they need fixed geometry while frames move.
  if (!els.processMap) {
    return;
  }
  state.mapZoom = clampMapZoom(state.mapZoom);
  const zoomPercent = state.mapZoom * 100;
  els.processMap.style.width = `${zoomPercent}%`;
  els.processMap.style.minWidth = `${zoomPercent}%`;
  els.processMap.style.height = "auto";
  updateMapZoomControls();
}

// ---------------------------------------------------------------------------
// Process-map simplification and layout
// ---------------------------------------------------------------------------
// The process maps can get dense quickly. The next group of functions keeps the
// dominant backbone visible while using activity/path detail sliders to reduce
// visual complexity and then lays out nodes in staged rows similar to Disco.

function topCoverageSet(items, scoreFn, percent, idFn) {
  // Keep enough top-ranked items to cover the requested percentage of volume.
  // The highest-volume item is always retained so a slider at 0 still has an
  // anchor when possible.
  const sorted = [...items].sort((a, b) => Number(scoreFn(b) || 0) - Number(scoreFn(a) || 0));
  if (!sorted.length) {
    return new Set();
  }

  const total = sorted.reduce((sum, item) => sum + Math.max(Number(scoreFn(item) || 0), 0), 0);
  if (percent >= 100 || total <= 0) {
    return new Set(sorted.map((item) => idFn(item)));
  }

  const threshold = total * (percent / 100);
  const keep = new Set();
  let running = 0;
  sorted.forEach((item, index) => {
    if (index === 0 || running < threshold) {
      keep.add(idFn(item));
      running += Math.max(Number(scoreFn(item) || 0), 0);
    }
  });
  return keep;
}

function buildDominantBackbone(nodes, edges, outgoingBySource, nodeMap) {
  // Greedily follow the strongest outgoing path from the most likely start
  // activity. This creates a stable "spine" that remains visible as sliders
  // reduce detail.
  if (!nodes.length || !edges.length) {
    return { nodeIds: new Set(), edgeKeys: new Set() };
  }

  const startCandidates = [...nodes].sort(
    (a, b) =>
      Number(b.start_count || 0) - Number(a.start_count || 0) ||
      Number(b.frequency || 0) - Number(a.frequency || 0)
  );
  let currentId = String(startCandidates[0]?.id || edges[0]?.source || "");
  const nodeIds = new Set(currentId ? [currentId] : []);
  const edgeKeys = new Set();
  const visited = new Set();

  for (let step = 0; step < nodes.length + 3 && currentId; step += 1) {
    if (visited.has(currentId)) {
      break;
    }
    visited.add(currentId);
    const candidates = [...(outgoingBySource.get(currentId) || [])].filter(
      (edge) => !edgeKeys.has(processEdgeKey(edge.source, edge.target))
    );
    if (!candidates.length) {
      break;
    }
    candidates.sort((a, b) => {
      const targetA = nodeMap.get(String(a.target));
      const targetB = nodeMap.get(String(b.target));
      return (
        Number(b.frequency || 0) - Number(a.frequency || 0) ||
        Number(targetB?.end_count || 0) - Number(targetA?.end_count || 0) ||
        Number(targetB?.frequency || 0) - Number(targetA?.frequency || 0)
      );
    });
    const bestEdge = candidates[0];
    const key = processEdgeKey(bestEdge.source, bestEdge.target);
    edgeKeys.add(key);
    nodeIds.add(String(bestEdge.source));
    nodeIds.add(String(bestEdge.target));
    currentId = String(bestEdge.target);
  }

  return { nodeIds, edgeKeys };
}

function simplifyProcessGraph(nodes, edges, options = {}) {
  // Normalize first so renderers can share this function across process and
  // handoff views, then apply activity/path coverage thresholds.
  const preserveEdgeKeys = options.preserveEdgeKeys || new Set();
  const normalizedNodes = nodes.map((node) => ({
    ...node,
    id: String(node.id),
    label: String(node.label || node.id),
    frequency: Number(node.frequency || 0),
    start_count: Number(node.start_count || 0),
    end_count: Number(node.end_count || 0),
    median_position: Number(node.median_position),
  }));
  const nodeMap = new Map(normalizedNodes.map((node) => [node.id, node]));

  const normalizedEdges = edges
    .map((edge) => ({
      ...edge,
      source: String(edge.source),
      target: String(edge.target),
      frequency: Number(edge.frequency || 0),
      median_duration_seconds: Number(edge.median_duration_seconds || 0),
      mean_duration_seconds: Number(edge.mean_duration_seconds || 0),
      p90_duration_seconds: Number(edge.p90_duration_seconds || 0),
    }))
    .filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target))
    .sort((a, b) => b.frequency - a.frequency);

  const outgoingBySource = new Map();
  const incomingByTarget = new Map();
  normalizedNodes.forEach((node) => {
    outgoingBySource.set(node.id, []);
    incomingByTarget.set(node.id, []);
  });
  normalizedEdges.forEach((edge) => {
    outgoingBySource.get(edge.source)?.push(edge);
    incomingByTarget.get(edge.target)?.push(edge);
  });

  const backbone = buildDominantBackbone(
    normalizedNodes,
    normalizedEdges,
    outgoingBySource,
    nodeMap
  );
  const { activityPercent, pathPercent } = currentProcessDetailSettings();

  // Animated edges and selected edges are preserved, otherwise the current
  // frame could disappear while the user scrubs or plays the animation.
  const activityKeep =
    activityPercent <= 0
      ? new Set(backbone.nodeIds)
      : topCoverageSet(
          normalizedNodes,
          (node) => node.frequency,
          activityPercent,
          (node) => node.id
        );
  normalizedNodes.forEach((node) => {
    if (node.start_count > 0 || node.end_count > 0) {
      activityKeep.add(node.id);
    }
  });
  backbone.nodeIds.forEach((nodeId) => activityKeep.add(nodeId));
  normalizedEdges.forEach((edge) => {
    const edgeKey = processEdgeKey(edge.source, edge.target);
    if (preserveEdgeKeys.has(edgeKey)) {
      activityKeep.add(edge.source);
      activityKeep.add(edge.target);
    }
  });

  const eligibleEdges = normalizedEdges.filter(
    (edge) => activityKeep.has(edge.source) && activityKeep.has(edge.target)
  );
  const pathKeep =
    pathPercent <= 0
      ? new Set(backbone.edgeKeys)
      : topCoverageSet(
          eligibleEdges,
          (edge) => edge.frequency,
          pathPercent,
          (edge) => processEdgeKey(edge.source, edge.target)
        );
  backbone.edgeKeys.forEach((edgeKey) => pathKeep.add(edgeKey));
  preserveEdgeKeys.forEach((edgeKey) => pathKeep.add(edgeKey));

  const visibleEdges = eligibleEdges.filter((edge) =>
    pathKeep.has(processEdgeKey(edge.source, edge.target))
  );
  const visibleNodeIds = new Set(backbone.nodeIds);
  visibleEdges.forEach((edge) => {
    visibleNodeIds.add(edge.source);
    visibleNodeIds.add(edge.target);
  });
  normalizedNodes.forEach((node) => {
    if ((node.start_count > 0 || node.end_count > 0) && activityKeep.has(node.id)) {
      visibleNodeIds.add(node.id);
    }
  });

  let visibleNodes = normalizedNodes.filter((node) => visibleNodeIds.has(node.id));
  if (!visibleEdges.length && eligibleEdges.length) {
    const fallbackEdge = eligibleEdges[0];
    visibleNodes = normalizedNodes.filter(
      (node) => node.id === fallbackEdge.source || node.id === fallbackEdge.target
    );
    return {
      nodes: visibleNodes,
      edges: [fallbackEdge],
      totalNodeCount: normalizedNodes.length,
      totalEdgeCount: normalizedEdges.length,
      backbone,
    };
  }

  return {
    nodes: visibleNodes,
    edges: visibleEdges,
    totalNodeCount: normalizedNodes.length,
    totalEdgeCount: normalizedEdges.length,
    backbone,
  };
}

function computeProcessStages(nodes, edges) {
  // Prefer median event position from the backend, then fill missing stages by
  // walking through direct-follow edges from likely start activities.
  const stageMap = new Map();
  const incoming = new Map();
  const outgoing = new Map();

  nodes.forEach((node) => {
    incoming.set(node.id, []);
    outgoing.set(node.id, []);
  });
  edges.forEach((edge) => {
    incoming.get(edge.target)?.push(edge);
    outgoing.get(edge.source)?.push(edge);
  });

  nodes.forEach((node) => {
    if (Number.isFinite(node.median_position)) {
      stageMap.set(node.id, Math.max(0, Math.round(node.median_position)));
    }
  });

  const startNodes = [...nodes]
    .filter((node) => node.start_count > 0)
    .sort(
      (a, b) =>
        Number(b.start_count || 0) - Number(a.start_count || 0) ||
        Number(b.frequency || 0) - Number(a.frequency || 0)
    );

  const seedNodes = startNodes.length
    ? startNodes
    : [...nodes].sort((a, b) => Number(b.frequency || 0) - Number(a.frequency || 0)).slice(0, 1);
  seedNodes.forEach((node) => {
    if (!stageMap.has(node.id)) {
      stageMap.set(node.id, 0);
    }
  });

  for (let pass = 0; pass < nodes.length + 2; pass += 1) {
    let changed = false;
    edges.forEach((edge) => {
      if (!stageMap.has(edge.source) && !stageMap.has(edge.target)) {
        return;
      }
      const sourceStage = stageMap.get(edge.source);
      const targetStage = stageMap.get(edge.target);
      if (sourceStage !== undefined && targetStage === undefined) {
        stageMap.set(edge.target, sourceStage + 1);
        changed = true;
      } else if (sourceStage === undefined && targetStage !== undefined) {
        stageMap.set(edge.source, Math.max(0, targetStage - 1));
        changed = true;
      }
    });
    if (!changed) {
      break;
    }
  }

  let nextStage = Math.max(...stageMap.values(), 0);
  nodes.forEach((node) => {
    if (!stageMap.has(node.id)) {
      nextStage += 1;
      stageMap.set(node.id, nextStage);
    }
  });

  const minStage = Math.min(...stageMap.values(), 0);
  if (minStage !== 0) {
    stageMap.forEach((value, key) => {
      stageMap.set(key, value - minStage);
    });
  }

  return { stageMap, incoming, outgoing };
}

function nodeBoxDimensions(node, nodeMaxFrequency) {
  return { width: 160, height: 200 };
}

function computeProcessLayout(nodes, edges, options = {}) {
  // A light barycenter pass reduces edge crossings by sorting nodes within each
  // stage near the weighted center of their neighbors in adjacent stages.
  const { stageMap, incoming, outgoing } = computeProcessStages(nodes, edges);
  const stages = [...new Set(nodes.map((node) => stageMap.get(node.id) || 0))].sort((a, b) => a - b);
  const nodesByStage = new Map();
  stages.forEach((stage) => nodesByStage.set(stage, []));
  nodes.forEach((node) => {
    const stage = stageMap.get(node.id) || 0;
    nodesByStage.get(stage)?.push(node);
  });

  nodesByStage.forEach((group) => {
    group.sort(
      (a, b) =>
        Number(b.start_count || 0) - Number(a.start_count || 0) ||
        Number(b.frequency || 0) - Number(a.frequency || 0) ||
        a.label.localeCompare(b.label)
    );
  });

  const stageOrderIndex = new Map();
  function refreshStageIndices() {
    nodesByStage.forEach((group) => {
      group.forEach((node, index) => {
        stageOrderIndex.set(node.id, index);
      });
    });
  }

  function barycenterFor(nodeId, neighborMap, useSource) {
    const related = neighborMap.get(nodeId) || [];
    if (!related.length) {
      return stageOrderIndex.get(nodeId) || 0;
    }
    const weighted = related.reduce(
      (acc, edge) => {
        const otherId = useSource ? edge.source : edge.target;
        const order = stageOrderIndex.get(otherId);
        if (order === undefined) {
          return acc;
        }
        const weight = Math.max(Number(edge.frequency || 0), 1);
        return {
          total: acc.total + order * weight,
          weight: acc.weight + weight,
        };
      },
      { total: 0, weight: 0 }
    );
    if (!weighted.weight) {
      return stageOrderIndex.get(nodeId) || 0;
    }
    return weighted.total / weighted.weight;
  }

  refreshStageIndices();
  for (let pass = 0; pass < 4; pass += 1) {
    stages.forEach((stage) => {
      const group = nodesByStage.get(stage) || [];
      group.sort(
        (a, b) =>
          barycenterFor(a.id, incoming, true) - barycenterFor(b.id, incoming, true) ||
          Number(b.frequency || 0) - Number(a.frequency || 0)
      );
      refreshStageIndices();
    });
    [...stages].reverse().forEach((stage) => {
      const group = nodesByStage.get(stage) || [];
      group.sort(
        (a, b) =>
          barycenterFor(a.id, outgoing, false) - barycenterFor(b.id, outgoing, false) ||
          Number(b.frequency || 0) - Number(a.frequency || 0)
      );
      refreshStageIndices();
    });
  }

  const maxStage = Math.max(...stages, 0);
  const nodeMaxFrequency = Math.max(...nodes.map((node) => Number(node.frequency || 0)), 1);
  const nodeWidthScale = Number(options.nodeWidthScale || 1.0);
  const nodeHeightOverride = options.nodeHeightOverride;
  const boxByNode = new Map();
  nodes.forEach((node) => {
    const box = nodeBoxDimensions(node, nodeMaxFrequency);
    boxByNode.set(node.id, {
      width: nodeWidthScale !== 1.0 ? Math.round(box.width * nodeWidthScale) : box.width,
      height: nodeHeightOverride !== undefined ? nodeHeightOverride : box.height,
    });
  });

  const siblingGap = Number(options.horizontalGap || 58);
  const isLTR = options.orientation === "ltr";
  const maxNodesInStage = Math.max(...[...nodesByStage.values()].map((group) => group.length), 1);

  if (isLTR) {
    // Stages spread on X axis; nodes stack vertically within each stage.
    // options.topPad/bottomPad reinterpreted as left/right stage-axis padding.
    const leftPad = options.protectLoopTop
      ? Math.max(Number(options.topPad || 140), 126 + maxNodesInStage * 26)
      : Number(options.topPad || 140);
    const rightPad = Number(options.bottomPad || 120);
    const topPad = Number(options.leftPad || 80);
    const bottomPad = Number(options.rightPad || 80);
    const stageGap =
      maxStage === 0
        ? 0
        : Math.max(
            Number(options.minStageGap || 300),
            Number(options.stageGapBase || 260) + Math.max(maxNodesInStage - 1, 0) * 8
          );
    const heightByStage = stages.map((stage) => {
      const group = nodesByStage.get(stage) || [];
      return (
        group.reduce((sum, node) => sum + (boxByNode.get(node.id)?.height || 0), 0) +
        Math.max(group.length - 1, 0) * siblingGap
      );
    });
    const requiredInnerHeight = Math.max(...heightByStage, 0);
    const ltrWidth = Math.max(
      Number(options.minWidth || 1200),
      Math.ceil(leftPad + rightPad + maxStage * stageGap)
    );
    const ltrHeight = Math.max(
      Number(options.minHeight || 600),
      Math.ceil(requiredInnerHeight + topPad + bottomPad + Number(options.extraHeight || 0))
    );
    const ltrLayout = new Map();
    const stageXs = new Map();
    const verticalShift = Number(options.verticalShift || 0);
    stages.forEach((stage) => {
      const group = nodesByStage.get(stage) || [];
      const x = maxStage === 0 ? ltrWidth / 2 : leftPad + stage * stageGap;
      stageXs.set(stage, x);
      const groupHeight =
        group.reduce((sum, node) => sum + (boxByNode.get(node.id)?.height || 0), 0) +
        Math.max(group.length - 1, 0) * siblingGap;
      let cursorY = (ltrHeight - groupHeight) / 2 + verticalShift;
      group.forEach((node, index) => {
        const box = boxByNode.get(node.id) || { width: 160, height: 54 };
        const y = cursorY + box.height / 2;
        cursorY += box.height + siblingGap;
        ltrLayout.set(node.id, {
          ...node,
          stage,
          order: index,
          x,
          y,
          width: box.width,
          height: box.height,
        });
      });
    });
    const maxNodeHalfW = Math.max(...[...boxByNode.values()].map((b) => b.width / 2), 60);
    const leftAnchorX = Math.max(leftPad - maxNodeHalfW - 120, 70);
    const rightAnchorX = Math.min(ltrWidth - rightPad + maxNodeHalfW + 120, ltrWidth - 70);
    const anchorY = ltrHeight / 2 + verticalShift;
    return {
      nodesByStage,
      positionedNodes: ltrLayout,
      maxStage,
      width: ltrWidth,
      height: ltrHeight,
      stageXs,
      leftAnchor: { x: leftAnchorX, y: anchorY },
      rightAnchor: { x: rightAnchorX, y: anchorY },
    };
  }

  const horizontalGap = siblingGap;
  const topPad = options.protectLoopTop
    ? Math.max(Number(options.topPad || 122), 126 + maxNodesInStage * 26)
    : Number(options.topPad || 122);
  const bottomPad = Number(options.bottomPad || 118);
  const leftPad = Number(options.leftPad || 110);
  const rightPad = Number(options.rightPad || 110);
  const stageGap =
    maxStage === 0
      ? 0
      : Math.max(
          Number(options.minStageGap || 146),
          Number(options.stageGapBase || 108) + Math.max(maxNodesInStage - 1, 0) * 8
        );
  const widthByStage = stages.map((stage) => {
    const group = nodesByStage.get(stage) || [];
    return group.reduce((sum, node) => sum + (boxByNode.get(node.id)?.width || 0), 0) +
      Math.max(group.length - 1, 0) * horizontalGap;
  });
  const requiredInnerWidth = Math.max(...widthByStage, 0);
  const width = Math.max(
    Number(options.minWidth || 1480),
    Math.ceil(requiredInnerWidth + leftPad + rightPad + Number(options.extraWidth || 140))
  );
  const height = Math.max(
    Number(options.minHeight || 860),
    Math.ceil(topPad + bottomPad + maxStage * stageGap)
  );
  const layout = new Map();
  const stageYs = new Map();

  stages.forEach((stage) => {
    const group = nodesByStage.get(stage) || [];
    const y = maxStage === 0 ? height / 2 : topPad + stage * stageGap;
    stageYs.set(stage, y);
    const groupWidth =
      group.reduce((sum, node) => sum + (boxByNode.get(node.id)?.width || 0), 0) +
      Math.max(group.length - 1, 0) * horizontalGap;
    let cursorX = (width - groupWidth) / 2;
    group.forEach((node, index) => {
      const box = boxByNode.get(node.id) || { width: 160, height: 54 };
      const x = cursorX + box.width / 2;
      cursorX += box.width + horizontalGap;
      layout.set(node.id, {
        ...node,
        stage,
        order: index,
        x,
        y,
        width: box.width,
        height: box.height,
      });
    });
  });

  return {
    nodesByStage,
    positionedNodes: layout,
    maxStage,
    width,
    height,
    stageYs,
    topAnchor: { x: width / 2, y: 48 },
    bottomAnchor: { x: width / 2, y: height - 44 },
  };
}

function processEdgeGeometryLTR(edge, source, target, height, bounds = {}) {
  // LTR variant: forward edges exit the right side of source and enter the left
  // side of target. Same-stage loops arc left; backward edges swing above/below.
  const sameStage = source.stage === target.stage;
  const backward = source.stage > target.stage;

  if (edge.source === edge.target) {
    return {
      d: `M ${source.x + source.width / 2 - 6} ${source.y - 8}
        C ${source.x + source.width / 2 + 54} ${source.y - 70},
          ${source.x + source.width / 2 + 54} ${source.y + 18},
          ${source.x + 4} ${source.y + source.height / 2}`,
      points: {
        x0: source.x + source.width / 2 - 6,
        y0: source.y - 8,
        cx1: source.x + source.width / 2 + 54,
        cy1: source.y - 70,
        cx2: source.x + source.width / 2 + 54,
        cy2: source.y + 18,
        x1: source.x + 4,
        y1: source.y + source.height / 2,
      },
    };
  }

  if (sameStage) {
    const loopWidth = 106 + Math.abs(source.order - target.order) * 26;
    return {
      d: `M ${source.x - source.width / 2} ${source.y}
        C ${source.x - loopWidth} ${source.y},
          ${target.x - loopWidth} ${target.y},
          ${target.x - target.width / 2} ${target.y}`,
      points: {
        x0: source.x - source.width / 2,
        y0: source.y,
        cx1: source.x - loopWidth,
        cy1: source.y,
        cx2: target.x - loopWidth,
        cy2: target.y,
        x1: target.x - target.width / 2,
        y1: target.y,
      },
    };
  }

  if (backward) {
    const { minNodeY, maxNodeY } = bounds;
    const margin = 60;
    const aboveY = minNodeY !== undefined ? Math.max(minNodeY - margin, 10) : 42;
    const belowY = maxNodeY !== undefined ? Math.min(maxNodeY + margin, height - 10) : height - 42;
    const outerY = (source.y + target.y) / 2 < height / 2 ? aboveY : belowY;
    return {
      d: `M ${source.x - source.width / 2} ${source.y}
        C ${source.x - source.width / 2 - 44} ${outerY},
          ${target.x + target.width / 2 + 44} ${outerY},
          ${target.x + target.width / 2} ${target.y}`,
      points: {
        x0: source.x - source.width / 2,
        y0: source.y,
        cx1: source.x - source.width / 2 - 44,
        cy1: outerY,
        cx2: target.x + target.width / 2 + 44,
        cy2: outerY,
        x1: target.x + target.width / 2,
        y1: target.y,
      },
    };
  }

  const exitX = source.x + source.width / 2;
  const entryX = target.x - target.width / 2;
  const edgeSpan = Math.max(entryX - exitX, 20);
  const sway = clamp((target.y - source.y) * 0.16, -84, 84);
  return {
    d: `M ${exitX} ${source.y}
      C ${exitX + edgeSpan * 0.45} ${source.y + sway},
        ${entryX - edgeSpan * 0.45} ${target.y - sway},
        ${entryX} ${target.y}`,
    points: {
      x0: exitX,
      y0: source.y,
      cx1: exitX + edgeSpan * 0.45,
      cy1: source.y + sway,
      cx2: entryX - edgeSpan * 0.45,
      cy2: target.y - sway,
      x1: entryX,
      y1: target.y,
    },
  };
}

function processEdgeGeometry(edge, source, target, dimension, orientation = "ttb", bounds = {}) {
  // Different edge shapes prevent self-loops, same-stage loops, back edges, and
  // normal forward paths from collapsing onto the same curve.
  if (orientation === "ltr") {
    return processEdgeGeometryLTR(edge, source, target, dimension, bounds);
  }
  const sameStage = source.stage === target.stage;
  const backward = source.stage > target.stage;

  if (edge.source === edge.target) {
    return {
      d: `M ${source.x + source.width / 2 - 6} ${source.y - 8}
        C ${source.x + source.width / 2 + 54} ${source.y - 70},
          ${source.x + source.width / 2 + 54} ${source.y + 18},
          ${source.x + 4} ${source.y + source.height / 2}`,
      points: {
        x0: source.x + source.width / 2 - 6,
        y0: source.y - 8,
        cx1: source.x + source.width / 2 + 54,
        cy1: source.y - 70,
        cx2: source.x + source.width / 2 + 54,
        cy2: source.y + 18,
        x1: source.x + 4,
        y1: source.y + source.height / 2,
      },
    };
  }

  if (sameStage) {
    const isAdjacent = Math.abs((source.order ?? 0) - (target.order ?? 0)) === 1;
    if (isAdjacent) {
      const goRight = source.x < target.x;
      const srcSideX = goRight ? source.x + source.width / 2 : source.x - source.width / 2;
      const tgtSideX = goRight ? target.x - target.width / 2 : target.x + target.width / 2;
      const cp = Math.abs(tgtSideX - srcSideX) / 3;
      const bow = 12;
      const bowY = source.y + (goRight ? -bow : bow);
      const sign = goRight ? 1 : -1;
      return {
        d: `M ${srcSideX} ${source.y} C ${srcSideX + sign * cp} ${bowY}, ${tgtSideX - sign * cp} ${bowY}, ${tgtSideX} ${target.y}`,
        points: { x0: srcSideX, y0: source.y, cx1: srcSideX + sign * cp, cy1: bowY, cx2: tgtSideX - sign * cp, cy2: bowY, x1: tgtSideX, y1: target.y },
      };
    }
    const loopHeight = 106 + Math.abs(source.order - target.order) * 26;
    return {
      d: `M ${source.x} ${source.y - source.height / 2}
        C ${source.x} ${source.y - loopHeight},
          ${target.x} ${target.y - loopHeight},
          ${target.x} ${target.y - target.height / 2}`,
      points: {
        x0: source.x,
        y0: source.y - source.height / 2,
        cx1: source.x,
        cy1: source.y - loopHeight,
        cx2: target.x,
        cy2: target.y - loopHeight,
        x1: target.x,
        y1: target.y - target.height / 2,
      },
    };
  }

  // Backward edges and skip-stage forward edges (stageDiff > 1) both route through
  // a dedicated lane outside the node cluster — a C-shaped arc that never enters
  // the diagram interior. Lane side is chosen by source position vs diagram centre.
  // Margin of 160px ensures the arc is wide enough that at all intermediate Y levels
  // the interpolated X clears the rightmost/leftmost node edges.
  const isSkipForward = !backward && (target.stage - source.stage) > 1;
  if (backward || isSkipForward) {
    const centerX = bounds.minNodeX !== undefined
      ? (bounds.minNodeX + bounds.maxNodeX) / 2
      : (source.x + target.x) / 2;
    const useLeft = source.x < centerX;
    const farX = useLeft
      ? (bounds.minNodeX !== undefined ? bounds.minNodeX : source.x) - 160
      : (bounds.maxNodeX !== undefined ? bounds.maxNodeX : source.x) + 160;
    const srcEdgeX = useLeft ? source.x - source.width / 2 : source.x + source.width / 2;
    const tgtEdgeX = useLeft ? target.x - target.width / 2 : target.x + target.width / 2;
    return {
      d: `M ${srcEdgeX} ${source.y} C ${farX} ${source.y}, ${farX} ${target.y}, ${tgtEdgeX} ${target.y}`,
      points: {
        x0: srcEdgeX,
        y0: source.y,
        cx1: farX,
        cy1: source.y,
        cx2: farX,
        cy2: target.y,
        x1: tgtEdgeX,
        y1: target.y,
      },
    };
  }

  // Orthogonal elbow: vertical in source column → horizontal at midY → vertical in
  // target column. This guarantees the path never enters any node bounding box
  // because the only horizontal segment runs through the inter-row gap.
  const exitY = source.y + source.height / 2;
  const entryY = target.y - target.height / 2;
  const midY = (exitY + entryY) / 2;
  const dx = target.x - source.x;
  if (Math.abs(dx) < 4) {
    return {
      d: `M ${source.x} ${exitY} L ${target.x} ${entryY}`,
      waypoints: [{ x: source.x, y: exitY }, { x: target.x, y: entryY }],
    };
  }
  const dir = dx > 0 ? 1 : -1;
  const r = Math.min(18, Math.abs(dx) / 4, Math.max(midY - exitY - 2, 2));
  return {
    d: `M ${source.x} ${exitY}
      L ${source.x} ${midY - r}
      Q ${source.x} ${midY} ${source.x + dir * r} ${midY}
      L ${target.x - dir * r} ${midY}
      Q ${target.x} ${midY} ${target.x} ${midY + r}
      L ${target.x} ${entryY}`,
    waypoints: [
      { x: source.x, y: exitY },
      { x: source.x, y: midY },
      { x: target.x, y: midY },
      { x: target.x, y: entryY },
    ],
  };
}

// Returns the midpoint of a geometry object regardless of its routing type.
function geometryMidpoint(geometry) {
  if (geometry.waypoints) return waypointPoint(0.5, geometry.waypoints);
  const p = geometry.points;
  return cubicBezierPoint(0.5, p.x0, p.y0, p.cx1, p.cy1, p.cx2, p.cy2, p.x1, p.y1);
}

// Label position at arc midpoint offset to the convex (outer) side of the bend.
// For elbow paths: picks the perpendicular normal that points away from the
// straight-line source→target vector (negative dot product = outward/convex).
// For bezier arcs: keeps the existing above-apex placement.
function geometryLabelPosition(geometry, source, target, offsetPx) {
  if (geometry.waypoints) {
    const { x, y, tx, ty } = waypointMidTangent(0.5, geometry.waypoints);
    const n1x = -ty, n1y = tx;
    const n2x = ty, n2y = -tx;
    const sdx = target.x - source.x;
    const sdy = target.y - source.y;
    const useN1 = (n1x * sdx + n1y * sdy) <= 0;
    return { x: x + (useN1 ? n1x : n2x) * offsetPx, y: y + (useN1 ? n1y : n2y) * offsetPx, textAnchor: "middle" };
  }
  const mid = geometryMidpoint(geometry);
  return { x: mid.x, y: mid.y - offsetPx, textAnchor: "middle" };
}

function estimateLabelWidth(text, fontSize) {
  return text.length * fontSize * 0.61;
}

// Greedy vertical lane de-collision for edge labels sharing the same horizontal
// corridor. Items must have { x, y, yOffset, text, fontSize, textAnchor }. Mutates yOffset.
function resolveEdgeLabelCollisions(items) {
  const LANE_OFFSETS = [0, -13, 13, -26, 26, -39, 39, -52, 52];
  const corridors = new Map();
  items.forEach((item) => {
    const key = Math.round(item.y);
    if (!corridors.has(key)) corridors.set(key, []);
    corridors.get(key).push(item);
  });
  corridors.forEach((group) => {
    group.sort((a, b) => {
      const leftEdge = (i) => {
        const w = estimateLabelWidth(i.text, i.fontSize);
        return i.textAnchor === "start" ? i.x : i.x - w / 2;
      };
      return leftEdge(a) - leftEdge(b);
    });
    const laneRightX = new Map();
    group.forEach((item) => {
      const w = estimateLabelWidth(item.text, item.fontSize);
      const xMin = item.textAnchor === "start" ? item.x - 6 : item.x - w / 2 - 6;
      const xMax = item.textAnchor === "start" ? item.x + w + 6 : item.x + w / 2 + 6;
      for (const offset of LANE_OFFSETS) {
        if ((laneRightX.get(offset) ?? -Infinity) <= xMin) {
          laneRightX.set(offset, xMax);
          item.yOffset = offset;
          return;
        }
      }
      item.yOffset = LANE_OFFSETS[LANE_OFFSETS.length - 1];
    });
  });
}

function appendSvgTitle(element, text) {
  const title = svgElement("title");
  title.textContent = text;
  element.appendChild(title);
}

function appendAnimatedCaseDots(pulseLayer, geometry, activeCount, activityIntensity, pulseT) {
  // Yellow dots are intentionally rendered only for animation overlays. Static
  // process maps should show structure, not simulated cases.
  const dotCount = Math.max(1, Math.min(Number(activeCount || 0), 80));
  if (!dotCount) {
    return;
  }

  for (let dotIndex = 0; dotIndex < dotCount; dotIndex += 1) {
    const dotT = (pulseT + dotIndex / dotCount) % 1;
    // Two-segment paths (highway routing for multi-stage skips) split the travel:
    // first half = first bezier, second half = second bezier.
    let pulsePoint;
    if (geometry.waypoints) {
      pulsePoint = waypointPoint(dotT, geometry.waypoints);
    } else if (geometry.points2) {
      const seg = dotT < 0.5 ? geometry.points : geometry.points2;
      const segT = dotT < 0.5 ? dotT * 2 : (dotT - 0.5) * 2;
      pulsePoint = cubicBezierPoint(segT, seg.x0, seg.y0, seg.cx1, seg.cy1, seg.cx2, seg.cy2, seg.x1, seg.y1);
    } else {
      pulsePoint = cubicBezierPoint(
        dotT,
        geometry.points.x0,
        geometry.points.y0,
        geometry.points.cx1,
        geometry.points.cy1,
        geometry.points.cx2,
        geometry.points.cy2,
        geometry.points.x1,
        geometry.points.y1
      );
    }
    pulseLayer.appendChild(
      svgElement("circle", {
        cx: pulsePoint.x,
        cy: pulsePoint.y,
        r: 7 + Math.min(activityIntensity, 1) * 3.2,
        fill: FLOW_COLORS.caseBallFill,
        stroke: FLOW_COLORS.caseBallStroke,
        "stroke-width": 1.5,
        opacity: 0.98,
      })
    );
  }
}

function renderProcessMap(nodes, edges) {
  // Main interactive DFG-style process map. It renders start/end anchors,
  // frequency/performance labels, clickable activities/paths, and optional
  // yellow case dots when animation overlay is active.
  els.processMap.innerHTML = "";
  updateProcessDetailLabels();

  if (!nodes.length || !edges.length) {
    setProcessMapSummary("No process map edges available for current filters.");
    renderEmptyMap("No process map edges available for current filters.");
    return;
  }

  const simplified = simplifyProcessGraph(nodes, edges, {});
  if (!simplified.nodes.length || !simplified.edges.length) {
    setProcessMapSummary("The current activity/path detail settings hide all visible flows.");
    renderEmptyMap("Raise activity or path detail to show flows.");
    return;
  }

  const activeFrame = currentAnimationFrameData();
  const hasAnimationOverlay = Boolean(activeFrame);

  const layout = computeProcessLayout(simplified.nodes, simplified.edges, {
    topPad: 150,
    bottomPad: 140,
    leftPad: 80,
    rightPad: 80,
    minStageGap: 132,
    stageGapBase: 108,
    horizontalGap: 160,
    nodeWidthScale: 1.5,
    nodeHeightOverride: 72,
  });
  const width = layout.width;
  const height = layout.height;
  const allPosForViewBox = [...layout.positionedNodes.values()];
  const laneMargin = 160;
  const svgLeft = Math.min(0, Math.min(...allPosForViewBox.map((n) => n.x - n.width / 2)) - laneMargin);
  const svgRight = Math.max(width, Math.max(...allPosForViewBox.map((n) => n.x + n.width / 2)) + laneMargin);
  const svgWidth = svgRight - svgLeft;
  els.processMap.setAttribute("viewBox", `${svgLeft} 0 ${svgWidth} ${height}`);
  els.processMap.style.aspectRatio = `${svgWidth} / ${height}`;
  const defs = svgElement("defs");
  const marker = svgElement("marker", {
    id: "process-arrowhead",
    viewBox: "0 0 10 10",
    refX: 10,
    refY: 5,
    markerUnits: "userSpaceOnUse",
    markerWidth: 20,
    markerHeight: 20,
    orient: "auto-start-reverse",
  });
  marker.appendChild(
    svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: FLOW_COLORS.edgeMarker })
  );
  defs.appendChild(marker);
  els.processMap.appendChild(defs);

  const positionedNodes = layout.positionedNodes;
  const edgeMaxFrequency = Math.max(
    ...simplified.edges.map((edge) => Number(edge.frequency || 0)),
    1
  );
  const edgeMaxDuration = Math.max(
    ...simplified.edges.map((edge) => Number(edge.total_duration_seconds || 0)),
    1
  );
  const nodeMaxFrequency = Math.max(
    ...simplified.nodes.map((node) => Number(node.frequency || 0)),
    1
  );
  const nodeMaxDuration = Math.max(
    ...simplified.nodes.map((node) => Number(node.total_duration_seconds || 0)),
    1
  );

  const guidesLayer = svgElement("g");
  const anchorLayer = svgElement("g");
  const edgesLayer = svgElement("g");
  const labelsLayer = svgElement("g");
  const pulseLayer = svgElement("g");
  const nodesLayer = svgElement("g");

  for (let stage = 0; stage <= layout.maxStage; stage += 1) {
    const y = layout.stageYs.get(stage) || height / 2;
    guidesLayer.appendChild(
      svgElement("line", {
        x1: 34,
        y1: y,
        x2: width - 34,
        y2: y,
        stroke: "rgba(0, 0, 0, 0.06)",
        "stroke-width": 1,
      })
    );
  }

  const anchorFill = "rgba(0, 51, 153, 0.1)";
  const pillW = 110, pillH = 40, pillR = 20;
  const startRect = svgElement("rect", {
    x: layout.topAnchor.x - pillW / 2,
    y: layout.topAnchor.y - pillH / 2,
    width: pillW,
    height: pillH,
    rx: pillR,
    fill: anchorFill,
    stroke: "rgba(0, 51, 153, 0.24)",
  });
  const endRect = svgElement("rect", {
    x: layout.bottomAnchor.x - pillW / 2,
    y: layout.bottomAnchor.y - pillH / 2,
    width: pillW,
    height: pillH,
    rx: pillR,
    fill: anchorFill,
    stroke: "rgba(0, 51, 153, 0.24)",
  });
  anchorLayer.appendChild(startRect);
  anchorLayer.appendChild(endRect);

  const startLabel = svgElement("text", {
    x: layout.topAnchor.x,
    y: layout.topAnchor.y,
    "text-anchor": "middle",
    "dominant-baseline": "central",
    "font-size": 25,
    "font-family": "IBM Plex Mono, monospace",
    fill: "#1258ff",
  });
  startLabel.textContent = "START";
  anchorLayer.appendChild(startLabel);

  const endLabel = svgElement("text", {
    x: layout.bottomAnchor.x,
    y: layout.bottomAnchor.y,
    "text-anchor": "middle",
    "dominant-baseline": "central",
    "font-size": 25,
    "font-family": "IBM Plex Mono, monospace",
    fill: "#1258ff",
  });
  endLabel.textContent = "END";
  anchorLayer.appendChild(endLabel);

  const pulseT = ((state.animation.frameIndex % 16) + 1) / 17;
  const topStartCount = Math.max(...simplified.nodes.map((node) => Number(node.start_count || 0)), 1);
  const topEndCount = Math.max(...simplified.nodes.map((node) => Number(node.end_count || 0)), 1);

  const allProcessPos = [...positionedNodes.values()];
  const processNodeBounds = {
    minNodeX: Math.min(...allProcessPos.map((n) => n.x - n.width / 2)),
    maxNodeX: Math.max(...allProcessPos.map((n) => n.x + n.width / 2)),
  };

  simplified.nodes
    .filter((node) => node.start_count > 0)
    .forEach((node) => {
      const point = positionedNodes.get(node.id);
      if (!point) {
        return;
      }
      const strength = Math.max(Number(node.start_count || 0) / topStartCount, 0.08);
      const startConnY = layout.topAnchor.y + pillH / 2;
      const startNodeY = point.y - point.height / 2;
      let d;
      const startCp = Math.max((startNodeY - startConnY) * 0.5, 8);
      d = `M ${layout.topAnchor.x} ${startConnY} C ${layout.topAnchor.x} ${startConnY + startCp}, ${point.x} ${startNodeY - startCp}, ${point.x} ${startNodeY}`;
      const path = svgElement("path", { d, fill: "none", stroke: FLOW_COLORS.anchorStroke(0.42 + strength * 0.42), "stroke-width": 1.4 + strength * 5.4, opacity: 0.96 });
      appendSvgTitle(path, `Start in case: ${node.label} (${formatNumber(node.start_count)})`);
      edgesLayer.appendChild(path);
    });

  simplified.nodes
    .filter((node) => node.end_count > 0)
    .forEach((node) => {
      const point = positionedNodes.get(node.id);
      if (!point) {
        return;
      }
      const strength = Math.max(Number(node.end_count || 0) / topEndCount, 0.08);
      const endNodeY = point.y + point.height / 2;
      const endConnY = layout.bottomAnchor.y - pillH / 2;
      const offsetFromEnd = point.x - layout.bottomAnchor.x;
      let d;
      const pathXMin = Math.min(point.x, layout.bottomAnchor.x) - 60;
      const pathXMax = Math.max(point.x, layout.bottomAnchor.x) + 60;
      const pathBlocked = allProcessPos.some(
        (n) => n !== point && n.x >= pathXMin && n.x <= pathXMax && n.y > endNodeY && n.y < endConnY
      );
      if (pathBlocked) {
        const goRight = offsetFromEnd >= 0;
        const farX = goRight ? processNodeBounds.maxNodeX + 160 : processNodeBounds.minNodeX - 160;
        const srcEdgeX = goRight ? point.x + point.width / 2 : point.x - point.width / 2;
        const r = 30;
        const laneStartY = point.y + 2 * r;
        const laneEndY = Math.max(laneStartY, endConnY - 2 * r);
        const exitCpX = layout.bottomAnchor.x + (goRight ? 2 * r : -2 * r);
        d = `M ${srcEdgeX} ${point.y} C ${farX} ${point.y}, ${farX} ${point.y + r}, ${farX} ${laneStartY} L ${farX} ${laneEndY} C ${farX} ${endConnY - r}, ${exitCpX} ${endConnY}, ${layout.bottomAnchor.x} ${endConnY}`;
      } else {
        const endCp = Math.max((endConnY - endNodeY) * 0.5, 8);
        d = `M ${point.x} ${endNodeY} C ${point.x} ${endNodeY + endCp}, ${layout.bottomAnchor.x} ${endConnY - endCp}, ${layout.bottomAnchor.x} ${endConnY}`;
      }
      const path = svgElement("path", { d, fill: "none", stroke: FLOW_COLORS.anchorStroke(0.4 + strength * 0.42), "stroke-width": 1.4 + strength * 5.4, opacity: 0.96 });
      appendSvgTitle(path, `Last in case: ${node.label} (${formatNumber(node.end_count)})`);
      edgesLayer.appendChild(path);
    });
  const edgeLabelItems = [];
  const sourceOutDegreeProcess = new Map();
  simplified.edges.slice(0, 260).forEach((edge) => {
    const k = String(edge.source);
    sourceOutDegreeProcess.set(k, (sourceOutDegreeProcess.get(k) || 0) + 1);
  });

  simplified.edges.slice(0, 260).forEach((edge, index) => {
    const source = positionedNodes.get(edge.source);
    const target = positionedNodes.get(edge.target);
    if (!source || !target) {
      return;
    }

    const geometry = processEdgeGeometry(edge, source, target, width, "ttb", processNodeBounds);
    const edgeKey = processEdgeKey(edge.source, edge.target);
    const activeCount = hasAnimationOverlay ? activeFrame.edgeCounts.get(edgeKey) || 0 : 0;
    const activityIntensity = hasAnimationOverlay
      ? Math.min(activeCount / activeFrame.maxEdgeCount, 1)
      : 0;
    const frequencyStrength = visualStrength(edge.frequency, edgeMaxFrequency, 0.05);
    const totalDuration = Number(edge.total_duration_seconds || 0);
    const durationStrength = visualStrength(totalDuration, edgeMaxDuration, 0.04);
    const durationHeat = clamp(totalDuration / edgeMaxDuration, 0, 1);
    const strength = state.mode === "performance" ? durationStrength : frequencyStrength;
    const isBackbone = simplified.backbone.edgeKeys.has(edgeKey);
    const isSelected = isSelectedMapPath(edge.source, edge.target, "process");

    let strokeWidth = 1.0 + strength * (state.mode === "performance" ? 4 : 5) + (isBackbone ? 0.6 : 0);
    let strokeColor =
      state.mode === "performance"
        ? twoStopHeat(
            FLOW_COLORS.performanceEdgeLow,
            FLOW_COLORS.performanceEdgeMid,
            FLOW_COLORS.performanceEdgeHigh,
            Math.pow(durationHeat, 0.72)
          )
        : mixColor(FLOW_COLORS.frequencyEdgeLow, FLOW_COLORS.frequencyEdgeHigh, frequencyStrength);
    let opacity = isBackbone ? 0.98 : state.mode === "performance" ? 0.82 : 0.9;

    if (hasAnimationOverlay) {
      strokeWidth = 1 + frequencyStrength * 5 + activityIntensity * 8;
      strokeColor =
        activityIntensity > 0
          ? FLOW_COLORS.activeStroke(0.68 + activityIntensity * 0.28)
          : strokeColor;
      opacity = 0.68 + Math.max(activityIntensity * 0.28, frequencyStrength * 0.16);
    }
    if (isSelected) {
      strokeWidth += 2.6;
      strokeColor = "#000000";
      opacity = 1;
    }

    const path = svgElement("path", {
      d: geometry.d,
      fill: "none",
      stroke: strokeColor,
      "stroke-width": strokeWidth,
      opacity,
      "marker-end": "url(#process-arrowhead)",
      "data-map-selectable": "true",
    });
    path.style.cursor = "pointer";
    path.addEventListener("click", (event) => {
      event.stopPropagation();
      setMapSelection({
        type: "path",
        view: "process",
        source: String(edge.source),
        target: String(edge.target),
      });
    });
    appendSvgTitle(
      path,
      `${edge.source} -> ${edge.target}\nFrequency: ${formatNumber(edge.frequency)}\nTotal wait: ${formatDuration(edge.total_duration_seconds)}\nMedian wait: ${formatDuration(edge.median_duration_seconds)}`
    );
    edgesLayer.appendChild(path);

    if (hasAnimationOverlay && activeCount > 0) {
      appendAnimatedCaseDots(pulseLayer, geometry, activeCount, activityIntensity, pulseT);
    }

    if (index < 26) {
      const text =
        state.mode === "frequency"
          ? hasAnimationOverlay
            ? `${formatNumber(activeCount)} / ${formatNumber(edge.frequency)}`
            : formatNumber(edge.frequency)
          : formatDuration(edge.total_duration_seconds);
      let lx, ly, textAnchor;
      const isSplit = (sourceOutDegreeProcess.get(String(edge.source)) || 0) > 1;
      if (isSplit || !geometry.waypoints) {
        // Split source or curved arc: place label at midpoint offset to convex side.
        const pos = geometryLabelPosition(geometry, source, target, 15);
        lx = pos.x; ly = pos.y; textAnchor = pos.textAnchor;
      } else {
        // Single arrow, straight/elbow: label to the right, clear of the arrow.
        lx = Math.max(source.x, target.x) + 23;
        ly = (source.y + source.height / 2 + target.y - target.height / 2) / 2;
        textAnchor = "start";
      }
      edgeLabelItems.push({ x: lx, y: ly, yOffset: 0, text, fontSize: 18, textAnchor, edge, source, target, durationHeat });
    }
  });

  simplified.nodes.forEach((node) => {
    const point = positionedNodes.get(node.id);
    if (!point) {
      return;
    }

    const frequencyScale = visualStrength(node.frequency, nodeMaxFrequency, 0.08);
    const totalDuration = Number(node.total_duration_seconds || 0);
    const durationHeat = clamp(totalDuration / nodeMaxDuration, 0, 1);
    const isPerformanceMode = state.mode === "performance";
    const fill = isPerformanceMode
      ? twoStopHeat(
          FLOW_COLORS.performanceNodeLow,
          FLOW_COLORS.performanceNodeMid,
          FLOW_COLORS.performanceNodeHigh,
          Math.pow(durationHeat, 0.7)
        )
      : mixColor(FLOW_COLORS.frequencyNodeLow, FLOW_COLORS.frequencyNodeHigh, frequencyScale);
    const textColor = isPerformanceMode
      ? durationHeat > 0.64
        ? "#ffffff"
        : "#08152a"
      : frequencyScale > 0.62
        ? "#ffffff"
        : "#08152a";
    const isSelected = isSelectedMapActivity(node.id, "process");
    const group = svgElement("g", { "data-map-selectable": "true" });
    group.style.cursor = "pointer";
    group.addEventListener("click", (event) => {
      event.stopPropagation();
      setMapSelection({
        type: "activity",
        view: "process",
        value: String(node.id),
      });
    });

    group.appendChild(
      svgElement("rect", {
        x: point.x - point.width / 2,
        y: point.y - point.height / 2,
        width: point.width,
        height: point.height,
        rx: 12,
        fill,
        stroke: isSelected
          ? "#000000"
          : node.start_count > 0 || node.end_count > 0
            ? isPerformanceMode
              ? "#755f40"
              : "#31445f"
            : isPerformanceMode
              ? "#806f58"
              : "#5f6978",
        "stroke-width": isSelected ? 3 : node.start_count > 0 || node.end_count > 0 ? 2.4 : 1.6,
      })
    );

    const labelLines = wrapActivityLabel(node.label || "", point.width, 17);
    const lineH = 22;
    const statGap = 20;
    const firstLabelY = Math.round(point.y - ((labelLines.length - 1) * lineH + statGap - 8) / 2);
    const statY = firstLabelY + (labelLines.length - 1) * lineH + statGap;
    const labelEl = svgElement("text", {
      "text-anchor": "middle",
      "font-size": 17,
      "font-family": "Space Grotesk, sans-serif",
      "font-weight": 700,
      fill: textColor,
    });
    labelLines.forEach((line, i) => {
      const tspan = svgElement("tspan", { x: point.x, y: firstLabelY + i * lineH });
      tspan.textContent = line;
      labelEl.appendChild(tspan);
    });
    group.appendChild(labelEl);

    const stat = svgElement("text", {
      x: point.x,
      y: statY,
      "text-anchor": "middle",
      "font-size": 15,
      "font-family": "IBM Plex Mono, monospace",
      fill: textColor,
    });
    const startEndMarker =
      node.start_count > 0 && node.end_count > 0
        ? "S/E"
        : node.start_count > 0
          ? "S"
          : node.end_count > 0
            ? "E"
            : "";
    stat.textContent = `${formatNumber(node.frequency)}${startEndMarker ? ` | ${startEndMarker}` : ""}`;
    if (isPerformanceMode) {
      stat.textContent = formatDuration(totalDuration);
    }
    group.appendChild(stat);

    appendSvgTitle(
      labelEl,
      `${node.label}\nEvents: ${formatNumber(node.frequency)}\nTotal activity duration: ${formatDuration(node.total_duration_seconds)}\nStart in case: ${formatNumber(node.start_count)}\nEnd in case: ${formatNumber(node.end_count)}`
    );
    nodesLayer.appendChild(group);
  });

  setProcessMapSummary(
    `Showing ${formatNumber(simplified.nodes.length)} of ${formatNumber(simplified.totalNodeCount)} activities and ${formatNumber(simplified.edges.length)} of ${formatNumber(simplified.totalEdgeCount)} paths. Dominant flow backbone is always preserved while activity/path detail sliders simplify the map.`
  );

  resolveEdgeLabelCollisions(edgeLabelItems);
  edgeLabelItems.forEach(({ x, y, yOffset, text, textAnchor, edge, source, target, durationHeat }) => {
    const ly = y + yOffset;
    const label = svgElement("text", {
      x,
      y: ly,
      "text-anchor": textAnchor,
      "dominant-baseline": "central",
      "font-size": 18,
      "font-family": "IBM Plex Mono, monospace",
      fill:
        state.mode === "performance" && durationHeat > 0.5
          ? FLOW_COLORS.performanceEdgeHigh
          : "#111111",
      "data-map-selectable": "true",
    });
    label.style.cursor = "pointer";
    label.addEventListener("click", (evt) => {
      evt.stopPropagation();
      setMapSelection({ type: "path", view: "process", source: String(edge.source), target: String(edge.target) });
    });
    label.textContent = text;
    labelsLayer.appendChild(label);
  });

  els.processMap.appendChild(guidesLayer);
  els.processMap.appendChild(anchorLayer);
  els.processMap.appendChild(edgesLayer);
  els.processMap.appendChild(pulseLayer);
  els.processMap.appendChild(nodesLayer);
  els.processMap.appendChild(labelsLayer);
  applyMapZoom();
}

function renderGenericNetwork(nodes, edges, options = {}) {
  // Shared renderer for the two handoff diagrams. It reuses the process-map
  // layout and animation mechanics but changes labels and selection behavior.
  els.processMap.innerHTML = "";
  const emptyMessage = options.emptyMessage || "No diagram data available.";
  updateProcessDetailLabels();
  if (!nodes.length || !edges.length) {
    setProcessMapSummary(emptyMessage);
    renderEmptyMap(emptyMessage);
    return;
  }

  const valueKey = options.valueKey || "frequency";
  const durationKey = options.durationKey || "median_duration_seconds";
  const summaryContext = options.summaryContext || detailControlContext();
  const viewKey = options.viewKey || state.currentView;
  const activeFrame = currentAnimationFrameData();
  const hasAnimationOverlay = Boolean(activeFrame);
  const defs = svgElement("defs");
  const marker = svgElement("marker", {
    id: "generic-arrowhead",
    viewBox: "0 0 10 10",
    refX: 10,
    refY: 5,
    markerUnits: "userSpaceOnUse",
    markerWidth: 10,
    markerHeight: 10,
    orient: "auto-start-reverse",
  });
  marker.appendChild(
    svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: FLOW_COLORS.edgeMarker })
  );
  defs.appendChild(marker);
  els.processMap.appendChild(defs);

  const normalizedNodes = nodes.map((node) => ({
    ...node,
    id: String(node.id),
    label: String(node.label || node.id),
    frequency: Number(node.frequency || 0),
    start_count: 0,
    end_count: 0,
    median_position: Number(node.median_position),
  }));
  const normalizedEdges = edges.map((edge) => ({
    ...edge,
    source: String(edge.source),
    target: String(edge.target),
    frequency: Number(edge[valueKey] || edge.frequency || 0),
    median_duration_seconds: Number(edge[durationKey] || edge.median_duration_seconds || 0),
  }));

  const simplified = simplifyProcessGraph(normalizedNodes, normalizedEdges, {});
  if (!simplified.nodes.length || !simplified.edges.length) {
    setProcessMapSummary(`Raise ${summaryContext.nodeSingular} or ${summaryContext.edgeSingular} detail to show flows.`);
    renderEmptyMap(`Raise ${summaryContext.nodeSingular} or ${summaryContext.edgeSingular} detail to show flows.`);
    return;
  }

  const layout = computeProcessLayout(simplified.nodes, simplified.edges, {
    minWidth: viewKey === "handoff_actor" ? 980 : 1320,
    minHeight: viewKey === "handoff_actor" ? 620 : 900,
    topPad: viewKey === "handoff_activity" ? 260 : 210,
    bottomPad: viewKey === "handoff_activity" ? 160 : 130,
    leftPad: viewKey === "handoff_actor" ? 72 : 110,
    rightPad: viewKey === "handoff_actor" ? 72 : 110,
    horizontalGap: viewKey === "handoff_actor" ? 80 : 100,
    minStageGap: viewKey === "handoff_actor" ? 200 : 156,
    stageGapBase: viewKey === "handoff_actor" ? 160 : 118,
    extraWidth: viewKey === "handoff_actor" ? 80 : 140,
    protectLoopTop: viewKey === "handoff_activity",
    nodeHeightOverride: 67,
  });
  const width = layout.width;
  const height = layout.height;
  const positionedNodes = layout.positionedNodes;
  const allHandoffPosVB = [...positionedNodes.values()];
  const svgHMargin = 160;
  const svgLeft = Math.min(0, Math.min(...allHandoffPosVB.map((n) => n.x - n.width / 2)) - svgHMargin);
  const svgRight = Math.max(width, Math.max(...allHandoffPosVB.map((n) => n.x + n.width / 2)) + svgHMargin);
  const maxLoopH = simplified.edges.reduce((max, edge) => {
    const src = positionedNodes.get(String(edge.source));
    const tgt = positionedNodes.get(String(edge.target));
    if (!src || !tgt || src.stage !== tgt.stage) return max;
    return Math.max(max, 106 + Math.abs((src.order ?? 0) - (tgt.order ?? 0)) * 26);
  }, 0);
  const minHandoffNodeY = Math.min(...allHandoffPosVB.map((n) => n.y - n.height / 2));
  const svgTop = Math.min(0, minHandoffNodeY - maxLoopH - 30);
  const svgWidth = svgRight - svgLeft;
  const svgHeight = height - svgTop;
  els.processMap.setAttribute("viewBox", `${svgLeft} ${svgTop} ${svgWidth} ${svgHeight}`);
  els.processMap.style.aspectRatio = `${svgWidth} / ${svgHeight}`;
  const maxNodeFrequency = Math.max(
    ...simplified.nodes.map((node) => Number(node.frequency || 0)),
    1
  );
  const maxEdgeValue = Math.max(
    ...simplified.edges.map((edge) => Number(edge.frequency || 0)),
    1
  );
  const edgeMaxDuration = Math.max(
    ...simplified.edges.map((edge) => Number(edge.total_duration_seconds || 0)),
    1
  );
  const nodeMaxDuration = Math.max(
    ...simplified.nodes.map((node) => Number(node.total_duration_seconds || 0)),
    1
  );
  const pulseT = ((state.animation.frameIndex % 16) + 1) / 17;

  const guidesLayer = svgElement("g");
  const edgeLayer = svgElement("g");
  const labelLayer = svgElement("g");
  const pulseLayer = svgElement("g");
  const nodeLayer = svgElement("g");

  for (let stage = 0; stage <= layout.maxStage; stage += 1) {
    const y = layout.stageYs.get(stage) || height / 2;
    guidesLayer.appendChild(
      svgElement("line", {
        x1: 34,
        y1: y,
        x2: width - 34,
        y2: y,
        stroke: "rgba(0, 0, 0, 0.06)",
        "stroke-width": 1,
      })
    );
  }

  const allHandoffPos = [...positionedNodes.values()];
  const handoffNodeBounds = {
    minNodeX: Math.min(...allHandoffPos.map((n) => n.x - n.width / 2)),
    maxNodeX: Math.max(...allHandoffPos.map((n) => n.x + n.width / 2)),
  };
  const edgeLabelItems = [];
  const sourceOutDegreeHandoff = new Map();
  simplified.edges.slice(0, 260).forEach((edge) => {
    const k = String(edge.source);
    sourceOutDegreeHandoff.set(k, (sourceOutDegreeHandoff.get(k) || 0) + 1);
  });

  simplified.edges.slice(0, 260).forEach((edge, index) => {
    const source = positionedNodes.get(String(edge.source));
    const target = positionedNodes.get(String(edge.target));
    if (!source || !target) {
      return;
    }

    const geometry = processEdgeGeometry(edge, source, target, width, "ttb", handoffNodeBounds);
    const edgeKey = processEdgeKey(edge.source, edge.target);
    const activeCount = hasAnimationOverlay ? activeFrame.edgeCounts.get(edgeKey) || 0 : 0;
    const activityIntensity = hasAnimationOverlay
      ? Math.min(activeCount / activeFrame.maxEdgeCount, 1)
      : 0;
    const value = Number(edge.frequency || 0);
    const strength = Math.max(value / maxEdgeValue, 0.05);
    const totalDuration = Number(edge.total_duration_seconds || 0);
    const durationStrength = Math.max(totalDuration / edgeMaxDuration, 0.05);
    const edgeStrength = state.mode === "performance" ? durationStrength : strength;
    const isBackbone = simplified.backbone.edgeKeys.has(edgeKey);
    const supportsPathSelection = viewKey === "handoff_activity";
    const isSelected = supportsPathSelection
      ? isSelectedMapPath(edge.source, edge.target, "handoff_activity")
      : false;

    let strokeWidth = 1.2 + edgeStrength * 7 + (isBackbone ? 1.0 : 0);
    let strokeColor = state.mode === "performance"
      ? twoStopHeat(
          FLOW_COLORS.performanceEdgeLow,
          FLOW_COLORS.performanceEdgeMid,
          FLOW_COLORS.performanceEdgeHigh,
          durationStrength
        )
      : twoStopHeat(FLOW_COLORS.frequencyEdgeLow, FLOW_COLORS.frequencyEdgeMid, FLOW_COLORS.frequencyEdgeHigh, strength);
    let opacity = isBackbone ? 0.97 : 0.9;

    if (hasAnimationOverlay) {
      strokeWidth = 1 + strength * 5 + activityIntensity * 8;
      strokeColor =
        activityIntensity > 0
          ? FLOW_COLORS.activeStroke(0.68 + activityIntensity * 0.28)
          : strokeColor;
      opacity = 0.68 + Math.max(activityIntensity * 0.28, strength * 0.16);
    }
    if (isSelected) {
      strokeWidth += 2.4;
      strokeColor = FLOW_COLORS.backboneStroke(0.98);
      opacity = 1;
    }

    const path = svgElement("path", {
      d: geometry.d,
      fill: "none",
      stroke: strokeColor,
      "stroke-width": strokeWidth,
      opacity,
      "marker-end": "url(#generic-arrowhead)",
      "data-map-selectable": supportsPathSelection ? "true" : "false",
    });
    if (supportsPathSelection) {
      path.style.cursor = "pointer";
      path.addEventListener("click", (event) => {
        event.stopPropagation();
        setMapSelection({
          type: "path",
          view: "handoff_activity",
          source: String(edge.source),
          target: String(edge.target),
        });
      });
    }
    appendSvgTitle(
      path,
      `${edge.source} -> ${edge.target}\n${summaryContext.edgeSingular}: ${formatNumber(value)}\nMedian wait: ${formatDuration(edge.median_duration_seconds)}`
    );
    edgeLayer.appendChild(path);

    if (hasAnimationOverlay && activeCount > 0) {
      appendAnimatedCaseDots(pulseLayer, geometry, activeCount, activityIntensity, pulseT);
    }

    if (index < 26) {
      const labelText =
        state.mode === "frequency"
          ? hasAnimationOverlay
            ? `${formatNumber(activeCount)} / ${formatNumber(value)}`
            : formatNumber(value)
          : formatDuration(edge.median_duration_seconds);
      let lx, ly, textAnchor;
      const isSplit = (sourceOutDegreeHandoff.get(String(edge.source)) || 0) > 1;
      if (isSplit || !geometry.waypoints) {
        const pos = geometryLabelPosition(geometry, source, target, 15);
        lx = pos.x; ly = pos.y; textAnchor = pos.textAnchor;
      } else {
        lx = Math.max(source.x, target.x) + 23;
        ly = (source.y + source.height / 2 + target.y - target.height / 2) / 2;
        textAnchor = "start";
      }
      edgeLabelItems.push({ x: lx, y: ly, yOffset: 0, text: labelText, fontSize: 12, textAnchor, edge, source, target, supportsPathSelection });
    }
  });

  simplified.nodes.forEach((node) => {
    const point = positionedNodes.get(String(node.id));
    if (!point) {
      return;
    }

    const scale = Math.max(Number(node.frequency || 0) / maxNodeFrequency, 0.08);
    const nodeDuration = Number(node.total_duration_seconds || 0);
    const durationHeat = clamp(nodeDuration / nodeMaxDuration, 0, 1);
    const isPerformanceMode = state.mode === "performance";
    const fillOpacity = 0.12 + scale * 0.86;
    const nodeFill = isPerformanceMode
      ? twoStopHeat(
          FLOW_COLORS.performanceNodeLow,
          FLOW_COLORS.performanceNodeMid,
          FLOW_COLORS.performanceNodeHigh,
          Math.pow(durationHeat, 0.7)
        )
      : twoStopHeat(FLOW_COLORS.frequencyNodeLow, FLOW_COLORS.frequencyNodeMid, FLOW_COLORS.frequencyNodeHigh, Math.pow(scale, 0.7));
    const textColor = isPerformanceMode
      ? durationHeat > 0.64 ? "#ffffff" : "#08152a"
      : Math.pow(scale, 0.7) > 0.5 ? "#ffffff" : "#001033";
    const isActivityView = viewKey === "handoff_activity";
    const isActorView = viewKey === "handoff_actor";
    const isSelected = isActivityView
      ? isSelectedMapActivity(node.id, "handoff_activity")
      : isActorView
        ? isSelectedMapActor(node.id)
        : false;
    const group = svgElement("g", {
      "data-map-selectable": isActivityView || isActorView ? "true" : "false",
    });
    if (isActivityView || isActorView) {
      group.style.cursor = "pointer";
      group.addEventListener("click", (event) => {
        event.stopPropagation();
        setMapSelection(
          isActivityView
            ? {
                type: "activity",
                view: "handoff_activity",
                value: String(node.id),
              }
            : {
                type: "actor",
                view: "handoff_actor",
                value: String(node.id),
              }
        );
      });
    }

    group.appendChild(
      svgElement("rect", {
        x: point.x - point.width / 2,
        y: point.y - point.height / 2,
        width: point.width,
        height: point.height,
        rx: 12,
        fill: nodeFill,
        stroke: isSelected ? "#000000" : "rgba(0, 51, 153, 0.34)",
        "stroke-width": isSelected ? 3 : 1.6,
      })
    );

    const labelFontSize = isActorView ? 15 : 12;
    const lineH = isActorView ? 20 : 17;
    const statGap = 16;
    const labelLines = wrapActivityLabel(String(node.label || node.id), point.width, labelFontSize);
    const firstLabelY = Math.round(point.y - ((labelLines.length - 1) * lineH + statGap - 8) / 2);
    const statY = firstLabelY + (labelLines.length - 1) * lineH + statGap;
    const label = svgElement("text", {
      "text-anchor": "middle",
      "font-size": labelFontSize,
      "font-family": "Space Grotesk, sans-serif",
      "font-weight": 700,
      fill: textColor,
    });
    labelLines.forEach((line, i) => {
      const tspan = svgElement("tspan", { x: point.x, y: firstLabelY + i * lineH });
      tspan.textContent = line;
      label.appendChild(tspan);
    });
    group.appendChild(label);

    const stat = svgElement("text", {
      x: point.x,
      y: statY,
      "text-anchor": "middle",
      "font-size": isActorView ? 13 : 11,
      "font-family": "IBM Plex Mono, monospace",
      fill: textColor,
    });
    stat.textContent = formatNumber(node.frequency || 0);
    group.appendChild(stat);

    appendSvgTitle(
      label,
      `${node.label || node.id}\nVolume: ${formatNumber(node.frequency || 0)}`
    );
    nodeLayer.appendChild(group);
  });

  setProcessMapSummary(
    `Showing ${formatNumber(simplified.nodes.length)} of ${formatNumber(simplified.totalNodeCount)} ${summaryContext.nodePlural} and ${formatNumber(simplified.edges.length)} of ${formatNumber(simplified.totalEdgeCount)} ${summaryContext.edgePlural}. The dominant handoff backbone stays visible while the detail sliders simplify the network.`
  );

  resolveEdgeLabelCollisions(edgeLabelItems);
  edgeLabelItems.forEach(({ x, y, yOffset, text, textAnchor, edge, source, target, supportsPathSelection }) => {
    const ly = y + yOffset;
    const label = svgElement("text", {
      x,
      y: ly,
      "text-anchor": textAnchor,
      "dominant-baseline": "central",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#111111",
      "data-map-selectable": supportsPathSelection ? "true" : "false",
    });
    if (supportsPathSelection) {
      label.style.cursor = "pointer";
      label.addEventListener("click", (evt) => {
        evt.stopPropagation();
        setMapSelection({ type: "path", view: "handoff_activity", source: String(edge.source), target: String(edge.target) });
      });
    }
    label.textContent = text;
    labelLayer.appendChild(label);
  });

  els.processMap.appendChild(guidesLayer);
  els.processMap.appendChild(edgeLayer);
  els.processMap.appendChild(pulseLayer);
  els.processMap.appendChild(nodeLayer);
  els.processMap.appendChild(labelLayer);
  applyMapZoom();
}

function bpmnOrthogonalPath(points, orientation = "ttb") {
  if (!points.length) return "";
  const r = 5;
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let index = 1; index < points.length; index += 1) {
    const prev = points[index - 1];
    const curr = points[index];
    if (Math.abs(prev.x - curr.x) < 1 || Math.abs(prev.y - curr.y) < 1) {
      d += ` L ${curr.x} ${curr.y}`;
      continue;
    }
    if (orientation === "ltr") {
      const midX = (prev.x + curr.x) / 2;
      const sx = curr.x > prev.x ? 1 : -1;
      const sy = curr.y > prev.y ? 1 : -1;
      const r1 = Math.min(r, Math.abs(midX - prev.x) / 2, Math.abs(curr.y - prev.y) / 2);
      const r2 = Math.min(r, Math.abs(curr.y - prev.y) / 2, Math.abs(curr.x - midX) / 2);
      d += ` L ${midX - sx * r1} ${prev.y}`;
      d += ` Q ${midX} ${prev.y} ${midX} ${prev.y + sy * r1}`;
      d += ` L ${midX} ${curr.y - sy * r2}`;
      d += ` Q ${midX} ${curr.y} ${midX + sx * r2} ${curr.y}`;
      d += ` L ${curr.x} ${curr.y}`;
    } else {
      const midY = (prev.y + curr.y) / 2;
      const sx = curr.x > prev.x ? 1 : -1;
      const sy = curr.y > prev.y ? 1 : -1;
      const r1 = Math.min(r, Math.abs(midY - prev.y) / 2, Math.abs(curr.x - prev.x) / 2);
      const r2 = Math.min(r, Math.abs(curr.x - prev.x) / 2, Math.abs(curr.y - midY) / 2);
      d += ` L ${prev.x} ${midY - sy * r1}`;
      d += ` Q ${prev.x} ${midY} ${prev.x + sx * r1} ${midY}`;
      d += ` L ${curr.x - sx * r2} ${midY}`;
      d += ` Q ${curr.x} ${midY} ${curr.x} ${midY + sy * r2}`;
      d += ` L ${curr.x} ${curr.y}`;
    }
  }
  return d;
}

function bpmnLabelPoint(points) {
  if (points.length < 2) {
    return points[0] || { x: 0, y: 0 };
  }
  const middleIndex = Math.floor(points.length / 2);
  const previous = points[middleIndex - 1] || points[0];
  const next = points[middleIndex] || points[points.length - 1];
  return {
    x: (previous.x + next.x) / 2,
    y: (previous.y + next.y) / 2,
  };
}

function bpmnGatewayDiamond(gateway) {
  const size = 17;
  return `${gateway.x} ${gateway.y - size} ${gateway.x + size} ${gateway.y} ${gateway.x} ${gateway.y + size} ${gateway.x - size} ${gateway.y}`;
}

function computeBpmnGateways(positionedNodes, edges, orientation = "ttb") {
  // Gateways are inferred from visible variation: multiple outgoing paths form
  // an XOR split, and multiple incoming paths form a merge before the task.
  // In LTR mode, split gateways appear to the right of source nodes and merge
  // gateways appear to the left of target nodes.
  const outgoing = new Map();
  const incoming = new Map();
  positionedNodes.forEach((node, nodeId) => {
    outgoing.set(nodeId, []);
    incoming.set(nodeId, []);
  });
  edges.forEach((edge) => {
    outgoing.get(edge.source)?.push(edge);
    incoming.get(edge.target)?.push(edge);
  });

  const isLTR = orientation === "ltr";
  const split = new Map();
  const merge = new Map();
  outgoing.forEach((items, nodeId) => {
    if (items.length <= 1) {
      return;
    }
    const node = positionedNodes.get(nodeId);
    if (!node) {
      return;
    }
    split.set(nodeId, {
      id: `split::${nodeId}`,
      type: "split",
      x: isLTR ? node.x + node.width / 2 + 48 : node.x,
      y: isLTR ? node.y : node.y + node.height / 2 + 48,
      degree: items.length,
      frequency: items.reduce((sum, edge) => sum + Number(edge.frequency || 0), 0),
    });
  });
  incoming.forEach((items, nodeId) => {
    if (items.length <= 1) {
      return;
    }
    const node = positionedNodes.get(nodeId);
    if (!node) {
      return;
    }
    merge.set(nodeId, {
      id: `merge::${nodeId}`,
      type: "merge",
      x: isLTR ? node.x - node.width / 2 - 48 : node.x,
      y: isLTR ? node.y : node.y - node.height / 2 - 48,
      degree: items.length,
      frequency: items.reduce((sum, edge) => sum + Number(edge.frequency || 0), 0),
    });
  });
  return { split, merge };
}

function bpmnFlowEdgeGeometry(edge, source, target, gateways, dimension, orientation = "ttb", bounds = {}) {
  const isLTR = orientation === "ltr";

  // Self-loops: keep bezier curve
  if (edge.source === edge.target) {
    const fallback = processEdgeGeometry(edge, source, target, dimension, orientation);
    return {
      d: fallback.d,
      labelPoint: cubicBezierPoint(0.5, fallback.points.x0, fallback.points.y0, fallback.points.cx1, fallback.points.cy1, fallback.points.cx2, fallback.points.cy2, fallback.points.x1, fallback.points.y1),
    };
  }

  // Same-stage in LTR: nodes share the same X column — straight vertical line between top/bottom ports
  if (isLTR && source.stage === target.stage) {
    const goUp = target.y < source.y;
    const srcPortY = goUp ? source.y - source.height / 2 : source.y + source.height / 2;
    const tgtPortY = goUp ? target.y + target.height / 2 : target.y - target.height / 2;
    return {
      d: `M ${source.x} ${srcPortY} L ${target.x} ${tgtPortY}`,
      labelPoint: { x: (source.x + target.x) / 2, y: (srcPortY + tgtPortY) / 2, direction: "vertical" },
    };
  }

  // Backward edges in LTR: orthogonal U-shape routed below all nodes with rounded corners
  if (isLTR && source.stage > target.stage) {
    const laneY = (bounds.maxNodeY || dimension - 80) + 60;
    const srcX = source.x;
    const tgtX = target.x;
    const srcBottomY = source.y + source.height / 2;
    const tgtBottomY = target.y + target.height / 2;
    const r = 5;
    const dirX = tgtX < srcX ? -1 : 1;
    const r1 = Math.min(r, (laneY - srcBottomY) / 2, Math.abs(srcX - tgtX) / 2);
    const r2 = Math.min(r, Math.abs(srcX - tgtX) / 2, (laneY - tgtBottomY) / 2);
    return {
      d: `M ${srcX} ${srcBottomY} L ${srcX} ${laneY - r1} Q ${srcX} ${laneY} ${srcX + dirX * r1} ${laneY} L ${tgtX - dirX * r2} ${laneY} Q ${tgtX} ${laneY} ${tgtX} ${laneY - r2} L ${tgtX} ${tgtBottomY}`,
      labelPoint: { x: (srcX + tgtX) / 2, y: laneY, direction: "arc" },
    };
  }

  // Non-LTR backward/same-stage: fall back to curved renderer
  if (source.stage >= target.stage) {
    const fallback = processEdgeGeometry(edge, source, target, dimension, orientation);
    return {
      d: fallback.d,
      labelPoint: cubicBezierPoint(0.5, fallback.points.x0, fallback.points.y0, fallback.points.cx1, fallback.points.cy1, fallback.points.cx2, fallback.points.cy2, fallback.points.x1, fallback.points.y1),
    };
  }

  // Skip-forward in LTR (skips ≥1 intermediate stage): travel right at source.y then descend near target
  // Descends at mergeGw.x rather than target.x to avoid passing through nodes in the same column as target
  if (isLTR && target.stage - source.stage > 1) {
    const splitGw = gateways.split.get(edge.source);
    const mergeGw = gateways.merge.get(edge.target);
    const startX = splitGw ? splitGw.x : source.x + source.width / 2;
    const endX = mergeGw ? mergeGw.x : target.x - target.width / 2 - 48;
    const srcY = source.y;
    const tgtY = target.y;
    const r = 5;
    const signY = tgtY > srcY ? 1 : tgtY < srcY ? -1 : 0;
    const r1 = Math.min(r, Math.abs(endX - startX) / 2, Math.abs(tgtY - srcY) / 2);
    const r2 = r1;
    let d = `M ${source.x + source.width / 2} ${srcY}`;
    if (splitGw) d += ` L ${startX} ${srcY}`;
    if (signY === 0) {
      d += ` L ${target.x - target.width / 2} ${tgtY}`;
    } else {
      d += ` L ${endX - r1} ${srcY}`;
      d += ` Q ${endX} ${srcY} ${endX} ${srcY + signY * r1}`;
      d += ` L ${endX} ${tgtY - signY * r2}`;
      d += ` Q ${endX} ${tgtY} ${endX + r2} ${tgtY}`;
      d += ` L ${target.x - target.width / 2} ${tgtY}`;
    }
    return {
      d,
      labelPoint: { x: (startX + endX) / 2, y: srcY },
    };
  }

  // Forward edges (adjacent stage): route through split/merge gateways with orthogonal connectors
  const points = isLTR
    ? [{ x: source.x + source.width / 2, y: source.y }]
    : [{ x: source.x, y: source.y + source.height / 2 }];
  const splitGateway = gateways.split.get(edge.source);
  const mergeGateway = gateways.merge.get(edge.target);
  if (splitGateway) {
    points.push({ x: splitGateway.x, y: splitGateway.y });
  }
  if (mergeGateway) {
    points.push({ x: mergeGateway.x, y: mergeGateway.y });
  }
  if (isLTR) {
    points.push({ x: target.x - target.width / 2, y: target.y });
  } else {
    points.push({ x: target.x, y: target.y - target.height / 2 });
  }

  // In LTR, anchor label at the source node's right edge (not the gateway) so it
  // sits as far left as possible. textAnchor="start" means text grows rightward
  // away from the node. y offsets of ±60/50 keep the two-line label clear of
  // the gateway diamond (half-size 17px, spans source.y ± 17).
  let forwardLabelPoint;
  if (isLTR) {
    forwardLabelPoint = {
      x: source.x + source.width / 2 + 20,
      y: source.y,
      direction: target.y > source.y + 20 ? "below" : "above",
    };
  } else {
    forwardLabelPoint = bpmnLabelPoint(points);
  }

  return {
    d: bpmnOrthogonalPath(points, orientation),
    labelPoint: forwardLabelPoint,
  };
}

function renderBpmnFlowDiagram(flowchart) {
  // This replaces the old swimlane renderer. Activities are normalized to one
  // task node each, while gateway diamonds show where visible variants split
  // and merge in a more traditional BPMN-like process view.
  els.processMap.innerHTML = "";
  updateProcessDetailLabels();
  if (!flowchart?.available || !flowchart.nodes?.length) {
    setProcessMapSummary("No BPMN flowchart data available for current filters.");
    renderEmptyMap("No BPMN flowchart data available for current filters.");
    return;
  }

  const sourceNodes = flowchart.nodes || [];
  const sourceEdges = flowchart.edges || [];
  const simplified = sourceEdges.length
    ? simplifyProcessGraph(sourceNodes, sourceEdges)
    : {
        nodes: sourceNodes.slice(0, 40),
        edges: [],
        totalNodeCount: sourceNodes.length,
        totalEdgeCount: 0,
        backbone: { nodeIds: new Set(), edgeKeys: new Set() },
      };
  if (!simplified.nodes.length) {
    setProcessMapSummary("The current activity/path detail settings hide all BPMN flow nodes.");
    renderEmptyMap("Raise activity or path detail to show the BPMN flow.");
    return;
  }

  const layout = computeProcessLayout(simplified.nodes, simplified.edges, {
    orientation: "ltr",
    minWidth: 1200,
    minHeight: 700,
    topPad: 300,
    bottomPad: 280,
    leftPad: 90,
    rightPad: 90,
    minStageGap: 400,
    stageGapBase: 340,
    horizontalGap: 160,
    protectLoopTop: true,
    nodeWidthScale: 1.25,
  });
  const width = layout.width;
  const height = layout.height;
  els.processMap.setAttribute("viewBox", `0 0 ${width} ${height}`);
  els.processMap.style.aspectRatio = `${width} / ${height}`;

  const defs = svgElement("defs");
  const marker = svgElement("marker", {
    id: "bpmn-arrowhead",
    viewBox: "0 0 10 10",
    refX: 10,
    refY: 5,
    markerUnits: "userSpaceOnUse",
    markerWidth: 27,
    markerHeight: 27,
    orient: "auto-start-reverse",
  });
  marker.appendChild(
    svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: FLOW_COLORS.edgeMarker })
  );
  defs.appendChild(marker);
  els.processMap.appendChild(defs);

  const positionedNodes = layout.positionedNodes;
  const gateways = computeBpmnGateways(positionedNodes, simplified.edges, "ltr");
  const edgeMaxFrequency = Math.max(
    ...simplified.edges.map((edge) => Number(edge.frequency || 0)),
    1
  );
  const edgeMaxDuration = Math.max(
    ...simplified.edges.map((edge) => Number(edge.total_duration_seconds || 0)),
    1
  );
  const nodeMaxFrequency = Math.max(
    ...simplified.nodes.map((node) => Number(node.frequency || 0)),
    1
  );
  const nodeMaxDuration = Math.max(
    ...simplified.nodes.map((node) => Number(node.total_duration_seconds || 0)),
    1
  );

  const backdropLayer = svgElement("g");
  const edgeLayer = svgElement("g");
  const gatewayLayer = svgElement("g");
  const labelLayer = svgElement("g");
  const eventLayer = svgElement("g");
  const nodeLayer = svgElement("g");

  for (let stage = 0; stage <= layout.maxStage; stage += 1) {
    const x = layout.stageXs.get(stage) || width / 2;
    backdropLayer.appendChild(
      svgElement("line", {
        x1: x,
        y1: 44,
        x2: x,
        y2: height - 44,
        stroke: "rgba(0, 0, 0, 0.045)",
        "stroke-width": 1,
      })
    );
  }

  const startEvent = { x: 58, y: height / 2, r: 22 };
  const endEvent = { x: width - 58, y: height / 2, r: 22 };
  eventLayer.appendChild(
    svgElement("circle", {
      cx: startEvent.x,
      cy: startEvent.y,
      r: startEvent.r,
      fill: "#ffffff",
      stroke: "#003399",
      "stroke-width": 3,
    })
  );
  eventLayer.appendChild(
    svgElement("circle", {
      cx: endEvent.x,
      cy: endEvent.y,
      r: endEvent.r,
      fill: "#ffffff",
      stroke: "#000000",
      "stroke-width": 4,
    })
  );
  [
    { label: "START", x: startEvent.x, y: startEvent.y + 54, color: "#003399" },
    { label: "END", x: endEvent.x, y: endEvent.y + 54, color: "#000000" },
  ].forEach((item) => {
    const text = svgElement("text", {
      x: item.x,
      y: item.y,
      "text-anchor": "middle",
      "font-size": 25,
      "font-family": "IBM Plex Mono, monospace",
      "font-weight": 700,
      fill: item.color,
    });
    text.textContent = item.label;
    eventLayer.appendChild(text);
  });

  const topStartCount = Math.max(...simplified.nodes.map((node) => Number(node.start_count || 0)), 1);
  const topEndCount = Math.max(...simplified.nodes.map((node) => Number(node.end_count || 0)), 1);
  simplified.nodes
    .filter((node) => Number(node.start_count || 0) > 0)
    .forEach((node) => {
      const target = positionedNodes.get(node.id);
      if (!target) {
        return;
      }
      const strength = Math.max(Number(node.start_count || 0) / topStartCount, 0.08);
      const d = bpmnOrthogonalPath([
        { x: startEvent.x + startEvent.r, y: startEvent.y },
        { x: target.x - target.width / 2, y: target.y },
      ], "ltr");
      edgeLayer.appendChild(
        svgElement("path", {
          d,
          fill: "none",
          stroke: FLOW_COLORS.anchorStroke(0.42 + strength * 0.4),
          "stroke-width": 1.4 + strength * 5,
          opacity: 0.9,
          "marker-end": "url(#bpmn-arrowhead)",
        })
      );
    });
  simplified.nodes
    .filter((node) => Number(node.end_count || 0) > 0)
    .forEach((node) => {
      const source = positionedNodes.get(node.id);
      if (!source) {
        return;
      }
      const strength = Math.max(Number(node.end_count || 0) / topEndCount, 0.08);
      const d = bpmnOrthogonalPath([
        { x: source.x + source.width / 2, y: source.y },
        { x: endEvent.x - endEvent.r, y: endEvent.y },
      ], "ltr");
      edgeLayer.appendChild(
        svgElement("path", {
          d,
          fill: "none",
          stroke: FLOW_COLORS.anchorStroke(0.42 + strength * 0.4),
          "stroke-width": 1.4 + strength * 5,
          opacity: 0.9,
          "marker-end": "url(#bpmn-arrowhead)",
        })
      );
    });

  const bpmnBounds = {
    maxNodeY: Math.max(...[...positionedNodes.values()].map((n) => n.y + n.height / 2)),
    minNodeY: Math.min(...[...positionedNodes.values()].map((n) => n.y - n.height / 2)),
  };

  // Backward arcs descend to maxNodeY+60; their labels sit at maxNodeY+68 with a
  // sub-line ~29px below. Expand the viewBox downward if that exceeds the layout height.
  const arcFloor = bpmnBounds.maxNodeY + 110;
  if (arcFloor > height) {
    els.processMap.setAttribute("viewBox", `0 0 ${width} ${arcFloor}`);
    els.processMap.style.aspectRatio = `${width} / ${arcFloor}`;
  }

  const bpmnEdgeLabelItems = [];
  simplified.edges.slice(0, 320).forEach((edge, index) => {
    const source = positionedNodes.get(edge.source);
    const target = positionedNodes.get(edge.target);
    if (!source || !target) {
      return;
    }

    const frequencyStrength = visualStrength(edge.frequency, edgeMaxFrequency, 0.05);
    const totalDuration = Number(edge.total_duration_seconds || 0);
    const durationStrength = visualStrength(totalDuration, edgeMaxDuration, 0.04);
    const durationHeat = clamp(totalDuration / edgeMaxDuration, 0, 1);
    const strength = state.mode === "performance" ? durationStrength : frequencyStrength;
    const isBackbone = simplified.backbone.edgeKeys.has(processEdgeKey(edge.source, edge.target));
    const isSelected = isSelectedMapPath(edge.source, edge.target, "swimlane");
    const geometry = bpmnFlowEdgeGeometry(edge, source, target, gateways, height, "ltr", bpmnBounds);
    const path = svgElement("path", {
      d: geometry.d,
      fill: "none",
      stroke: isSelected
        ? "#000000"
        : state.mode === "performance"
          ? twoStopHeat(
              FLOW_COLORS.performanceEdgeLow,
              FLOW_COLORS.performanceEdgeMid,
              FLOW_COLORS.performanceEdgeHigh,
              Math.pow(durationHeat, 0.72)
            )
          : isBackbone
            ? mixColor(FLOW_COLORS.frequencyEdgeLow, FLOW_COLORS.frequencyEdgeHigh, frequencyStrength)
            : mixColor(FLOW_COLORS.frequencyEdgeLow, FLOW_COLORS.frequencyEdgeHigh, frequencyStrength * 0.86),
      "stroke-width": (1.5 + strength * 10 + (isBackbone ? 1.4 : 0) + (isSelected ? 2.2 : 0)) * 0.65,
      opacity: isBackbone || isSelected ? 0.98 : 0.84,
      "marker-end": "url(#bpmn-arrowhead)",
      "data-map-selectable": "true",
    });
    path.style.cursor = "pointer";
    path.addEventListener("click", (event) => {
      event.stopPropagation();
      setMapSelection({
        type: "path",
        view: "swimlane",
        source: String(edge.source),
        target: String(edge.target),
      });
    });
    appendSvgTitle(
      path,
      `${edge.source} -> ${edge.target}\nFrequency: ${formatNumber(edge.frequency)}\nCases: ${formatNumber(edge.case_frequency || 0)}\nShare after source: ${formatPct(edge.outgoing_share)}\nTotal wait: ${formatDuration(edge.total_duration_seconds)}\nMedian wait: ${formatDuration(edge.median_duration_seconds)}`
    );
    edgeLayer.appendChild(path);

    if (index < 32) {
      const lp = geometry.labelPoint;
      const isVerticalEdge = lp.direction === "vertical";
      const isArcEdge = lp.direction === "arc";
      const mainText = state.mode === "frequency"
        ? formatNumber(edge.frequency)
        : formatDuration(edge.total_duration_seconds);
      const subText = state.mode === "frequency" ? formatPct(edge.outgoing_share) : null;
      const isDirectional = lp.direction === "above" || lp.direction === "below";
      const labelY = isVerticalEdge ? lp.y
        : isArcEdge ? lp.y + 30
        : lp.direction === "below" ? lp.y + 50
        : lp.y - 60;
      bpmnEdgeLabelItems.push({
        x: isVerticalEdge ? lp.x + 28 : lp.x,
        y: labelY,
        text: mainText,
        subText,
        fontSize: 22,
        textAnchor: isVerticalEdge || isDirectional ? "start" : "middle",
        yOffset: 0,
        isVerticalEdge,
        edge,
      });
    }
  });

  resolveEdgeLabelCollisions(bpmnEdgeLabelItems.filter((item) => !item.isVerticalEdge));
  bpmnEdgeLabelItems.forEach(({ x, y, yOffset, text, subText, fontSize, textAnchor, edge }) => {
    const ly = y + yOffset;
    const label = svgElement("text", {
      x,
      y: ly,
      "text-anchor": textAnchor,
      "font-size": fontSize,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#111111",
      "data-map-selectable": "true",
    });
    label.style.cursor = "pointer";
    if (subText) {
      const line1 = svgElement("tspan", { x, dy: "0" });
      line1.textContent = text;
      const line2 = svgElement("tspan", { x, dy: "1.3em" });
      line2.textContent = subText;
      label.appendChild(line1);
      label.appendChild(line2);
    } else {
      label.textContent = text;
    }
    label.addEventListener("click", (event) => {
      event.stopPropagation();
      setMapSelection({
        type: "path",
        view: "swimlane",
        source: String(edge.source),
        target: String(edge.target),
      });
    });
    labelLayer.appendChild(label);
  });

  [...gateways.split.values(), ...gateways.merge.values()].forEach((gateway) => {
    const diamond = svgElement("polygon", {
      points: bpmnGatewayDiamond(gateway),
      fill: "#ffffff",
      stroke: "#003399",
      "stroke-width": 2.2,
    });
    appendSvgTitle(
      diamond,
      `${gateway.type === "split" ? "Branch" : "Merge"} gateway\nPaths: ${formatNumber(gateway.degree)}\nEvents: ${formatNumber(gateway.frequency)}`
    );
    gatewayLayer.appendChild(diamond);
    const label = svgElement("text", {
      x: gateway.x,
      y: gateway.y + 4,
      "text-anchor": "middle",
      "font-size": 13,
      "font-family": "IBM Plex Mono, monospace",
      "font-weight": 700,
      fill: "#003399",
    });
    label.textContent = "X";
    gatewayLayer.appendChild(label);
  });

  positionedNodes.forEach((point, nodeId) => {
    const node = point;
    const frequencyScale = visualStrength(node.frequency, nodeMaxFrequency, 0.08);
    const totalDuration = Number(node.total_duration_seconds || 0);
    const durationHeat = clamp(totalDuration / nodeMaxDuration, 0, 1);
    const isPerformanceMode = state.mode === "performance";
    const fill = isPerformanceMode
      ? twoStopHeat(
          FLOW_COLORS.performanceNodeLow,
          FLOW_COLORS.performanceNodeMid,
          FLOW_COLORS.performanceNodeHigh,
          Math.pow(durationHeat, 0.7)
        )
      : mixColor(FLOW_COLORS.frequencyNodeLow, FLOW_COLORS.frequencyNodeHigh, frequencyScale);
    const textColor = isPerformanceMode
      ? durationHeat > 0.64
        ? "#ffffff"
        : "#08152a"
      : frequencyScale > 0.62
        ? "#ffffff"
        : "#08152a";
    const isSelected = isSelectedMapActivity(nodeId, "swimlane");
    const group = svgElement("g", { "data-map-selectable": "true" });
    group.style.cursor = "pointer";
    group.addEventListener("click", (event) => {
      event.stopPropagation();
      setMapSelection({
        type: "activity",
        view: "swimlane",
        value: String(nodeId),
      });
    });

    group.appendChild(
      svgElement("rect", {
        x: node.x - node.width / 2,
        y: node.y - node.height / 2,
        width: node.width,
        height: node.height,
        rx: 9,
        fill: isSelected ? "rgba(0, 51, 153, 0.16)" : fill,
        stroke: isSelected ? "#000000" : "#003399",
        "stroke-width": isSelected ? 3 : 1.8 + frequencyScale * 1.4,
      })
    );
    group.appendChild(
      svgElement("rect", {
        x: node.x - node.width / 2,
        y: node.y - node.height / 2,
        width: 7,
        height: node.height,
        rx: 4,
        fill: "#003399",
        opacity: 0.8,
      })
    );

    const labelLines = wrapActivityLabel(node.label || "", node.width, 30);
    const lineH = 36;
    const statGap = 38;
    const firstLabelY = Math.round(node.y - ((labelLines.length - 1) * lineH + statGap + 19 - 17) / 2);
    const statY = firstLabelY + (labelLines.length - 1) * lineH + statGap;
    const labelEl = svgElement("text", {
      "text-anchor": "middle",
      "font-size": 30,
      "font-family": "Space Grotesk, sans-serif",
      "font-weight": 700,
      fill: textColor,
    });
    labelLines.forEach((line, i) => {
      const tspan = svgElement("tspan", { x: node.x, y: firstLabelY + i * lineH });
      tspan.textContent = line;
      labelEl.appendChild(tspan);
    });
    group.appendChild(labelEl);

    const stat = svgElement("text", {
      "text-anchor": "middle",
      "font-size": 25,
      "font-family": "IBM Plex Mono, monospace",
      fill: textColor,
    });
    if (state.mode === "frequency") {
      const tspan1 = svgElement("tspan", { x: node.x, y: statY });
      tspan1.textContent = `${formatNumber(node.frequency)} events`;
      const tspan2 = svgElement("tspan", { x: node.x, y: statY + 24 });
      tspan2.textContent = `${formatPct(node.case_coverage)} cases`;
      stat.appendChild(tspan1);
      stat.appendChild(tspan2);
    } else {
      const tspan1 = svgElement("tspan", { x: node.x, y: statY });
      tspan1.textContent = formatDuration(totalDuration);
      stat.appendChild(tspan1);
    }
    group.appendChild(stat);

    appendSvgTitle(
      group,
      `${node.label}\nEvents: ${formatNumber(node.frequency)}\nCases: ${formatNumber(node.case_frequency || 0)} (${formatPct(node.case_coverage)})\nTotal activity duration: ${formatDuration(node.total_duration_seconds)}\nStarts: ${formatNumber(node.start_count || 0)}\nEnds: ${formatNumber(node.end_count || 0)}`
    );
    nodeLayer.appendChild(group);
  });

  setProcessMapSummary(
    `BPMN flow shows ${formatNumber(simplified.nodes.length)} of ${formatNumber(simplified.totalNodeCount)} normalized activities and ${formatNumber(simplified.edges.length)} of ${formatNumber(simplified.totalEdgeCount)} paths. Gateway diamonds mark visible branch and merge variation; line width shows path volume.`
  );

  els.processMap.appendChild(backdropLayer);
  els.processMap.appendChild(edgeLayer);
  els.processMap.appendChild(gatewayLayer);
  els.processMap.appendChild(eventLayer);
  els.processMap.appendChild(nodeLayer);
  els.processMap.appendChild(labelLayer);
  applyMapZoom();
}

function renderSankeyDiagram(sankey) {
  // Sankey makes volume immediately visible by varying path width between
  // staged activity columns.
  els.processMap.innerHTML = "";
  if (!sankey?.available || !sankey.nodes?.length || !sankey.links?.length) {
    renderEmptyMap("No sankey data available for current filters.");
    return;
  }

  const width = 1200;
  const height = 760;
  els.processMap.setAttribute("viewBox", `0 0 ${width} ${height}`);
  els.processMap.style.aspectRatio = `${width} / ${height}`;
  const topPad = 24;
  const bottomPad = 70;
  const leftPad = 100;
  const rightPad = 100;

  const maxStage = Math.max(...sankey.nodes.map((node) => Number(node.stage || 0)), 0);
  const stageGroups = new Map();
  sankey.nodes.forEach((node) => {
    const stage = Number(node.stage || 0);
    if (!stageGroups.has(stage)) {
      stageGroups.set(stage, []);
    }
    stageGroups.get(stage).push(node);
  });
  stageGroups.forEach((group) =>
    group.sort((a, b) => Number(b.frequency || 0) - Number(a.frequency || 0))
  );

  const nodeCoords = new Map();
  const stageWidth = (width - leftPad - rightPad) / Math.max(maxStage, 1);
  stageGroups.forEach((group, stage) => {
    const x = leftPad + (maxStage === 0 ? 0 : stage * stageWidth);
    const count = Math.max(group.length, 1);
    group.forEach((node, index) => {
      const y = topPad + ((index + 0.5) * (height - topPad - bottomPad)) / count;
      nodeCoords.set(node.id, { x, y, node, stage });
    });
  });

  const maxFlow = Math.max(...sankey.links.map((link) => Number(link.value || 0)), 1);
  const edgeLayer = svgElement("g");
  const nodeLayer = svgElement("g");
  const labelLayer = svgElement("g");

  sankey.links.slice(0, 300).forEach((link) => {
    const source = nodeCoords.get(link.source);
    const target = nodeCoords.get(link.target);
    if (!source || !target) {
      return;
    }
    const strength = Math.max(Number(link.value || 0) / maxFlow, 0.05);
    const path = svgElement("path", {
      d: `M ${source.x + 14} ${source.y} C ${source.x + 120} ${source.y}, ${target.x - 120} ${target.y}, ${target.x - 14} ${target.y}`,
      fill: "none",
      stroke: twoStopHeat(FLOW_COLORS.frequencyEdgeLow, FLOW_COLORS.frequencyEdgeMid, FLOW_COLORS.frequencyEdgeHigh, strength),
      "stroke-width": 1 + strength * 16,
      opacity: 0.7 + strength * 0.22,
    });
    edgeLayer.appendChild(path);
  });

  nodeCoords.forEach(({ x, y, node, stage }) => {
    nodeLayer.appendChild(
      svgElement("rect", {
        x: x - 14,
        y: y - 18,
        width: 28,
        height: 36,
        rx: 5,
        fill: "#0A7CC1",
        stroke: "#ffffff",
        "stroke-width": 2,
      })
    );
    const isFirst = stage === 0;
    const isLast = stage === maxStage;
    const anchor = isFirst ? "start" : isLast ? "end" : "middle";
    const labelX = isFirst ? x - 14 : isLast ? x + 14 : x;
    const label = svgElement("text", {
      x: labelX,
      y: y + 30,
      "text-anchor": anchor,
      "font-size": 11,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#000000",
    });
    const nameLine = svgElement("tspan", { x: labelX, dy: "0" });
    nameLine.textContent = node.label;
    const countLine = svgElement("tspan", { x: labelX, dy: "1.3em" });
    countLine.textContent = `(${formatNumber(node.frequency || 0)})`;
    label.appendChild(nameLine);
    label.appendChild(countLine);
    labelLayer.appendChild(label);
  });

  els.processMap.appendChild(edgeLayer);
  els.processMap.appendChild(nodeLayer);
  els.processMap.appendChild(labelLayer);
  applyMapZoom();
}

function renderReworkDiagram(rework) {
  // Compact bar-chart view for repeated activities. The treemap tab below is
  // better for visual volume comparison; this one preserves ranked labels.
  els.processMap.innerHTML = "";
  const activities = rework?.activities || [];
  if (!activities.length) {
    renderEmptyMap("No rework hotspots detected for current filters.");
    return;
  }

  const width = 1200;
  const height = 760;
  els.processMap.setAttribute("viewBox", `0 0 ${width} ${height}`);
  els.processMap.style.aspectRatio = `${width} / ${height}`;
  const topPad = 40;
  const bottomPad = 50;
  const leftPad = 220;
  const rightPad = 40;

  const rows = activities.slice(0, 16);
  const maxRework = Math.max(...rows.map((row) => Number(row.rework_events || 0)), 1);
  const rowHeight = (height - topPad - bottomPad) / Math.max(rows.length, 1);

  const axisLayer = svgElement("g");
  const barLayer = svgElement("g");
  const textLayer = svgElement("g");

  rows.forEach((row, index) => {
    const y = topPad + index * rowHeight + rowHeight / 2;
    const value = Number(row.rework_events || 0);
    const widthScale = (value / maxRework) * (width - leftPad - rightPad);
    const intensity = Math.max(value / maxRework, 0.08);

    barLayer.appendChild(
      svgElement("rect", {
        x: leftPad,
        y: y - 12,
        width: Math.max(widthScale, 2),
        height: 24,
        rx: 6,
        fill: twoStopHeat(FLOW_COLORS.frequencyNodeLow, FLOW_COLORS.frequencyNodeMid, FLOW_COLORS.frequencyNodeHigh, intensity),
        opacity: 0.86,
      })
    );

    const nameText = svgElement("text", {
      x: leftPad - 10,
      y: y + 4,
      "text-anchor": "end",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#000000",
    });
    nameText.textContent = row.activity;
    textLayer.appendChild(nameText);

    const valueText = svgElement("text", {
      x: leftPad + widthScale + 8,
      y: y + 4,
      "text-anchor": "start",
      "font-size": 11,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#000000",
    });
    valueText.textContent = `${formatNumber(value)} rework events | ${formatPct(
      row.rework_case_ratio
    )}`;
    textLayer.appendChild(valueText);
  });

  axisLayer.appendChild(
    svgElement("line", {
      x1: leftPad,
      y1: topPad - 8,
      x2: leftPad,
      y2: height - bottomPad + 8,
      stroke: "rgba(0,0,0,0.18)",
      "stroke-width": 1.5,
    })
  );

  els.processMap.appendChild(axisLayer);
  els.processMap.appendChild(barLayer);
  els.processMap.appendChild(textLayer);
  applyMapZoom();
}

function renderQueueAgeHeatmap(heatmap) {
  // Heatmap cells show median wait from an activity to its next activity within
  // a time bucket. It is designed to spot queue-age drift over the log period.
  els.processMap.innerHTML = "";
  const rows = heatmap?.rows || [];
  const buckets = heatmap?.buckets || [];
  const cells = heatmap?.cells || [];
  if (!heatmap?.available || !rows.length || !buckets.length || !cells.length) {
    renderEmptyMap("No queue age heatmap data for current filters.");
    return;
  }

  const width = 1200;
  const height = 760;
  els.processMap.setAttribute("viewBox", `0 0 ${width} ${height}`);
  els.processMap.style.aspectRatio = `${width} / ${height}`;

  const leftPad = 250;
  const rightPad = 42;
  const topPad = 96;
  const bottomPad = 66;
  const plotWidth = width - leftPad - rightPad;
  const plotHeight = height - topPad - bottomPad;
  const rowHeight = plotHeight / Math.max(rows.length, 1);
  const colWidth = plotWidth / Math.max(buckets.length, 1);
  const maxMedian = Math.max(
    ...cells.map((cell) => Number(cell.median_duration_seconds || 0)),
    1
  );
  const cellByKey = new Map(
    cells.map((cell) => [`${cell.activity}|||${cell.bucket_index}`, cell])
  );

  const title = svgElement("text", {
    x: leftPad,
    y: 38,
    "font-size": 20,
    "font-family": "IBM Plex Mono, monospace",
    "font-weight": 800,
    fill: "#000000",
  });
  title.textContent = "Queue Age Heatmap";
  els.processMap.appendChild(title);

  const subtitle = svgElement("text", {
    x: leftPad,
    y: 62,
    "font-size": 12,
    "font-family": "IBM Plex Mono, monospace",
    fill: "rgba(0,0,0,0.58)",
  });
  subtitle.textContent = "Darker cells indicate longer median waits before the next activity.";
  els.processMap.appendChild(subtitle);

  buckets.forEach((bucket, index) => {
    const x = leftPad + index * colWidth + colWidth / 2;
    const label = svgElement("text", {
      x,
      y: topPad - 18,
      "text-anchor": "middle",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "rgba(0,0,0,0.68)",
    });
    label.textContent = bucket.label || `Bucket ${index + 1}`;
    els.processMap.appendChild(label);
  });

  rows.forEach((row, rowIndex) => {
    const y = topPad + rowIndex * rowHeight;
    const centerY = y + rowHeight / 2;
    const activityLabel = svgElement("text", {
      x: leftPad - 14,
      y: centerY - 2,
      "text-anchor": "end",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#000000",
    });
    activityLabel.textContent = truncateProcessLabel(row.activity, 28);
    appendSvgTitle(activityLabel, String(row.activity || ""));
    els.processMap.appendChild(activityLabel);

    const rowMeta = svgElement("text", {
      x: leftPad - 14,
      y: centerY + 15,
      "text-anchor": "end",
      "font-size": 10,
      "font-family": "IBM Plex Mono, monospace",
      fill: "rgba(0,0,0,0.5)",
    });
    rowMeta.textContent = `${formatNumber(row.frequency || 0)} transitions`;
    els.processMap.appendChild(rowMeta);

    buckets.forEach((bucket, colIndex) => {
      const cell = cellByKey.get(`${row.activity}|||${bucket.index}`);
      const x = leftPad + colIndex * colWidth;
      const median = Number(cell?.median_duration_seconds || 0);
      const intensity = cell ? clamp(median / maxMedian, 0.08, 1) : 0;
      const rect = svgElement("rect", {
        x: x + 4,
        y: y + 4,
        width: Math.max(colWidth - 8, 1),
        height: Math.max(rowHeight - 8, 1),
        rx: 10,
        fill: cell
          ? twoStopHeat(FLOW_COLORS.frequencyNodeLow, FLOW_COLORS.frequencyNodeMid, FLOW_COLORS.frequencyNodeHigh, intensity)
          : "rgba(0,0,0,0.035)",
        stroke: cell ? "#8ACFF9" : "rgba(0,0,0,0.05)",
        "stroke-width": 1,
      });
      appendSvgTitle(
        rect,
        cell
          ? `${row.activity} | ${bucket.label}: median ${formatDuration(
              median
            )}, p90 ${formatDuration(cell.p90_duration_seconds)}, ${formatNumber(
              cell.frequency
            )} transitions`
          : `${row.activity} | ${bucket.label}: no transitions`
      );
      els.processMap.appendChild(rect);

      if (cell && colWidth > 76 && rowHeight > 42) {
        const valueText = svgElement("text", {
          x: x + colWidth / 2,
          y: centerY + 4,
          "text-anchor": "middle",
          "font-size": 11,
          "font-family": "IBM Plex Mono, monospace",
          "font-weight": 700,
          fill: intensity > 0.46 ? "#ffffff" : "#000000",
        });
        valueText.textContent = formatDuration(median);
        els.processMap.appendChild(valueText);
      }
    });
  });

  els.processMap.appendChild(
    svgElement("line", {
      x1: leftPad,
      y1: topPad - 8,
      x2: width - rightPad,
      y2: topPad - 8,
      stroke: "rgba(0,0,0,0.12)",
      "stroke-width": 1,
    })
  );
  applyMapZoom();
}

function binaryTreemapLayout(items, x, y, width, height, depth = 0) {
  // Small deterministic treemap layout with no external dependency. It splits
  // the remaining rectangle roughly in half by value, alternating orientation
  // based on available aspect ratio.
  if (!items.length) {
    return [];
  }
  if (items.length === 1) {
    return [{ ...items[0], x, y, width, height }];
  }

  const total = items.reduce((sum, item) => sum + item.value, 0);
  let running = 0;
  let splitIndex = 1;
  for (let index = 0; index < items.length - 1; index += 1) {
    running += items[index].value;
    splitIndex = index + 1;
    if (running >= total / 2) {
      break;
    }
  }

  const first = items.slice(0, splitIndex);
  const second = items.slice(splitIndex);
  const firstTotal = first.reduce((sum, item) => sum + item.value, 0);
  const ratio = total ? firstTotal / total : 0.5;
  const splitVertical = width >= height;

  if (splitVertical) {
    const firstWidth = width * ratio;
    return [
      ...binaryTreemapLayout(first, x, y, firstWidth, height, depth + 1),
      ...binaryTreemapLayout(second, x + firstWidth, y, width - firstWidth, height, depth + 1),
    ];
  }

  const firstHeight = height * ratio;
  return [
    ...binaryTreemapLayout(first, x, y, width, firstHeight, depth + 1),
    ...binaryTreemapLayout(second, x, y + firstHeight, width, height - firstHeight, depth + 1),
  ];
}

function renderReworkTreemap(treemap) {
  // Treemap area and opacity both encode rework event volume so the biggest
  // repeat-work consumers jump out quickly.
  els.processMap.innerHTML = "";
  const rows = (treemap?.activities || [])
    .map((activity) => ({
      ...activity,
      value: Number(activity.rework_events || 0),
    }))
    .filter((activity) => activity.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 18);

  if (!treemap?.available || !rows.length) {
    renderEmptyMap("No rework treemap data for current filters.");
    return;
  }

  const width = 1200;
  const height = 760;
  els.processMap.setAttribute("viewBox", `0 0 ${width} ${height}`);
  els.processMap.style.aspectRatio = `${width} / ${height}`;

  const title = svgElement("text", {
    x: 36,
    y: 38,
    "font-size": 20,
    "font-family": "IBM Plex Mono, monospace",
    "font-weight": 800,
    fill: "#000000",
  });
  title.textContent = "Rework Treemap";
  els.processMap.appendChild(title);

  const subtitle = svgElement("text", {
    x: 36,
    y: 62,
    "font-size": 12,
    "font-family": "IBM Plex Mono, monospace",
    fill: "rgba(0,0,0,0.58)",
  });
  subtitle.textContent = "Tile area and color intensity both represent repeated work volume.";
  els.processMap.appendChild(subtitle);

  const maxValue = Math.max(...rows.map((row) => row.value), 1);
  const tiles = binaryTreemapLayout(rows, 32, 90, width - 64, height - 124);
  tiles.forEach((tile) => {
    const intensity = clamp(tile.value / maxValue, 0.12, 1);
    const inset = 5;
    const rectWidth = Math.max(tile.width - inset * 2, 1);
    const rectHeight = Math.max(tile.height - inset * 2, 1);
    const rect = svgElement("rect", {
      x: tile.x + inset,
      y: tile.y + inset,
      width: rectWidth,
      height: rectHeight,
      rx: 16,
      fill: twoStopHeat(FLOW_COLORS.frequencyNodeLow, FLOW_COLORS.frequencyNodeMid, FLOW_COLORS.frequencyNodeHigh, intensity),
      stroke: "rgba(255,255,255,0.92)",
      "stroke-width": 2,
    });
    appendSvgTitle(
      rect,
      `${tile.activity}: ${formatNumber(tile.value)} rework events, ${formatNumber(
        tile.cases_with_rework || 0
      )} cases, ${formatPct(tile.rework_case_ratio)} of cases`
    );
    els.processMap.appendChild(rect);

    if (rectWidth < 92 || rectHeight < 46) {
      return;
    }

    const labelColor = intensity > 0.42 ? "#ffffff" : "#000000";
    const label = svgElement("text", {
      x: tile.x + inset + 14,
      y: tile.y + inset + 24,
      "font-size": rectWidth > 220 ? 15 : 12,
      "font-family": "IBM Plex Mono, monospace",
      "font-weight": 800,
      fill: labelColor,
    });
    label.textContent = truncateProcessLabel(tile.activity, rectWidth > 220 ? 30 : 18);
    els.processMap.appendChild(label);

    if (rectHeight > 72) {
      const value = svgElement("text", {
        x: tile.x + inset + 14,
        y: tile.y + inset + 45,
        "font-size": 12,
        "font-family": "IBM Plex Mono, monospace",
        fill: labelColor,
        opacity: 0.86,
      });
      value.textContent = `${formatNumber(tile.value)} rework events`;
      els.processMap.appendChild(value);
    }
  });
  applyMapZoom();
}

function renderVariantDurationBoxplot(boxplot) {
  // Boxplot compares duration spread among top variants. It complements the
  // variants table by showing volatility, not just median duration.
  els.processMap.innerHTML = "";
  const rows = (boxplot?.variants || []).slice(0, 12);
  if (!boxplot?.available || !rows.length) {
    renderEmptyMap("No variant duration boxplot data for current filters.");
    return;
  }

  const width = 1200;
  const height = 760;
  els.processMap.setAttribute("viewBox", `0 0 ${width} ${height}`);
  els.processMap.style.aspectRatio = `${width} / ${height}`;

  const leftPad = 300;
  const rightPad = 80;
  const topPad = 94;
  const bottomPad = 76;
  const plotWidth = width - leftPad - rightPad;
  const plotHeight = height - topPad - bottomPad;
  const rowHeight = plotHeight / Math.max(rows.length, 1);
  const maxDuration = Math.max(
    ...rows.map((row) => Number(row.max_duration_hours || 0)),
    1
  );
  const scaleX = (value) =>
    leftPad + (clamp(Number(value || 0), 0, maxDuration) / maxDuration) * plotWidth;

  const title = svgElement("text", {
    x: leftPad,
    y: 38,
    "font-size": 20,
    "font-family": "IBM Plex Mono, monospace",
    "font-weight": 800,
    fill: "#000000",
  });
  title.textContent = "Variant Duration Boxplot";
  els.processMap.appendChild(title);

  const subtitle = svgElement("text", {
    x: leftPad,
    y: 62,
    "font-size": 12,
    "font-family": "IBM Plex Mono, monospace",
    fill: "rgba(0,0,0,0.58)",
  });
  subtitle.textContent = "Box = Q1 to Q3, center line = median, whiskers = min to max.";
  els.processMap.appendChild(subtitle);

  for (let tick = 0; tick <= 4; tick += 1) {
    const value = (maxDuration * tick) / 4;
    const x = scaleX(value);
    els.processMap.appendChild(
      svgElement("line", {
        x1: x,
        y1: topPad - 12,
        x2: x,
        y2: height - bottomPad,
        stroke: "rgba(0,0,0,0.07)",
        "stroke-width": 1,
      })
    );
    const label = svgElement("text", {
      x,
      y: height - bottomPad + 30,
      "text-anchor": "middle",
      "font-size": 11,
      "font-family": "IBM Plex Mono, monospace",
      fill: "rgba(0,0,0,0.58)",
    });
    label.textContent = `${value.toFixed(value >= 10 ? 0 : 1)}h`;
    els.processMap.appendChild(label);
  }

  rows.forEach((row, index) => {
    const centerY = topPad + index * rowHeight + rowHeight / 2;
    const minX = scaleX(row.min_duration_hours);
    const q1X = scaleX(row.q1_duration_hours);
    const medianX = scaleX(row.median_duration_hours);
    const q3X = scaleX(row.q3_duration_hours);
    const maxX = scaleX(row.max_duration_hours);
    const boxHeight = Math.min(34, rowHeight * 0.56);

    if (index % 2 === 0) {
      els.processMap.appendChild(
        svgElement("rect", {
          x: 22,
          y: topPad + index * rowHeight + 2,
          width: width - 44,
          height: Math.max(rowHeight - 4, 1),
          rx: 10,
          fill: "rgba(197,231,252,0.22)",
        })
      );
    }

    const label = svgElement("text", {
      x: leftPad - 16,
      y: centerY - 2,
      "text-anchor": "end",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#000000",
    });
    label.textContent = `${row.rank}. ${truncateProcessLabel(row.variant, 31)}`;
    appendSvgTitle(label, row.variant);
    els.processMap.appendChild(label);

    const meta = svgElement("text", {
      x: leftPad - 16,
      y: centerY + 15,
      "text-anchor": "end",
      "font-size": 10,
      "font-family": "IBM Plex Mono, monospace",
      fill: "rgba(0,0,0,0.5)",
    });
    meta.textContent = `${formatNumber(row.cases || 0)} cases`;
    els.processMap.appendChild(meta);

    const whisker = svgElement("line", {
      x1: minX,
      y1: centerY,
      x2: maxX,
      y2: centerY,
      stroke: "#0A7CC1",
      "stroke-width": 4,
      "stroke-linecap": "round",
    });
    appendSvgTitle(
      whisker,
      `${row.variant}: min ${Number(row.min_duration_hours || 0).toFixed(
        2
      )}h, median ${Number(row.median_duration_hours || 0).toFixed(
        2
      )}h, max ${Number(row.max_duration_hours || 0).toFixed(2)}h`
    );
    els.processMap.appendChild(whisker);

    ["min_duration_hours", "max_duration_hours"].forEach((key) => {
      const x = scaleX(row[key]);
      els.processMap.appendChild(
        svgElement("line", {
          x1: x,
          y1: centerY - boxHeight / 2,
          x2: x,
          y2: centerY + boxHeight / 2,
          stroke: "#0A7CC1",
          "stroke-width": 2,
        })
      );
    });

    els.processMap.appendChild(
      svgElement("rect", {
        x: Math.min(q1X, q3X),
        y: centerY - boxHeight / 2,
        width: Math.max(Math.abs(q3X - q1X), 5),
        height: boxHeight,
        rx: 8,
        fill: "#0A7CC1",
        stroke: "#ffffff",
        "stroke-width": 2,
      })
    );

    els.processMap.appendChild(
      svgElement("line", {
        x1: medianX,
        y1: centerY - boxHeight / 2 - 5,
        x2: medianX,
        y2: centerY + boxHeight / 2 + 5,
        stroke: "#000000",
        "stroke-width": 3,
        "stroke-linecap": "round",
      })
    );

    const valueText = svgElement("text", {
      x: Math.min(maxX + 10, width - 18),
      y: centerY + 4,
      "font-size": 11,
      "font-family": "IBM Plex Mono, monospace",
      fill: "rgba(0,0,0,0.68)",
    });
    valueText.textContent = `med ${Number(row.median_duration_hours || 0).toFixed(1)}h`;
    els.processMap.appendChild(valueText);
  });

  applyMapZoom();
}

function renderEdgesTable(edges) {
  if (!edges.length) {
    els.edgesBody.innerHTML = '<tr><td colspan="3">No edges</td></tr>';
    return;
  }

  const rows = [...edges]
    .sort((a, b) => b.frequency - a.frequency)
    .slice(0, 200)
    .map(
      (edge) => `
        <tr>
          <td>${edge.source} -> ${edge.target}</td>
          <td>${formatNumber(edge.frequency)}</td>
          <td>${formatDuration(edge.median_duration_seconds)}</td>
        </tr>
      `
    )
    .join("");

  els.edgesBody.innerHTML = rows;
}

// ---------------------------------------------------------------------------
// Tables, view selection, and dashboard orchestration
// ---------------------------------------------------------------------------

function renderVariantsTable(variants) {
  if (!variants.length) {
    els.variantsBody.innerHTML = '<tr><td colspan="5">No variants</td></tr>';
    return;
  }

  els.variantsBody.innerHTML = variants
    .map(
      (variant) => `
        <tr>
          <td>${variant.rank}</td>
          <td>${variant.variant}</td>
          <td>${formatNumber(variant.cases)}</td>
          <td>${formatPct(variant.share)}</td>
          <td>${Number(variant.median_duration_hours || 0).toFixed(2)}</td>
        </tr>
      `
    )
    .join("");
}

function renderBottlenecks(bottlenecks) {
  if (!bottlenecks.length) {
    els.bottlenecksBody.innerHTML = '<tr><td colspan="4">No bottlenecks</td></tr>';
    return;
  }

  els.bottlenecksBody.innerHTML = bottlenecks
    .map(
      (edge) => `
        <tr>
          <td>${edge.source} -> ${edge.target}</td>
          <td>${formatDuration(edge.median_duration_seconds)}</td>
          <td>${formatDuration(edge.p90_duration_seconds)}</td>
          <td>${formatNumber(edge.frequency)}</td>
        </tr>
      `
    )
    .join("");
}

function renderActivityStats(stats) {
  if (!stats.length) {
    els.activitiesBody.innerHTML = '<tr><td colspan="3">No activity stats</td></tr>';
    return;
  }

  els.activitiesBody.innerHTML = stats
    .map(
      (row) => `
        <tr>
          <td>${row.activity}</td>
          <td>${formatNumber(row.frequency)}</td>
          <td>${formatPct(row.case_coverage)}</td>
        </tr>
      `
    )
    .join("");
}

function renderReworkTable(rework) {
  const rows = rework?.activities || [];
  if (!rows.length) {
    els.reworkBody.innerHTML = '<tr><td colspan="4">No rework hotspots</td></tr>';
    return;
  }

  els.reworkBody.innerHTML = rows
    .slice(0, 100)
    .map(
      (row) => `
        <tr>
          <td>${row.activity}</td>
          <td>${formatNumber(row.cases_with_rework)}</td>
          <td>${formatNumber(row.rework_events)}</td>
          <td>${formatPct(row.rework_case_ratio)}</td>
        </tr>
      `
    )
    .join("");
}

function renderRecommendations(recommendations) {
  if (!els.recommendationsList) {
    return;
  }

  const items = recommendations || [];
  if (!items.length) {
    els.recommendationsList.innerHTML = "<li>No additional recommendations.</li>";
    return;
  }

  els.recommendationsList.innerHTML = items
    .map((item) => `<li><strong>${item.title}:</strong> ${item.why}</li>`)
    .join("");
}

function renderInformationalColumns(profile) {
  if (!els.informationalBody) {
    return;
  }

  const rows = profile || [];
  if (!rows.length) {
    els.informationalBody.innerHTML = '<tr><td colspan="3">No informational columns configured</td></tr>';
    return;
  }

  els.informationalBody.innerHTML = rows
    .map((row) => {
      const topValues = (row.top_values || [])
        .map((value) => `${value.value} (${formatNumber(value.count)})`)
        .join(", ");
      return `
        <tr>
          <td>${row.column}</td>
          <td>${formatNumber(row.unique_values || 0)}</td>
          <td>${topValues || "-"}</td>
        </tr>
      `;
    })
    .join("");
}

function updateViewAvailability() {
  // Disable view buttons when the current filtered data cannot support them.
  // If filters invalidate the active view, fall back to the process map.
  const dashboard = state.dashboard || {};
  const handoffEnabled = Boolean(dashboard.handoff?.enabled);
  const swimlaneAvailable = Boolean(dashboard.swimlane?.available);
  const sankeyAvailable = Boolean(dashboard.sankey?.available);
  const reworkAvailable = Boolean((dashboard.rework?.activities || []).length);
  const extraViews = dashboard.extra_views || {};
  const queueHeatmapAvailable = Boolean(extraViews.queue_age_heatmap?.available);
  const reworkTreemapAvailable = Boolean(extraViews.rework_treemap?.available);
  const variantBoxplotAvailable = Boolean(extraViews.variant_duration_boxplot?.available);

  els.viewHandoffActor.disabled = !handoffEnabled;
  els.viewHandoffActivity.disabled = !handoffEnabled;
  els.viewSwimlane.disabled = !swimlaneAvailable;
  els.viewSankey.disabled = !sankeyAvailable;
  els.viewRework.disabled = !reworkAvailable;
  els.viewQueueHeatmap.disabled = !queueHeatmapAvailable;
  els.viewReworkTreemap.disabled = !reworkTreemapAvailable;
  els.viewVariantBoxplot.disabled = !variantBoxplotAvailable;

  const invalidCurrentView =
    (state.currentView === "handoff_actor" && !handoffEnabled) ||
    (state.currentView === "handoff_activity" && !handoffEnabled) ||
    (state.currentView === "swimlane" && !swimlaneAvailable) ||
    (state.currentView === "sankey" && !sankeyAvailable) ||
    (state.currentView === "rework" && !reworkAvailable) ||
    (state.currentView === "queue_heatmap" && !queueHeatmapAvailable) ||
    (state.currentView === "rework_treemap" && !reworkTreemapAvailable) ||
    (state.currentView === "variant_boxplot" && !variantBoxplotAvailable);

  if (invalidCurrentView) {
    state.currentView = "process";
  }
}

function setDiagramView(viewKey) {
  // View switches always stop the animation overlay so case dots do not linger
  // on static views or incompatible diagrams.
  FlowScope.info("VIEW", `Switching to "${viewKey}" view`);
  stopAnimation({ hideOverlay: true });
  state.currentView = viewKey;
  updateViewButtons();
  const t0 = performance.now();
  renderCurrentMap();
  FlowScope.debug_log("RENDER", `View "${viewKey}" rendered in ${(performance.now() - t0).toFixed(1)} ms`);
}

function renderCurrentMap() {
  // Single diagram router. Each renderer owns its own SVG viewBox and calls
  // applyMapZoom when it is done.
  if (!state.dashboard) {
    setProcessMapSummary("");
    renderMapSelectionPanel();
    renderEmptyMap("Upload a log to start.");
    return;
  }

  renderMapSelectionPanel();

  const structuredView = usesStructuredFlowView(state.currentView);
  const animatedView = viewSupportsAnimation(state.currentView);

  if (animatedView) {
    syncActiveAnimationView(false);
    updateAnimationTimeLabel();
  } else {
    stopAnimation();
    state.animation.frames = [];
    state.animation.maxEdgeCount = 0;
    updateAnimationTimeLabel();
  }

  const hasAnimationFrames = animatedView && state.animation.frames.length > 0;
  els.toggleAnimation.disabled = !hasAnimationFrames;
  els.restartAnimation.disabled = !hasAnimationFrames;
  els.stepBackAnimation.disabled = !hasAnimationFrames;
  els.stepForwardAnimation.disabled = !hasAnimationFrames;
  els.animationFrame.disabled = !hasAnimationFrames;
  els.animationSpeed.disabled = !hasAnimationFrames;
  if (els.activityDetail) {
    els.activityDetail.disabled = !structuredView;
  }
  if (els.pathDetail) {
    els.pathDetail.disabled = !structuredView;
  }

  if (!structuredView) {
    setProcessMapSummary("");
  }

  if (state.currentView === "process") {
    renderProcessMap(state.dashboard.nodes, state.dashboard.edges);
    return;
  }
  if (state.currentView === "handoff_actor") {
    renderGenericNetwork(
      state.dashboard.handoff?.actor_view?.nodes || [],
      state.dashboard.handoff?.actor_view?.edges || [],
      {
        viewKey: "handoff_actor",
        emptyMessage: "No actor handoff data for current filters.",
        summaryContext: detailControlContext("handoff_actor"),
      }
    );
    return;
  }
  if (state.currentView === "handoff_activity") {
    renderGenericNetwork(
      state.dashboard.handoff?.activity_view?.nodes || [],
      state.dashboard.handoff?.activity_view?.edges || [],
      {
        viewKey: "handoff_activity",
        emptyMessage: "No activity handoff data for current filters.",
        summaryContext: detailControlContext("handoff_activity"),
      }
    );
    return;
  }
  if (state.currentView === "swimlane") {
    renderBpmnFlowDiagram(state.dashboard.swimlane);
    return;
  }
  if (state.currentView === "sankey") {
    renderSankeyDiagram(state.dashboard.sankey);
    return;
  }
  if (state.currentView === "rework") {
    renderReworkDiagram(state.dashboard.rework);
    return;
  }
  if (state.currentView === "queue_heatmap") {
    renderQueueAgeHeatmap(state.dashboard.extra_views?.queue_age_heatmap);
    return;
  }
  if (state.currentView === "rework_treemap") {
    renderReworkTreemap(state.dashboard.extra_views?.rework_treemap);
    return;
  }
  if (state.currentView === "variant_boxplot") {
    renderVariantDurationBoxplot(state.dashboard.extra_views?.variant_duration_boxplot);
    return;
  }
  renderProcessMap(state.dashboard.nodes, state.dashboard.edges);
}

function renderDashboard(dashboard, informationalProfile = []) {
  // Render all dashboard panels from one backend response so the tables and
  // active diagram always represent the same filtered event set.
  state.dashboard = dashboard;
  updateViewAvailability();
  updateViewButtons();
  renderMetrics(dashboard.summary);
  renderFilterStack();
  renderMapSelectionPanel();
  renderCurrentMap();
  renderEdgesTable(dashboard.edges);
  renderVariantsTable(dashboard.variants);
  renderBottlenecks(dashboard.bottlenecks);
  renderActivityStats(dashboard.activity_stats);
  renderReworkTable(dashboard.rework);
  renderRecommendations(dashboard.recommendations);
  renderInformationalColumns(informationalProfile);
}

function stopAnimation(options = {}) {
  // hideOverlay controls whether dots disappear immediately. Frame scrubbing
  // uses hideOverlay=false so the selected frame stays visible while dragging.
  const { hideOverlay = true, rerender = false } = options;
  if (state.animation.timerId) {
    clearInterval(state.animation.timerId);
    state.animation.timerId = null;
  }
  state.animation.isPlaying = false;
  if (hideOverlay) {
    state.animation.overlayVisible = false;
  }
  els.toggleAnimation.innerHTML = '<svg width="11" height="11" viewBox="0 0 10 10" style="vertical-align:-1px;margin-right:4px" aria-hidden="true"><polygon points="2,1 9,5 2,9" fill="currentColor"/></svg>Play Animation';
  updateMapZoomControls();
  if (rerender && state.dashboard) {
    renderCurrentMap();
  }
}

function updateAnimationTimeLabel() {
  // The primary animation uses relative offsets because all cases start at T+0.
  // Older absolute-time payloads are still handled for compatibility.
  const payload = currentAnimationPayload();
  if (!state.animation.frames.length || !payload.frame_count) {
    els.animationTime.textContent = "No animation data";
    return;
  }

  const frame = state.animation.frames[state.animation.frameIndex];
  if (!frame) {
    els.animationTime.textContent = "No animation data";
    return;
  }

  const context = detailControlContext();
  const countLabel = state.currentView === "process" ? "transitions" : context.edgePlural;
  const label =
    payload.timeline_mode === "relative_case_start" || payload.normalized_case_start
      ? `${formatTimelineOffset(frame.start_offset_seconds)} - ${formatTimelineOffset(frame.end_offset_seconds)} | ${countLabel} ${formatNumber(frame.total_transitions || 0)}`
      : `${formatDateTime(frame.start_time)} - ${formatDateTime(frame.end_time)} | ${countLabel} ${formatNumber(frame.total_transitions || 0)}`;
  els.animationTime.textContent = label;
}

function applyAnimationData(animationPayloads) {
  // Loading new dashboard data replaces every animation payload. Re-rendering
  // clears any stale dots from the previous filter state.
  stopAnimation({ hideOverlay: true });
  state.animation.payloads = normalizeAnimationPayloadMap(animationPayloads);
  syncActiveAnimationView(true);
  updateAnimationTimeLabel();
  renderCurrentMap();
}

function advanceAnimationFrame(step = 1) {
  // Animation loops continuously instead of stopping at the end, which makes
  // bottleneck/rework patterns easier to observe.
  if (!state.animation.frames.length) {
    return;
  }

  const frameCount = state.animation.frames.length;
  let nextIndex = state.animation.frameIndex + step;
  if (nextIndex >= frameCount) {
    nextIndex = 0;
  } else if (nextIndex < 0) {
    nextIndex = frameCount - 1;
  }

  state.animation.frameIndex = nextIndex;
  els.animationFrame.value = String(nextIndex);
  updateAnimationTimeLabel();
  renderCurrentMap();
}

function startAnimation() {
  // Render once before starting the interval so the first visible state matches
  // the current slider position.
  if (!state.animation.frames.length) {
    return;
  }

  stopAnimation({ hideOverlay: false });
  state.animation.overlayVisible = true;
  state.animation.isPlaying = true;
  els.toggleAnimation.innerHTML = '<svg width="11" height="11" viewBox="0 0 10 10" style="vertical-align:-1px;margin-right:4px" aria-hidden="true"><rect x="1.5" y="1" width="2.5" height="8" fill="currentColor"/><rect x="6" y="1" width="2.5" height="8" fill="currentColor"/></svg>Pause Animation';
  updateMapZoomControls();
  renderCurrentMap();

  const speed = Math.max(Number(els.animationSpeed.value) || 1, 0.1);
  const intervalMs = Math.max(120, 880 / speed);

  state.animation.timerId = setInterval(() => {
    advanceAnimationFrame(1);
  }, intervalMs);
}

function toggleAnimation() {
  if (state.animation.isPlaying) {
    stopAnimation({ hideOverlay: false, rerender: true });
    return;
  }
  startAnimation();
}

async function extractError(response, fallback) {
  // FastAPI returns { detail } for most errors; fall back to a plain message if
  // the response is not JSON.
  try {
    const payload = await response.json();
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

async function suggestMappingForCurrentFile() {
  // Mapping suggestions are intentionally available before upload so users can
  // inspect and override guessed case/activity/timestamp/actor fields.
  const file = els.logFile.files?.[0];
  if (!file) {
    setMappingStatus("Select a CSV first to generate mapping suggestions.", true);
    return;
  }

  const isCsv = file.name.toLowerCase().endsWith(".csv");
  if (!isCsv) {
    resetMappingSelectors();
    setMappingStatus(
      "XES selected: mapping fields are optional and inferred from the log format."
    );
    return;
  }

  setMappingStatus("Inspecting CSV columns and sample values...");
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch("/api/logs/suggest-mapping", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new Error(await extractError(response, "Could not suggest mapping"));
  }

  const data = await response.json();
  if (!data.supported || !data.mapping) {
    setMappingStatus(data.message || "No mapping suggestions available.");
    return;
  }

  applyMappingSuggestion(data.mapping);
}

async function loadDashboard() {
  // Dashboard and animation are independent backend computations, so fetch them
  // in parallel. The diagram renders as soon as dashboard data arrives; missing
  // animation data simply disables the animation controls.
  if (!state.logId) {
    return;
  }

  const payload = buildFilterPayload();
  FlowScope.info("API", "Loading dashboard + animation", { logId: state.logId, filters: payload });

  const t0 = performance.now();
  const [dashboardResponse, animationResponse] = await Promise.all([
    fetch(`/api/logs/${state.logId}/dashboard`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    fetch(`/api/logs/${state.logId}/animation?frame_count=90`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  ]);
  const fetchMs = (performance.now() - t0).toFixed(1);

  if (!dashboardResponse.ok) {
    const errMsg = await extractError(dashboardResponse, "Could not load dashboard");
    FlowScope.error("API", `Dashboard fetch failed (${dashboardResponse.status}) after ${fetchMs} ms`, errMsg);
    throw new Error(errMsg);
  }

  FlowScope.info("API", `Fetch complete in ${fetchMs} ms (dashboard=${dashboardResponse.status}, animation=${animationResponse.status})`);

  const dashboardData = await dashboardResponse.json();
  FlowScope.debug_log("DATA", "Dashboard payload", {
    cases: dashboardData.dashboard?.summary?.total_cases,
    events: dashboardData.dashboard?.summary?.total_events,
    nodes: dashboardData.dashboard?.nodes?.length,
    edges: dashboardData.dashboard?.edges?.length,
  });

  if (dashboardData.attribute_filter_options && state.filterOnlyColumns.length) {
    state.attributeFilterOptions = dashboardData.attribute_filter_options;
    renderAttributeFilterControls(state.filterOnlyColumns, state.attributeFilterOptions);
  }

  const renderT0 = performance.now();
  renderDashboard(
    dashboardData.dashboard,
    dashboardData.informational_columns_profile || []
  );
  FlowScope.debug_log("RENDER", `Dashboard rendered in ${(performance.now() - renderT0).toFixed(1)} ms`);

  if (animationResponse.ok) {
    const animationData = await animationResponse.json();
    const processAnimation =
      animationData.animations?.process || animationData.animation || emptyAnimationPayload();
    FlowScope.info("ANIM", `${processAnimation.frame_count || 0} frames loaded`, {
      normalizedCaseStart: Boolean(
        animationData.normalized_case_start || processAnimation.normalized_case_start
      ),
    });
    applyAnimationData(animationData.animations || animationData.animation);
  } else {
    FlowScope.warn("ANIM", `Animation fetch failed (${animationResponse.status})`);
    applyAnimationData({
      process: emptyAnimationPayload(),
      handoff_actor: emptyAnimationPayload(),
      handoff_activity: emptyAnimationPayload(),
    });
  }
}

function setFiltersFromSummary(summary) {
  els.startTime.value = toLocalDateInput(summary.start_time);
  els.endTime.value = toLocalDateInput(summary.end_time);
}

function resetFiltersToDefaults() {
  // Defaults are based on the original log summary, not the current filtered
  // dashboard, so Reset always returns to the full imported log.
  if (state.baseSummary) {
    setFiltersFromSummary(state.baseSummary);
  }

  els.minActivityFrequency.value = "1";
  els.minEdgeFrequency.value = "1";
  els.variantTopK.value = "20";
  els.retainTopVariants.value = "";
  els.minCaseDuration.value = "";
  els.maxCaseDuration.value = "";
  if (els.activityDetail) {
    els.activityDetail.value = "100";
  }
  if (els.pathDetail) {
    els.pathDetail.value = "50";
  }
  updateProcessDetailLabels();

  clearMultiSelect(els.includeActivities);
  clearMultiSelect(els.excludeActivities);

  if (els.attributeFilters) {
    Array.from(els.attributeFilters.querySelectorAll("select[data-column]")).forEach(
      (control) => {
        clearMultiSelect(control);
      }
    );
  }

  state.quickFilters = [];
  clearMapSelection();
  renderFilterStack();
}

async function runConformance() {
  // Conformance can be slower and pm4py-version dependent, so it is run only
  // when requested rather than on every filter change.
  if (!state.logId) {
    return;
  }

  FlowScope.info("CONFORM", "Starting conformance analysis");
  els.conformanceOutput.textContent = "Running conformance and model discovery...";

  const response = await FlowScope.time("CONFORM", "POST /conformance", () =>
    fetch(`/api/logs/${state.logId}/conformance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildFilterPayload()),
    })
  );

  if (!response.ok) {
    const errMsg = await extractError(response, "Conformance failed");
    FlowScope.error("CONFORM", `Conformance failed (${response.status})`, errMsg);
    throw new Error(errMsg);
  }

  const data = await response.json();
  const result = data.conformance;

  if (!result.supported) {
    FlowScope.warn("CONFORM", "Conformance not supported", result.message);
    els.conformanceOutput.textContent = result.message || "Conformance metrics unavailable.";
    return;
  }

  FlowScope.info("CONFORM", "Conformance result", {
    fitness: result.fitness,
    precision: result.precision,
    model: result.model,
  });

  const fitnessText = result.fitness === null ? "n/a" : result.fitness.toFixed(4);
  const precisionText = result.precision === null ? "n/a" : result.precision.toFixed(4);
  els.conformanceOutput.textContent =
    `Fitness: ${fitnessText} | Precision: ${precisionText} | ` +
    `Model size: ${result.model.places} places, ${result.model.transitions} transitions, ${result.model.arcs} arcs | ` +
    `Cases: ${formatNumber(result.cases)}, Events: ${formatNumber(result.events)}`;
}

function downloadBlob(blob, filename) {
  // Create a temporary object URL so browser downloads work without navigating
  // away from the analysis page.
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function filenameFromDisposition(contentDisposition) {
  if (!contentDisposition) {
    return null;
  }

  const match = /filename="?([^";]+)"?/i.exec(contentDisposition);
  return match?.[1] || null;
}

async function exportAnalysis() {
  // ZIP export gives analysts machine-readable artifacts: CSV tables, JSON
  // summaries, Mermaid diagrams, BPMN XML where available, and filtered events.
  if (!state.logId) {
    return;
  }

  FlowScope.info("EXPORT", "Starting ZIP export");
  setStatus("Preparing export package...");

  const response = await FlowScope.time("EXPORT", "POST /export (ZIP)", () =>
    fetch(`/api/logs/${state.logId}/export?include_conformance=true`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildFilterPayload()),
    })
  );

  if (!response.ok) {
    const errMsg = await extractError(response, "Export failed");
    FlowScope.error("EXPORT", `ZIP export failed (${response.status})`, errMsg);
    throw new Error(errMsg);
  }

  const blob = await response.blob();
  FlowScope.info("EXPORT", `ZIP blob received: ${(blob.size / 1024).toFixed(1)} KB`);
  const fromHeader = filenameFromDisposition(response.headers.get("Content-Disposition"));
  const fallback = `process-analysis-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.zip`;
  const filename = fromHeader || fallback;
  downloadBlob(blob, filename);

  setStatus(`Export downloaded: ${filename}`);
}

async function exportHtmlReport() {
  // HTML report is the shareable, human-readable counterpart to the ZIP export.
  if (!state.logId) {
    return;
  }

  FlowScope.info("EXPORT", "Starting HTML report export");
  setStatus("Preparing HTML report export...");

  const response = await FlowScope.time("EXPORT", "POST /export/html", () =>
    fetch(
      `/api/logs/${state.logId}/export/html?include_conformance=true`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildFilterPayload()),
      }
    )
  );

  if (!response.ok) {
    const errMsg = await extractError(response, "HTML report export failed");
    FlowScope.error("EXPORT", `HTML export failed (${response.status})`, errMsg);
    throw new Error(errMsg);
  }

  const blob = await response.blob();
  FlowScope.info("EXPORT", `HTML blob received: ${(blob.size / 1024).toFixed(1)} KB`);
  const fromHeader = filenameFromDisposition(response.headers.get("Content-Disposition"));
  const fallback = `process-analysis-report-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.html`;
  const filename = fromHeader || fallback;
  downloadBlob(blob, filename);

  setStatus(`Export downloaded: ${filename}`);
}

// ---------------------------------------------------------------------------
// Event wiring
// ---------------------------------------------------------------------------
// All event listeners live at the end of the file so the functions above can be
// read as a library, and the UI behavior wiring is visible in one place.

els.logFile.addEventListener("change", async () => {
  const file = els.logFile.files?.[0];
  if (!file) {
    return;
  }
  try {
    await suggestMappingForCurrentFile();
  } catch (error) {
    setMappingStatus(error.message || "Could not suggest mapping.", true);
  }
});

els.suggestMapping.addEventListener("click", async () => {
  try {
    await suggestMappingForCurrentFile();
  } catch (error) {
    setMappingStatus(error.message || "Could not suggest mapping.", true);
  }
});

[
  els.startTime,
  els.endTime,
  els.minActivityFrequency,
  els.minEdgeFrequency,
  els.retainTopVariants,
  els.minCaseDuration,
  els.maxCaseDuration,
  els.includeActivities,
  els.excludeActivities,
].forEach((control) => {
  control?.addEventListener("change", () => {
    renderFilterStack();
  });
});

els.attributeFilters?.addEventListener("change", () => {
  renderFilterStack();
});

els.filterStack?.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-filter-id]");
  if (!button) {
    return;
  }
  try {
    await removeFilterById(button.dataset.filterId || "");
  } catch (error) {
    els.conformanceOutput.textContent = error.message || "Could not remove filter.";
  }
});

els.clearFilterStack?.addEventListener("click", async () => {
  resetFiltersToDefaults();
  if (!state.logId) {
    return;
  }
  try {
    await loadDashboard();
    els.conformanceOutput.textContent = "";
  } catch (error) {
    els.conformanceOutput.textContent = error.message || "Could not clear filters.";
  }
});

els.mapSelectionActions?.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-selection-action]");
  if (!button) {
    return;
  }
  const action = button.dataset.selectionAction;
  if (action === "clear") {
    clearMapSelection(true);
    return;
  }
  if (action !== "add-filter") {
    return;
  }
  try {
    await applyMapSelectionFilter({
      kind: button.dataset.filterKind || "",
      activity: button.dataset.filterActivity || "",
      source: button.dataset.filterSource || "",
      target: button.dataset.filterTarget || "",
    });
  } catch (error) {
    els.conformanceOutput.textContent = error.message || "Could not apply map filter.";
  }
});

els.processMap?.addEventListener("click", (event) => {
  const selectableAncestor = event.target.closest?.('[data-map-selectable="true"]');
  if (selectableAncestor) {
    return;
  }
  clearMapSelection(true);
});

// ---------------------------------------------------------------------------
// Project management
// ---------------------------------------------------------------------------

function setProjectStatus(message, isError = false) {
  els.projectStatus.textContent = message;
  els.projectStatus.style.color = isError ? "#003399" : "#000000";
}

async function loadProjects() {
  try {
    const response = await fetch("/api/projects");
    const data = await response.json();
    const projects = data.projects || [];

    els.projectSelect.innerHTML = '<option value="">— select a project —</option>';
    projects.forEach((p) => {
      const option = document.createElement("option");
      option.value = p.project_id;
      option.textContent = p.name;
      els.projectSelect.appendChild(option);
    });

    if (projects.length === 0) {
      setProjectStatus("No projects yet. Create one to get started.");
    } else {
      setProjectStatus(`${projects.length} project${projects.length === 1 ? "" : "s"} available.`);
    }
  } catch {
    setProjectStatus("Could not load projects.", true);
  }
}

async function loadProjectLogs(projectId) {
  try {
    const response = await fetch(`/api/projects/${projectId}/logs`);
    const data = await response.json();
    const logs = data.logs || [];

    els.projectLogsList.innerHTML = "";

    if (logs.length === 0) {
      els.projectLogsList.innerHTML = '<p class="note">No logs uploaded to this project yet.</p>';
    } else {
      logs.forEach((log) => {
        const row = document.createElement("div");
        row.className = "project-log-row";
        const uploadedAt = new Date(log.uploaded_at).toLocaleString();
        row.dataset.logId = log.log_id;
        row.innerHTML = `
          <span class="log-filename">${log.filename}</span>
          <span class="log-date">${uploadedAt}</span>
          <span class="log-active-badge hidden">Active</span>
          <button class="btn-ghost btn-sm load-log-btn" data-log-id="${log.log_id}">Load</button>
          <button class="btn-delete-log" data-log-id="${log.log_id}" title="Delete log" aria-label="Delete ${log.filename}">
            <svg width="13" height="14" viewBox="0 0 13 14" fill="none" aria-hidden="true">
              <path d="M1 3.5h11M4.5 3.5V2.5a.5.5 0 0 1 .5-.5h3a.5.5 0 0 1 .5.5v1M2 3.5l.75 8a.5.5 0 0 0 .5.5h6.5a.5.5 0 0 0 .5-.5l.75-8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
              <line x1="5" y1="6" x2="5" y2="10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
              <line x1="8" y1="6" x2="8" y2="10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
            </svg>
          </button>
        `;
        row.querySelector(".load-log-btn").addEventListener("click", () =>
          reloadLogFromProject(log.log_id, log.filename)
        );
        row.querySelector(".btn-delete-log").addEventListener("click", async () => {
          if (!confirm(`Delete "${log.filename}"? This cannot be undone.`)) return;
          try {
            const res = await fetch(`/api/projects/${projectId}/logs/${log.log_id}`, { method: "DELETE" });
            if (!res.ok) throw new Error("Delete failed");
            row.remove();
            if (!els.projectLogsList.querySelector(".project-log-row")) {
              els.projectLogsList.innerHTML = '<p class="note">No logs uploaded to this project yet.</p>';
            }
            if (state.logId === log.log_id) {
              state.logId = null;
              state.dashboard = null;
              state.activities = [];
              state.baseSummary = null;
              stopAnimation({ hideOverlay: true });
              renderCurrentMap();
              setStatus("Log deleted. Upload or load another log to continue.");
            }
          } catch {
            setProjectStatus("Could not delete log.", true);
          }
        });
        els.projectLogsList.appendChild(row);
      });
    }

    els.projectLogsSection.classList.remove("hidden");
  } catch {
    setProjectStatus("Could not load logs for this project.", true);
  }
}

async function reloadLogFromProject(logId, filename) {
  setStatus(`Loading ${filename} from project…`);
  setProjectStatus(`Loading ${filename}…`);

  try {
    const response = await fetch(`/api/logs/${logId}/overview`);
    if (!response.ok) throw new Error("Could not reload log from database.");
    const data = await response.json();

    state.logId = logId;
    state.activities = data.activities || [];
    state.baseSummary = data.summary;
    state.columnMapping = data.column_mapping || null;
    state.informationalColumns = data.informational_columns || [];
    state.filterOnlyColumns = data.filter_only_columns || [];
    state.attributeFilterOptions = data.attribute_filter_options || {};

    populateActivityFilters(state.activities);
    renderAttributeFilterControls(state.filterOnlyColumns, state.attributeFilterOptions);
    renderInformationalColumns(data.informational_columns_profile || []);
    setFiltersFromSummary(data.summary);
    resetFiltersToDefaults();

    els.dashboard.classList.remove("hidden");
    setStatus(`Loaded ${filename}. Cases: ${formatNumber(data.summary.total_cases)}, Events: ${formatNumber(data.summary.total_events)}.`);
    setProjectStatus(`Loading dashboard for ${filename}…`);

    await loadDashboard();

    // Mark the active log row and clear any previous active state
    document.querySelectorAll(".project-log-row").forEach((r) => {
      r.classList.remove("active-log");
      const badge = r.querySelector(".log-active-badge");
      if (badge) badge.classList.add("hidden");
    });
    const activeRow = document.querySelector(`.project-log-row[data-log-id="${logId}"]`);
    if (activeRow) {
      activeRow.classList.add("active-log");
      const badge = activeRow.querySelector(".log-active-badge");
      if (badge) badge.classList.remove("hidden");
    }

    setProjectStatus(`${filename} loaded — dashboard updated below.`);

    // Scroll the dashboard into view so the user sees the updated analysis
    setTimeout(() => {
      els.dashboard.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 80);

  } catch (error) {
    setStatus(error.message || "Failed to reload log.", true);
    setProjectStatus(error.message || "Failed to reload log.", true);
  }
}

els.projectSelect.addEventListener("change", async () => {
  const projectId = els.projectSelect.value;
  if (!projectId) {
    state.projectId = null;
    state.projectName = null;
    els.projectLogsSection.classList.add("hidden");
    setProjectStatus("");
    return;
  }
  const selectedOption = els.projectSelect.options[els.projectSelect.selectedIndex];
  state.projectId = projectId;
  state.projectName = selectedOption.textContent;
  setProjectStatus(`Project selected: ${state.projectName}`);
  await loadProjectLogs(projectId);
});

els.createProjectBtn.addEventListener("click", async () => {
  const name = els.projectNameInput.value.trim();
  if (!name) {
    setProjectStatus("Please enter a project name.", true);
    return;
  }

  try {
    const response = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || "Could not create project.");
    }

    const data = await response.json();
    state.projectId = data.project_id;
    state.projectName = data.name;
    els.projectNameInput.value = "";

    await loadProjects();
    els.projectSelect.value = data.project_id;
    setProjectStatus(`Project "${data.name}" created and selected.`);
    els.projectLogsList.innerHTML = '<p class="note">No logs uploaded to this project yet.</p>';
    els.projectLogsSection.classList.remove("hidden");
  } catch (error) {
    setProjectStatus(error.message || "Could not create project.", true);
  }
});

// Load projects on page start
loadProjects();

els.uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const file = els.logFile.files?.[0];
  if (!file) {
    setStatus("Please choose a .csv or .xes file first.", true);
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  formData.append("case_id_col", String(els.caseCol.value || "").trim());
  formData.append("activity_col", String(els.activityCol.value || "").trim());
  formData.append(
    "start_timestamp_col",
    String(els.startTimestampCol.value || "").trim()
  );
  formData.append(
    "stop_timestamp_col",
    String(els.stopTimestampCol.value || "").trim()
  );
  formData.append("actor_col", String(els.actorCol.value || "").trim());
  formData.append(
    "informational_cols",
    selectedValues(els.informationalCols).join(",")
  );
  formData.append(
    "filter_only_cols",
    selectedValues(els.filterOnlyCols).join(",")
  );
  formData.append(
    "timestamp_col",
    // Compatibility field for the older one-timestamp backend API. The current
    // UI maps the same value through start_timestamp_col.
    String(els.startTimestampCol.value || "").trim() ||
      String(els.stopTimestampCol.value || "").trim() ||
      ""
  );

  setStatus("Uploading and parsing log...");
  FlowScope.info("UPLOAD", `Uploading ${file.name} (${(file.size / 1024).toFixed(1)} KB)`);

  try {
    const response = await FlowScope.time("UPLOAD", `POST /api/logs/upload (${file.name})`, () =>
      fetch("/api/logs/upload", {
        method: "POST",
        body: formData,
      })
    );

    if (!response.ok) {
      const errMsg = await extractError(response, "Upload failed");
      FlowScope.error("UPLOAD", `Upload rejected (${response.status})`, errMsg);
      throw new Error(errMsg);
    }

    const data = await response.json();
    FlowScope.info("UPLOAD", `Log stored: ${data.log_id}`, {
      filename: data.filename,
      cases: data.summary?.total_cases,
      events: data.summary?.total_events,
      activities: data.activities?.length,
      warnings: data.mapping_warnings,
    });

    state.logId = data.log_id;
    state.activities = data.activities || [];
    state.baseSummary = data.summary;
    state.columnMapping = data.column_mapping || null;
    state.informationalColumns = data.informational_columns || [];
    state.filterOnlyColumns = data.filter_only_columns || [];
    state.attributeFilterOptions = data.attribute_filter_options || {};

    if (state.projectId) {
      await fetch(`/api/projects/${state.projectId}/logs/${data.log_id}/assign`, {
        method: "POST",
      });
      await loadProjectLogs(state.projectId);
      setProjectStatus(`Log saved to project "${state.projectName}".`);
    }

    populateActivityFilters(state.activities);
    renderAttributeFilterControls(state.filterOnlyColumns, state.attributeFilterOptions);
    renderInformationalColumns(data.informational_columns_profile || []);
    setFiltersFromSummary(data.summary);
    resetFiltersToDefaults();

    els.dashboard.classList.remove("hidden");
    const warningText =
      data.mapping_warnings && data.mapping_warnings.length
        ? ` Mapping warnings: ${data.mapping_warnings.join(" | ")}`
        : "";
    setStatus(
      `Loaded ${data.filename}. Cases: ${formatNumber(data.summary.total_cases)}, Events: ${formatNumber(data.summary.total_events)}.${warningText}`
    );

    await loadDashboard();
  } catch (error) {
    FlowScope.error("UPLOAD", "Upload flow failed", error);
    setStatus(error.message || "Upload failed", true);
  }
});

els.applyFilters.addEventListener("click", async () => {
  if (!state.logId) {
    return;
  }

  FlowScope.info("FILTER", "Applying filters");
  try {
    await loadDashboard();
    els.conformanceOutput.textContent = "";
  } catch (error) {
    FlowScope.error("FILTER", "Apply filters failed", error);
    els.conformanceOutput.textContent = error.message || "Could not apply filters.";
  }
});

els.resetFilters.addEventListener("click", async () => {
  FlowScope.info("FILTER", "Resetting filters to defaults");
  resetFiltersToDefaults();
  if (!state.logId) {
    return;
  }

  try {
    await loadDashboard();
    els.conformanceOutput.textContent = "";
  } catch (error) {
    FlowScope.error("FILTER", "Reset filters failed", error);
    els.conformanceOutput.textContent = error.message || "Could not reset filters.";
  }
});

els.runConformance.addEventListener("click", async () => {
  try {
    await runConformance();
  } catch (error) {
    els.conformanceOutput.textContent = error.message || "Conformance failed.";
  }
});

els.exportAnalysis.addEventListener("click", async () => {
  try {
    await exportAnalysis();
  } catch (error) {
    setStatus(error.message || "Export failed", true);
  }
});

els.exportHtmlReport.addEventListener("click", async () => {
  try {
    await exportHtmlReport();
  } catch (error) {
    setStatus(error.message || "HTML report export failed", true);
  }
});

els.modeFrequency.addEventListener("click", () => {
  state.mode = "frequency";
  els.modeFrequency.classList.add("active");
  els.modePerformance.classList.remove("active");
  renderCurrentMap();
});

els.modePerformance.addEventListener("click", () => {
  state.mode = "performance";
  els.modePerformance.classList.add("active");
  els.modeFrequency.classList.remove("active");
  renderCurrentMap();
});

els.zoomIn?.addEventListener("click", () => {
  if (state.animation.isPlaying) {
    return;
  }
  state.mapZoom = clampMapZoom(state.mapZoom + 0.18);
  applyMapZoom();
});

els.zoomOut?.addEventListener("click", () => {
  if (state.animation.isPlaying) {
    return;
  }
  state.mapZoom = clampMapZoom(state.mapZoom - 0.18);
  applyMapZoom();
});

els.zoomReset?.addEventListener("click", () => {
  if (state.animation.isPlaying) {
    return;
  }
  state.mapZoom = DEFAULT_MAP_ZOOM;
  applyMapZoom();
});

els.viewProcess.addEventListener("click", () => setDiagramView("process"));
els.viewHandoffActor.addEventListener("click", () => setDiagramView("handoff_actor"));
els.viewHandoffActivity.addEventListener("click", () =>
  setDiagramView("handoff_activity")
);
els.viewSwimlane.addEventListener("click", () => setDiagramView("swimlane"));
els.viewSankey.addEventListener("click", () => setDiagramView("sankey"));
els.viewRework.addEventListener("click", () => setDiagramView("rework"));
els.viewQueueHeatmap.addEventListener("click", () => setDiagramView("queue_heatmap"));
els.viewReworkTreemap.addEventListener("click", () => setDiagramView("rework_treemap"));
els.viewVariantBoxplot.addEventListener("click", () => setDiagramView("variant_boxplot"));

els.toggleAnimation.addEventListener("click", () => {
  toggleAnimation();
});


els.restartAnimation.addEventListener("click", () => {
  stopAnimation({ hideOverlay: false });
  state.animation.frameIndex = 0;
  els.animationFrame.value = "0";
  updateAnimationTimeLabel();
  startAnimation();
});

els.stepBackAnimation.addEventListener("click", () => {
  if (state.animation.isPlaying) {
    stopAnimation({ hideOverlay: false });
  }
  state.animation.overlayVisible = true;
  advanceAnimationFrame(-1);
});

els.stepForwardAnimation.addEventListener("click", () => {
  if (state.animation.isPlaying) {
    stopAnimation({ hideOverlay: false });
  }
  state.animation.overlayVisible = true;
  advanceAnimationFrame(1);
});

els.animationSpeed.addEventListener("change", () => {
  if (state.animation.isPlaying) {
    startAnimation();
  }
});

els.animationFrame.addEventListener("input", (event) => {
  const index = Number(event.target.value);
  if (!Number.isFinite(index)) {
    return;
  }

  stopAnimation({ hideOverlay: false });
  state.animation.overlayVisible = true;
  state.animation.frameIndex = Math.max(0, Math.min(index, state.animation.frames.length - 1));
  updateAnimationTimeLabel();
  updateMapZoomControls();
  renderCurrentMap();
});

els.animationFrame.addEventListener("change", () => {
  if (state.animation.isPlaying) {
    return;
  }
  updateMapZoomControls();
  renderCurrentMap();
});

els.activityDetail?.addEventListener("input", () => {
  updateProcessDetailLabels();
  if (usesStructuredFlowView() && state.dashboard) {
    renderCurrentMap();
  }
});

els.pathDetail?.addEventListener("input", () => {
  updateProcessDetailLabels();
  if (usesStructuredFlowView() && state.dashboard) {
    renderCurrentMap();
  }
});

// ---------------------------------------------------------------------------
// Initial render
// ---------------------------------------------------------------------------
// The app starts in a valid empty state: controls are populated, unavailable
// diagrams are disabled, and the map area explains the next action.

applyAnimationData({
  process: emptyAnimationPayload(),
  handoff_actor: emptyAnimationPayload(),
  handoff_activity: emptyAnimationPayload(),
});
resetMappingSelectors();
updateViewButtons();
updateProcessDetailLabels();
renderAttributeFilterControls([], {});
renderInformationalColumns([]);
renderEmptyMap("Upload a log to start.");
