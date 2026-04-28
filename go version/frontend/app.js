// ---------------------------------------------------------------------------
// Lightweight logger — writes structured messages to the browser console
// Toggle verbose logging by setting FlowScope.debug = true in DevTools.
// ---------------------------------------------------------------------------
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

const state = {
  logId: null,
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
  animation: {
    frames: [],
    frameIndex: 0,
    maxEdgeCount: 0,
    isPlaying: false,
    timerId: null,
  },
};

const els = {
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
  applyFilters: document.getElementById("apply-filters"),
  resetFilters: document.getElementById("reset-filters"),
  runConformance: document.getElementById("run-conformance"),
  exportAnalysis: document.getElementById("export-analysis"),
  exportHtmlReport: document.getElementById("export-html-report"),
  conformanceOutput: document.getElementById("conformance-output"),
  processMap: document.getElementById("process-map"),
  viewDescription: document.getElementById("view-description"),
  viewProcess: document.getElementById("view-process"),
  viewHandoffActor: document.getElementById("view-handoff-actor"),
  viewHandoffActivity: document.getElementById("view-handoff-activity"),
  viewSwimlane: document.getElementById("view-swimlane"),
  viewSankey: document.getElementById("view-sankey"),
  viewRework: document.getElementById("view-rework"),
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
  rewindAnimation: document.getElementById("rewind-animation"),
  animationSpeed: document.getElementById("animation-speed"),
  animationFrame: document.getElementById("animation-frame"),
  animationTime: document.getElementById("animation-time"),
};

const SVG_NS = "http://www.w3.org/2000/svg";
const VIEW_DESCRIPTIONS = {
  process: "Activity-focused process map (frequency/performance modes plus animation).",
  handoff_actor:
    "Actor-focused handoff graph showing work transfer between resources.",
  handoff_activity:
    "Activity-focused handoff graph highlighting transitions where actor changes occur.",
  swimlane:
    "Visio-like swimlane structure with lanes per actor and cross-lane activity transitions.",
  sankey: "Sankey flow emphasizing dominant transition volume between activities.",
  rework: "Rework-focused view showing repeated activities and self-loop intensity.",
};

function updateViewButtons() {
  const viewButtons = [
    [els.viewProcess, "process"],
    [els.viewHandoffActor, "handoff_actor"],
    [els.viewHandoffActivity, "handoff_activity"],
    [els.viewSwimlane, "swimlane"],
    [els.viewSankey, "sankey"],
    [els.viewRework, "rework"],
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
}

function setStatus(message, isError = false) {
  els.uploadStatus.textContent = message;
  els.uploadStatus.style.color = "#ffffff";
}

function setMappingStatus(message, isError = false) {
  if (!els.mappingStatus) {
    return;
  }
  els.mappingStatus.textContent = message;
  els.mappingStatus.style.color = "#ffffff";
}

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

function formatNumber(value) {
  return new Intl.NumberFormat().format(value ?? 0);
}

function formatPct(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) {
    return "-";
  }

  const totalSeconds = Number(seconds);
  if (!Number.isFinite(totalSeconds)) {
    return "-";
  }

  if (totalSeconds < 60) {
    return `${totalSeconds.toFixed(0)}s`;
  }

  const totalMinutes = totalSeconds / 60;
  if (totalMinutes < 60) {
    return `${totalMinutes.toFixed(1)}m`;
  }

  const totalHours = totalMinutes / 60;
  if (totalHours < 24) {
    return `${totalHours.toFixed(1)}h`;
  }

  const totalDays = totalHours / 24;
  return `${totalDays.toFixed(1)}d`;
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
  return {
    start_time: fromLocalDateInput(els.startTime.value),
    end_time: fromLocalDateInput(els.endTime.value),
    include_activities: selectedValues(els.includeActivities),
    exclude_activities: selectedValues(els.excludeActivities),
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

function svgElement(tag, attrs = {}) {
  const element = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([key, value]) => {
    element.setAttribute(key, String(value));
  });
  return element;
}

function renderEmptyMap(message) {
  els.processMap.innerHTML = "";
  const text = svgElement("text", {
    x: 600,
    y: 380,
    "text-anchor": "middle",
    fill: "#ffffff",
    "font-size": 28,
    "font-family": "IBM Plex Mono, monospace",
  });
  text.textContent = message;
  els.processMap.appendChild(text);
}

function currentAnimationFrameData() {
  if (!state.animation.frames.length) {
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

function quadraticBezierPoint(t, x0, y0, cx, cy, x1, y1) {
  const mt = 1 - t;
  const x = mt * mt * x0 + 2 * mt * t * cx + t * t * x1;
  const y = mt * mt * y0 + 2 * mt * t * cy + t * t * y1;
  return { x, y };
}

function renderProcessMap(nodes, edges) {
  els.processMap.innerHTML = "";

  if (!nodes.length || !edges.length) {
    renderEmptyMap("No process map edges available for current filters.");
    return;
  }

  const activeFrame = currentAnimationFrameData();
  const hasAnimationOverlay = Boolean(activeFrame);

  const width = 1200;
  const height = 760;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.33;

  const defs = svgElement("defs");
  const marker = svgElement("marker", {
    id: "arrowhead",
    viewBox: "0 0 10 10",
    refX: 8,
    refY: 5,
    markerWidth: 7,
    markerHeight: 7,
    orient: "auto-start-reverse",
  });
  marker.appendChild(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#003399" }));
  defs.appendChild(marker);
  els.processMap.appendChild(defs);

  const sortedNodes = [...nodes].sort((a, b) => b.frequency - a.frequency);
  const nodeMaxFrequency = sortedNodes[0]?.frequency || 1;
  const edgeMaxFrequency = Math.max(...edges.map((edge) => edge.frequency), 1);

  const positionedNodes = new Map();
  sortedNodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / sortedNodes.length - Math.PI / 2;
    const x = centerX + radius * Math.cos(angle);
    const y = centerY + radius * 0.74 * Math.sin(angle);
    positionedNodes.set(node.id, { ...node, x, y });
  });

  const edgesLayer = svgElement("g");
  const labelsLayer = svgElement("g");
  const nodesLayer = svgElement("g");
  const pulseLayer = svgElement("g");

  const pulseT = ((state.animation.frameIndex % 12) + 1) / 13;
  const drawEdges = edges.slice(0, 200);

  drawEdges.forEach((edge, index) => {
    const source = positionedNodes.get(edge.source);
    const target = positionedNodes.get(edge.target);
    if (!source || !target) {
      return;
    }

    const edgeKey = `${edge.source}|||${edge.target}`;
    const activeCount = hasAnimationOverlay ? activeFrame.edgeCounts.get(edgeKey) || 0 : 0;
    const activityIntensity = hasAnimationOverlay
      ? Math.min(activeCount / activeFrame.maxEdgeCount, 1)
      : 0;

    const strength = Math.max(edge.frequency / edgeMaxFrequency, 0.05);
    let strokeWidth = 1 + strength * 9;
    let strokeColor = `rgba(0, 51, 153, ${0.35 + strength * 0.55})`;
    let opacity = 0.58;

    if (hasAnimationOverlay) {
      strokeWidth = 1 + strength * 3 + activityIntensity * 8;
      opacity = 0.1 + activityIntensity * 0.9;
      strokeColor =
        activityIntensity > 0
          ? `rgba(255, 255, 255, ${0.45 + activityIntensity * 0.5})`
          : `rgba(0, 51, 153, ${0.2 + strength * 0.4})`;
    }

    if (edge.source === edge.target) {
      const loopRadius = 26 + strength * 16;
      const loopPath = svgElement("path", {
        d: `M ${source.x} ${source.y - 20}
            C ${source.x + loopRadius} ${source.y - 40},
              ${source.x + loopRadius} ${source.y + 5},
              ${source.x} ${source.y + 8}`,
        fill: "none",
        stroke: strokeColor,
        "stroke-width": strokeWidth,
        opacity,
        "marker-end": "url(#arrowhead)",
      });
      edgesLayer.appendChild(loopPath);
    } else {
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.sqrt(dx * dx + dy * dy) || 1;
      const normX = dx / distance;
      const normY = dy / distance;
      const offset = (index % 2 === 0 ? 1 : -1) * Math.min(distance * 0.16, 38);
      const controlX = (source.x + target.x) / 2 + -normY * offset;
      const controlY = (source.y + target.y) / 2 + normX * offset;

      const path = svgElement("path", {
        d: `M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`,
        fill: "none",
        stroke: strokeColor,
        "stroke-width": strokeWidth,
        opacity,
        "marker-end": "url(#arrowhead)",
      });
      edgesLayer.appendChild(path);

      if (hasAnimationOverlay && activeCount > 0) {
        const pulsePoint = quadraticBezierPoint(
          pulseT,
          source.x,
          source.y,
          controlX,
          controlY,
          target.x,
          target.y
        );
        const pulse = svgElement("circle", {
          cx: pulsePoint.x,
          cy: pulsePoint.y,
          r: 2.5 + activityIntensity * 6,
          fill: `rgba(255, 255, 255, ${0.42 + activityIntensity * 0.45})`,
          stroke: "rgba(255,255,255,0.85)",
          "stroke-width": 1,
        });
        pulseLayer.appendChild(pulse);
      }

      if (index < 40) {
        const label = svgElement("text", {
          x: (source.x + target.x) / 2 + -normY * offset * 0.38,
          y: (source.y + target.y) / 2 + normX * offset * 0.38,
          "text-anchor": "middle",
          "font-size": 13,
          "font-family": "IBM Plex Mono, monospace",
          fill: "#ffffff",
        });

        if (state.mode === "frequency") {
          label.textContent = hasAnimationOverlay
            ? `${formatNumber(activeCount)} / ${formatNumber(edge.frequency)}`
            : formatNumber(edge.frequency);
        } else {
          label.textContent = formatDuration(edge.median_duration_seconds);
        }

        labelsLayer.appendChild(label);
      }
    }
  });

  sortedNodes.forEach((node) => {
    const point = positionedNodes.get(node.id);
    const scale = Math.max(node.frequency / nodeMaxFrequency, 0.08);
    const size = 16 + scale * 34;

    const halo = svgElement("circle", {
      cx: point.x,
      cy: point.y,
      r: size + 6,
      fill: "rgba(0, 51, 153, 0.22)",
    });
    nodesLayer.appendChild(halo);

    const circle = svgElement("circle", {
      cx: point.x,
      cy: point.y,
      r: size,
      fill: "#003399",
      stroke: "#ffffff",
      "stroke-width": 3,
    });
    nodesLayer.appendChild(circle);

    const label = svgElement("text", {
      x: point.x,
      y: point.y + size + 18,
      "text-anchor": "middle",
      "font-size": 13,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
    });
    label.textContent = `${node.label} (${formatNumber(node.frequency)})`;
    nodesLayer.appendChild(label);

    const centerLabel = svgElement("text", {
      x: point.x,
      y: point.y + 4,
      "text-anchor": "middle",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
    });
    centerLabel.textContent = formatNumber(node.frequency);
    nodesLayer.appendChild(centerLabel);
  });

  els.processMap.appendChild(edgesLayer);
  els.processMap.appendChild(labelsLayer);
  els.processMap.appendChild(pulseLayer);
  els.processMap.appendChild(nodesLayer);
}

function renderGenericNetwork(nodes, edges, options = {}) {
  els.processMap.innerHTML = "";
  const emptyMessage = options.emptyMessage || "No diagram data available.";
  if (!nodes.length || !edges.length) {
    renderEmptyMap(emptyMessage);
    return;
  }

  const valueKey = options.valueKey || "frequency";
  const durationKey = options.durationKey || "median_duration_seconds";

  const width = 1200;
  const height = 760;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.34;

  const sortedNodes = [...nodes].sort(
    (a, b) => Number(b.frequency || 0) - Number(a.frequency || 0)
  );
  const maxNodeFrequency = Math.max(
    ...sortedNodes.map((node) => Number(node.frequency || 0)),
    1
  );
  const maxEdgeValue = Math.max(...edges.map((edge) => Number(edge[valueKey] || 0)), 1);

  const positionedNodes = new Map();
  sortedNodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / sortedNodes.length - Math.PI / 2;
    const x = centerX + radius * Math.cos(angle);
    const y = centerY + radius * 0.73 * Math.sin(angle);
    positionedNodes.set(String(node.id), { ...node, x, y });
  });

  const edgeLayer = svgElement("g");
  const labelLayer = svgElement("g");
  const nodeLayer = svgElement("g");

  edges.slice(0, 220).forEach((edge, index) => {
    const source = positionedNodes.get(String(edge.source));
    const target = positionedNodes.get(String(edge.target));
    if (!source || !target) {
      return;
    }

    const value = Number(edge[valueKey] || 0);
    const strength = Math.max(value / maxEdgeValue, 0.05);
    const strokeWidth = 1 + strength * 10;
    const color = `rgba(0, 51, 153, ${0.38 + strength * 0.55})`;

    if (String(edge.source) === String(edge.target)) {
      const loopRadius = 24 + strength * 18;
      const loopPath = svgElement("path", {
        d: `M ${source.x} ${source.y - 20}
            C ${source.x + loopRadius} ${source.y - 42},
              ${source.x + loopRadius} ${source.y + 4},
              ${source.x} ${source.y + 10}`,
        fill: "none",
        stroke: color,
        "stroke-width": strokeWidth,
        opacity: 0.68,
      });
      edgeLayer.appendChild(loopPath);
      return;
    }

    const dx = target.x - source.x;
    const dy = target.y - source.y;
    const distance = Math.sqrt(dx * dx + dy * dy) || 1;
    const normX = dx / distance;
    const normY = dy / distance;
    const offset = (index % 2 === 0 ? 1 : -1) * Math.min(distance * 0.16, 35);
    const controlX = (source.x + target.x) / 2 + -normY * offset;
    const controlY = (source.y + target.y) / 2 + normX * offset;

    const path = svgElement("path", {
      d: `M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`,
      fill: "none",
      stroke: color,
      "stroke-width": strokeWidth,
      opacity: 0.5,
    });
    edgeLayer.appendChild(path);

    if (index < 40) {
      const text = svgElement("text", {
        x: (source.x + target.x) / 2 + -normY * offset * 0.34,
        y: (source.y + target.y) / 2 + normX * offset * 0.34,
        "text-anchor": "middle",
        "font-size": 12,
        "font-family": "IBM Plex Mono, monospace",
        fill: "#ffffff",
      });
      const duration = edge[durationKey];
      text.textContent =
        duration !== undefined && duration !== null
          ? `${formatNumber(value)} | ${formatDuration(duration)}`
          : formatNumber(value);
      labelLayer.appendChild(text);
    }
  });

  sortedNodes.forEach((node) => {
    const point = positionedNodes.get(String(node.id));
    const scale = Math.max(Number(node.frequency || 0) / maxNodeFrequency, 0.1);
    const size = 16 + scale * 32;

    nodeLayer.appendChild(
      svgElement("circle", {
        cx: point.x,
        cy: point.y,
        r: size + 5,
        fill: "rgba(0, 51, 153, 0.2)",
      })
    );
    nodeLayer.appendChild(
      svgElement("circle", {
        cx: point.x,
        cy: point.y,
        r: size,
        fill: "#003399",
        stroke: "#ffffff",
        "stroke-width": 3,
      })
    );

    const center = svgElement("text", {
      x: point.x,
      y: point.y + 4,
      "text-anchor": "middle",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
    });
    center.textContent = formatNumber(node.frequency || 0);
    nodeLayer.appendChild(center);

    const label = svgElement("text", {
      x: point.x,
      y: point.y + size + 18,
      "text-anchor": "middle",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
    });
    label.textContent = `${node.label || node.id} (${formatNumber(node.frequency || 0)})`;
    nodeLayer.appendChild(label);
  });

  els.processMap.appendChild(edgeLayer);
  els.processMap.appendChild(labelLayer);
  els.processMap.appendChild(nodeLayer);
}

function renderSwimlaneDiagram(swimlane) {
  els.processMap.innerHTML = "";
  if (!swimlane?.available || !swimlane.lanes?.length || !swimlane.nodes?.length) {
    renderEmptyMap("No swimlane data available (actor column required).");
    return;
  }

  const width = 1200;
  const height = 760;
  const leftPad = 200;
  const rightPad = 40;
  const topPad = 24;
  const laneCount = swimlane.lanes.length;
  const laneHeight = (height - topPad * 2) / laneCount;

  const nodeLayer = svgElement("g");
  const laneLayer = svgElement("g");
  const edgeLayer = svgElement("g");
  const labelLayer = svgElement("g");

  const nodesByLane = new Map();
  swimlane.lanes.forEach((lane) => nodesByLane.set(lane, []));
  swimlane.nodes.forEach((node) => {
    const lane = node.lane || node.actor;
    if (!nodesByLane.has(lane)) {
      nodesByLane.set(lane, []);
    }
    nodesByLane.get(lane).push(node);
  });
  nodesByLane.forEach((nodes) =>
    nodes.sort((a, b) => Number(b.frequency || 0) - Number(a.frequency || 0))
  );

  const nodeCoords = new Map();
  swimlane.lanes.forEach((lane, laneIndex) => {
    const yTop = topPad + laneIndex * laneHeight;
    laneLayer.appendChild(
      svgElement("rect", {
        x: 20,
        y: yTop + 2,
        width: width - 40,
        height: laneHeight - 4,
        rx: 10,
        fill: laneIndex % 2 === 0 ? "rgba(0,51,153,0.12)" : "rgba(0,51,153,0.08)",
        stroke: "rgba(255,255,255,0.18)",
      })
    );
    const laneLabel = svgElement("text", {
      x: 30,
      y: yTop + laneHeight / 2 + 4,
      "font-size": 13,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
    });
    laneLabel.textContent = lane;
    laneLayer.appendChild(laneLabel);

    const laneNodes = nodesByLane.get(lane) || [];
    const usableWidth = width - leftPad - rightPad;
    const count = Math.max(laneNodes.length, 1);
    laneNodes.slice(0, 8).forEach((node, index) => {
      const x = leftPad + ((index + 0.5) * usableWidth) / count;
      const y = yTop + laneHeight / 2;
      nodeCoords.set(node.id, { x, y, node });
    });
  });

  const maxEdgeValue = Math.max(...(swimlane.edges || []).map((e) => Number(e.frequency || 0)), 1);
  (swimlane.edges || []).slice(0, 260).forEach((edge, index) => {
    const source = nodeCoords.get(edge.source);
    const target = nodeCoords.get(edge.target);
    if (!source || !target) {
      return;
    }
    const strength = Math.max(Number(edge.frequency || 0) / maxEdgeValue, 0.08);
    const offset = (index % 2 === 0 ? 1 : -1) * 10;
    const controlX = (source.x + target.x) / 2;
    const controlY = (source.y + target.y) / 2 + offset;
    edgeLayer.appendChild(
      svgElement("path", {
        d: `M ${source.x} ${source.y} Q ${controlX} ${controlY} ${target.x} ${target.y}`,
        fill: "none",
        stroke: `rgba(0, 51, 153, ${0.35 + strength * 0.55})`,
        "stroke-width": 1 + strength * 8,
        opacity: 0.45 + strength * 0.35,
      })
    );
  });

  nodeCoords.forEach(({ x, y, node }) => {
    nodeLayer.appendChild(
      svgElement("rect", {
        x: x - 56,
        y: y - 16,
        width: 112,
        height: 32,
        rx: 8,
        fill: "#003399",
        stroke: "#ffffff",
        "stroke-width": 2,
      })
    );
    const label = svgElement("text", {
      x,
      y: y + 4,
      "text-anchor": "middle",
      "font-size": 11,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
    });
    label.textContent = `${node.label} (${formatNumber(node.frequency || 0)})`;
    labelLayer.appendChild(label);
  });

  els.processMap.appendChild(laneLayer);
  els.processMap.appendChild(edgeLayer);
  els.processMap.appendChild(nodeLayer);
  els.processMap.appendChild(labelLayer);
}

function renderSankeyDiagram(sankey) {
  els.processMap.innerHTML = "";
  if (!sankey?.available || !sankey.nodes?.length || !sankey.links?.length) {
    renderEmptyMap("No sankey data available for current filters.");
    return;
  }

  const width = 1200;
  const height = 760;
  const topPad = 24;
  const bottomPad = 24;
  const leftPad = 40;
  const rightPad = 40;

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
      nodeCoords.set(node.id, { x, y, node });
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
      stroke: `rgba(0, 51, 153, ${0.3 + strength * 0.62})`,
      "stroke-width": 1 + strength * 16,
      opacity: 0.28 + strength * 0.6,
    });
    edgeLayer.appendChild(path);
  });

  nodeCoords.forEach(({ x, y, node }) => {
    nodeLayer.appendChild(
      svgElement("rect", {
        x: x - 14,
        y: y - 18,
        width: 28,
        height: 36,
        rx: 5,
        fill: "#003399",
        stroke: "#ffffff",
        "stroke-width": 2,
      })
    );
    const label = svgElement("text", {
      x,
      y: y + 30,
      "text-anchor": "middle",
      "font-size": 11,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
    });
    label.textContent = `${node.label} (${formatNumber(node.frequency || 0)})`;
    labelLayer.appendChild(label);
  });

  els.processMap.appendChild(edgeLayer);
  els.processMap.appendChild(nodeLayer);
  els.processMap.appendChild(labelLayer);
}

function renderReworkDiagram(rework) {
  els.processMap.innerHTML = "";
  const activities = rework?.activities || [];
  if (!activities.length) {
    renderEmptyMap("No rework hotspots detected for current filters.");
    return;
  }

  const width = 1200;
  const height = 760;
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
        fill: `rgba(0, 51, 153, ${0.35 + intensity * 0.55})`,
        opacity: 0.86,
      })
    );

    const nameText = svgElement("text", {
      x: leftPad - 10,
      y: y + 4,
      "text-anchor": "end",
      "font-size": 12,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
    });
    nameText.textContent = row.activity;
    textLayer.appendChild(nameText);

    const valueText = svgElement("text", {
      x: leftPad + widthScale + 8,
      y: y + 4,
      "text-anchor": "start",
      "font-size": 11,
      "font-family": "IBM Plex Mono, monospace",
      fill: "#ffffff",
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
      stroke: "rgba(255,255,255,0.35)",
      "stroke-width": 1.5,
    })
  );

  els.processMap.appendChild(axisLayer);
  els.processMap.appendChild(barLayer);
  els.processMap.appendChild(textLayer);
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
  const dashboard = state.dashboard || {};
  const handoffEnabled = Boolean(dashboard.handoff?.enabled);
  const swimlaneAvailable = Boolean(dashboard.swimlane?.available);
  const sankeyAvailable = Boolean(dashboard.sankey?.available);
  const reworkAvailable = Boolean((dashboard.rework?.activities || []).length);

  els.viewHandoffActor.disabled = !handoffEnabled;
  els.viewHandoffActivity.disabled = !handoffEnabled;
  els.viewSwimlane.disabled = !swimlaneAvailable;
  els.viewSankey.disabled = !sankeyAvailable;
  els.viewRework.disabled = !reworkAvailable;

  const invalidCurrentView =
    (state.currentView === "handoff_actor" && !handoffEnabled) ||
    (state.currentView === "handoff_activity" && !handoffEnabled) ||
    (state.currentView === "swimlane" && !swimlaneAvailable) ||
    (state.currentView === "sankey" && !sankeyAvailable) ||
    (state.currentView === "rework" && !reworkAvailable);

  if (invalidCurrentView) {
    state.currentView = "process";
  }
}

function setDiagramView(viewKey) {
  FlowScope.info("VIEW", `Switching to "${viewKey}" view`);
  state.currentView = viewKey;
  updateViewButtons();
  const t0 = performance.now();
  renderCurrentMap();
  FlowScope.debug_log("RENDER", `View "${viewKey}" rendered in ${(performance.now() - t0).toFixed(1)} ms`);
}

function renderCurrentMap() {
  if (!state.dashboard) {
    renderEmptyMap("Upload a log to start.");
    return;
  }

  const isProcessView = state.currentView === "process";
  els.toggleAnimation.disabled = !isProcessView || !state.animation.frames.length;
  els.rewindAnimation.disabled = !isProcessView || !state.animation.frames.length;
  els.animationFrame.disabled = !isProcessView || !state.animation.frames.length;
  els.animationSpeed.disabled = !isProcessView;

  if (!isProcessView) {
    stopAnimation();
  }

  if (state.currentView === "process") {
    renderProcessMap(state.dashboard.nodes, state.dashboard.edges);
    return;
  }
  if (state.currentView === "handoff_actor") {
    renderGenericNetwork(
      state.dashboard.handoff?.actor_view?.nodes || [],
      state.dashboard.handoff?.actor_view?.edges || [],
      { emptyMessage: "No actor handoff data for current filters." }
    );
    return;
  }
  if (state.currentView === "handoff_activity") {
    renderGenericNetwork(
      state.dashboard.handoff?.activity_view?.nodes || [],
      state.dashboard.handoff?.activity_view?.edges || [],
      { emptyMessage: "No activity handoff data for current filters." }
    );
    return;
  }
  if (state.currentView === "swimlane") {
    renderSwimlaneDiagram(state.dashboard.swimlane);
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
  renderProcessMap(state.dashboard.nodes, state.dashboard.edges);
}

function renderDashboard(dashboard, informationalProfile = []) {
  state.dashboard = dashboard;
  updateViewAvailability();
  updateViewButtons();
  renderMetrics(dashboard.summary);
  renderCurrentMap();
  renderEdgesTable(dashboard.edges);
  renderVariantsTable(dashboard.variants);
  renderBottlenecks(dashboard.bottlenecks);
  renderActivityStats(dashboard.activity_stats);
  renderReworkTable(dashboard.rework);
  renderRecommendations(dashboard.recommendations);
  renderInformationalColumns(informationalProfile);
}

function stopAnimation() {
  if (state.animation.timerId) {
    clearInterval(state.animation.timerId);
    state.animation.timerId = null;
  }
  state.animation.isPlaying = false;
  els.toggleAnimation.textContent = "Play Animation";
}

function updateAnimationTimeLabel() {
  if (!state.animation.frames.length) {
    els.animationTime.textContent = "No animation data";
    return;
  }

  const frame = state.animation.frames[state.animation.frameIndex];
  if (!frame) {
    els.animationTime.textContent = "No animation data";
    return;
  }

  const label = `${formatDateTime(frame.start_time)} - ${formatDateTime(frame.end_time)} | transitions ${formatNumber(frame.total_transitions || 0)}`;
  els.animationTime.textContent = label;
}

function applyAnimationData(animationPayload) {
  stopAnimation();

  state.animation.frames = animationPayload?.frames || [];
  state.animation.frameIndex = 0;
  state.animation.maxEdgeCount = Number(animationPayload?.max_edge_count_per_frame || 0);

  const frameCount = state.animation.frames.length;
  const hasFrames = frameCount > 0;

  els.animationFrame.min = "0";
  els.animationFrame.max = String(Math.max(frameCount - 1, 0));
  els.animationFrame.value = "0";

  els.toggleAnimation.disabled = !hasFrames;
  els.rewindAnimation.disabled = !hasFrames;
  els.animationFrame.disabled = !hasFrames;

  updateAnimationTimeLabel();
  renderCurrentMap();
}

function advanceAnimationFrame(step = 1) {
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
  if (!state.animation.frames.length) {
    return;
  }

  stopAnimation();
  state.animation.isPlaying = true;
  els.toggleAnimation.textContent = "Pause Animation";

  const speed = Math.max(Number(els.animationSpeed.value) || 1, 0.1);
  const intervalMs = Math.max(120, 880 / speed);

  state.animation.timerId = setInterval(() => {
    advanceAnimationFrame(1);
  }, intervalMs);
}

function toggleAnimation() {
  if (state.animation.isPlaying) {
    stopAnimation();
    return;
  }
  startAnimation();
}

async function extractError(response, fallback) {
  try {
    const payload = await response.json();
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

async function suggestMappingForCurrentFile() {
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
    FlowScope.info("ANIM", `${animationData.animation?.frame_count || 0} frames loaded`);
    applyAnimationData(animationData.animation);
  } else {
    FlowScope.warn("ANIM", `Animation fetch failed (${animationResponse.status})`);
    applyAnimationData({ frames: [], max_edge_count_per_frame: 0 });
  }
}

function setFiltersFromSummary(summary) {
  els.startTime.value = toLocalDateInput(summary.start_time);
  els.endTime.value = toLocalDateInput(summary.end_time);
}

function resetFiltersToDefaults() {
  if (state.baseSummary) {
    setFiltersFromSummary(state.baseSummary);
  }

  els.minActivityFrequency.value = "1";
  els.minEdgeFrequency.value = "1";
  els.variantTopK.value = "20";
  els.retainTopVariants.value = "";
  els.minCaseDuration.value = "";
  els.maxCaseDuration.value = "";

  Array.from(els.includeActivities.options).forEach((option) => {
    option.selected = false;
  });
  Array.from(els.excludeActivities.options).forEach((option) => {
    option.selected = false;
  });

  if (els.attributeFilters) {
    Array.from(els.attributeFilters.querySelectorAll("select[data-column]")).forEach(
      (control) => {
        Array.from(control.options).forEach((option) => {
          option.selected = false;
        });
      }
    );
  }
}

async function runConformance() {
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

els.viewProcess.addEventListener("click", () => setDiagramView("process"));
els.viewHandoffActor.addEventListener("click", () => setDiagramView("handoff_actor"));
els.viewHandoffActivity.addEventListener("click", () =>
  setDiagramView("handoff_activity")
);
els.viewSwimlane.addEventListener("click", () => setDiagramView("swimlane"));
els.viewSankey.addEventListener("click", () => setDiagramView("sankey"));
els.viewRework.addEventListener("click", () => setDiagramView("rework"));

els.toggleAnimation.addEventListener("click", () => {
  toggleAnimation();
});

els.rewindAnimation.addEventListener("click", () => {
  stopAnimation();
  state.animation.frameIndex = 0;
  els.animationFrame.value = "0";
  updateAnimationTimeLabel();
  renderCurrentMap();
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

  stopAnimation();
  state.animation.frameIndex = Math.max(0, Math.min(index, state.animation.frames.length - 1));
  updateAnimationTimeLabel();
  renderCurrentMap();
});

applyAnimationData({ frames: [], max_edge_count_per_frame: 0 });
resetMappingSelectors();
updateViewButtons();
renderAttributeFilterControls([], {});
renderInformationalColumns([]);
renderEmptyMap("Upload a log to start.");
