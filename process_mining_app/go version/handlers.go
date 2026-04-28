package main

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"
	"crypto/rand"
	"encoding/hex"
	"sync"
	"time"
)

// ---------------------------------------------------------------------------
// StoredLog
// ---------------------------------------------------------------------------

type StoredLog struct {
	LogID                string
	Filename             string
	Events               []Event
	UploadedAt           time.Time
	ColumnMapping        map[string]string
	InformationalColumns []string
	FilterOnlyColumns    []string
	FilterOnlyValues     map[string][]string
	MappingWarnings      []string
}

// ---------------------------------------------------------------------------
// In-memory store
// ---------------------------------------------------------------------------

var (
	logStore   = map[string]*StoredLog{}
	logStoreMu sync.RWMutex
)

func getLogOrError(w http.ResponseWriter, logID string) *StoredLog {
	logStoreMu.RLock()
	record, ok := logStore[logID]
	logStoreMu.RUnlock()
	if !ok {
		http.Error(w, `{"detail":"Unknown log_id"}`, http.StatusNotFound)
		return nil
	}
	return record
}

// ---------------------------------------------------------------------------
// DashboardFilterRequest (JSON body)
// ---------------------------------------------------------------------------

type DashboardFilterRequest struct {
	StartTime            *time.Time          `json:"start_time"`
	EndTime              *time.Time          `json:"end_time"`
	IncludeActivities    []string            `json:"include_activities"`
	ExcludeActivities    []string            `json:"exclude_activities"`
	AttributeFilters     map[string][]string `json:"attribute_filters"`
	MinActivityFrequency int                 `json:"min_activity_frequency"`
	MinEdgeFrequency     int                 `json:"min_edge_frequency"`
	VariantTopK          int                 `json:"variant_top_k"`
	RetainTopVariants    *int                `json:"retain_top_variants"`
	MinCaseDurationHours *float64            `json:"min_case_duration_hours"`
	MaxCaseDurationHours *float64            `json:"max_case_duration_hours"`
}

func (r *DashboardFilterRequest) ToFilterSpec() FilterSpec {
	fs := FilterSpec{
		StartTime:            r.StartTime,
		EndTime:              r.EndTime,
		IncludeActivities:    r.IncludeActivities,
		ExcludeActivities:    r.ExcludeActivities,
		AttributeFilters:     r.AttributeFilters,
		MinActivityFrequency: r.MinActivityFrequency,
		MinEdgeFrequency:     r.MinEdgeFrequency,
		VariantTopK:          r.VariantTopK,
		RetainTopVariants:    r.RetainTopVariants,
		MinCaseDurationHours: r.MinCaseDurationHours,
		MaxCaseDurationHours: r.MaxCaseDurationHours,
	}
	if fs.MinActivityFrequency < 1 {
		fs.MinActivityFrequency = 1
	}
	if fs.MinEdgeFrequency < 1 {
		fs.MinEdgeFrequency = 1
	}
	if fs.VariantTopK < 1 {
		fs.VariantTopK = 20
	}
	return fs
}

// ---------------------------------------------------------------------------
// JSON helpers
// ---------------------------------------------------------------------------

func writeJSON(w http.ResponseWriter, status int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	enc.Encode(data)
}

func readFilterBody(r *http.Request) (DashboardFilterRequest, error) {
	var req DashboardFilterRequest
	if r.Body != nil {
		defer r.Body.Close()
		body, _ := io.ReadAll(r.Body)
		if len(body) > 0 {
			if err := json.Unmarshal(body, &req); err != nil {
				return req, fmt.Errorf("invalid JSON body: %w", err)
			}
		}
	}
	return req, nil
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

func healthHandler(w http.ResponseWriter, r *http.Request) {
	logStoreMu.RLock()
	count := len(logStore)
	logStoreMu.RUnlock()
	writeJSON(w, 200, map[string]interface{}{
		"status":         "ok",
		"logs_in_memory": count,
	})
}

func uploadLogHandler(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(200 << 20); err != nil { // 200 MB max
		http.Error(w, `{"detail":"Could not parse upload"}`, 400)
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		http.Error(w, `{"detail":"Missing file"}`, 400)
		return
	}
	defer file.Close()

	content, err := io.ReadAll(file)
	if err != nil || len(content) == 0 {
		http.Error(w, `{"detail":"Uploaded file is empty"}`, 400)
		return
	}

	filename := header.Filename
	ext := strings.ToLower(filepath.Ext(filename))

	caseIDCol := r.FormValue("case_id_col")
	activityCol := r.FormValue("activity_col")
	startTsCol := r.FormValue("start_timestamp_col")
	stopTsCol := r.FormValue("stop_timestamp_col")
	actorCol := r.FormValue("actor_col")
	timestampCol := r.FormValue("timestamp_col")
	infoColsRaw := r.FormValue("informational_cols")
	filterColsRaw := r.FormValue("filter_only_cols")

	log.Printf("Upload received: %s (%.1f KB, format=%s)", filename, float64(len(content))/1024, ext)

	if ext == ".xes" {
		http.Error(w, `{"detail":"XES format requires pm4py (Python). This Go version supports CSV only."}`, 400)
		return
	}
	if ext != ".csv" {
		http.Error(w, `{"detail":"Unsupported file format. Use .csv"}`, 400)
		return
	}

	eventLog, err := LoadCSVBytes(content, caseIDCol, activityCol, startTsCol, stopTsCol, actorCol, timestampCol)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"detail":"%s"}`, err.Error()), 400)
		return
	}

	// Parse informational / filter columns
	infoCols := parseColumnList(infoColsRaw)
	filterCols := parseColumnList(filterColsRaw)

	filterOnlyValues := AttributeFilterOptions(eventLog.Events, filterCols)

	logID := generateUUID()
	now := time.Now().UTC()

	record := &StoredLog{
		LogID:                logID,
		Filename:             filename,
		Events:               eventLog.Events,
		UploadedAt:           now,
		ColumnMapping:        eventLog.ColumnMapping,
		InformationalColumns: infoCols,
		FilterOnlyColumns:    filterCols,
		FilterOnlyValues:     filterOnlyValues,
		MappingWarnings:      eventLog.MappingWarnings,
	}

	logStoreMu.Lock()
	logStore[logID] = record
	logStoreMu.Unlock()

	log.Printf("Stored log %s (%s) — %d events", logID, filename, len(eventLog.Events))

	// Compute initial dashboard
	dashboard := ComputeDashboard(eventLog.Events, DefaultFilterSpec())

	writeJSON(w, 200, map[string]interface{}{
		"log_id":                       logID,
		"filename":                     filename,
		"uploaded_at":                  now.Format(time.RFC3339),
		"summary":                      dashboard.Summary,
		"activities":                   AvailableActivities(eventLog.Events),
		"column_mapping":               eventLog.ColumnMapping,
		"informational_columns":        infoCols,
		"filter_only_columns":          filterCols,
		"attribute_filter_options":     filterOnlyValues,
		"informational_columns_profile": InformationalColumnProfile(eventLog.Events, infoCols),
		"mapping_warnings":             eventLog.MappingWarnings,
	})
}

func suggestMappingHandler(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(100 << 20); err != nil {
		http.Error(w, `{"detail":"Could not parse upload"}`, 400)
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		http.Error(w, `{"detail":"Missing file"}`, 400)
		return
	}
	defer file.Close()

	content, _ := io.ReadAll(file)
	if len(content) == 0 {
		http.Error(w, `{"detail":"Uploaded file is empty"}`, 400)
		return
	}

	filename := header.Filename
	ext := strings.ToLower(filepath.Ext(filename))
	if ext != ".csv" {
		writeJSON(w, 200, map[string]interface{}{
			"filename":  filename,
			"supported": false,
			"message":   "Auto-suggestion is available for CSV uploads.",
			"mapping":   map[string]interface{}{},
		})
		return
	}

	mapping, err := SuggestCSVMapping(content)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"detail":"%s"}`, err.Error()), 400)
		return
	}

	writeJSON(w, 200, map[string]interface{}{
		"filename":  filename,
		"supported": true,
		"mapping":   mapping,
	})
}

func listLogsHandler(w http.ResponseWriter, r *http.Request) {
	logStoreMu.RLock()
	logs := make([]map[string]string, 0, len(logStore))
	for _, record := range logStore {
		logs = append(logs, map[string]string{
			"log_id":      record.LogID,
			"filename":    record.Filename,
			"uploaded_at": record.UploadedAt.Format(time.RFC3339),
		})
	}
	logStoreMu.RUnlock()
	writeJSON(w, 200, map[string]interface{}{"logs": logs})
}

func logOverviewHandler(w http.ResponseWriter, r *http.Request, logID string) {
	record := getLogOrError(w, logID)
	if record == nil {
		return
	}

	dashboard := ComputeDashboard(record.Events, DefaultFilterSpec())
	writeJSON(w, 200, map[string]interface{}{
		"log_id":                        record.LogID,
		"filename":                      record.Filename,
		"summary":                       dashboard.Summary,
		"activities":                    AvailableActivities(record.Events),
		"column_mapping":                record.ColumnMapping,
		"informational_columns":         record.InformationalColumns,
		"filter_only_columns":           record.FilterOnlyColumns,
		"attribute_filter_options":      record.FilterOnlyValues,
		"informational_columns_profile": InformationalColumnProfile(record.Events, record.InformationalColumns),
		"mapping_warnings":              record.MappingWarnings,
	})
}

func logDashboardHandler(w http.ResponseWriter, r *http.Request, logID string) {
	record := getLogOrError(w, logID)
	if record == nil {
		return
	}

	req, err := readFilterBody(r)
	if err != nil {
		http.Error(w, fmt.Sprintf(`{"detail":"%s"}`, err.Error()), 400)
		return
	}
	filters := req.ToFilterSpec()

	dashboard := ComputeDashboard(record.Events, filters)
	filtered := ApplyFilters(record.Events, filters)
	infoProfile := InformationalColumnProfile(filtered, record.InformationalColumns)

	writeJSON(w, 200, map[string]interface{}{
		"log_id":                        record.LogID,
		"filename":                      record.Filename,
		"filters":                       req,
		"dashboard":                     dashboard,
		"column_mapping":                record.ColumnMapping,
		"informational_columns":         record.InformationalColumns,
		"filter_only_columns":           record.FilterOnlyColumns,
		"attribute_filter_options":      record.FilterOnlyValues,
		"informational_columns_profile": infoProfile,
		"mapping_warnings":              record.MappingWarnings,
	})
}

func logConformanceHandler(w http.ResponseWriter, r *http.Request, logID string) {
	record := getLogOrError(w, logID)
	if record == nil {
		return
	}

	req, _ := readFilterBody(r)

	// Note: Conformance checking requires pm4py (Python). The Go version
	// returns a placeholder indicating this feature is not available.
	writeJSON(w, 200, map[string]interface{}{
		"log_id":   record.LogID,
		"filename": record.Filename,
		"filters":  req,
		"conformance": map[string]interface{}{
			"supported": false,
			"message":   "Conformance checking (Petri net discovery + token replay) requires pm4py. Use the Python version for this feature.",
		},
	})
}

func logAnimationHandler(w http.ResponseWriter, r *http.Request, logID string) {
	record := getLogOrError(w, logID)
	if record == nil {
		return
	}

	req, _ := readFilterBody(r)
	filters := req.ToFilterSpec()

	frameCount := 80
	if fc := r.URL.Query().Get("frame_count"); fc != "" {
		if n, err := strconv.Atoi(fc); err == nil && n > 0 {
			frameCount = n
		}
	}

	animation := ComputeAnimation(record.Events, filters, frameCount)
	writeJSON(w, 200, map[string]interface{}{
		"log_id":    record.LogID,
		"filename":  record.Filename,
		"filters":   req,
		"animation": animation,
	})
}

func logExportZipHandler(w http.ResponseWriter, r *http.Request, logID string) {
	record := getLogOrError(w, logID)
	if record == nil {
		return
	}

	req, _ := readFilterBody(r)
	filters := req.ToFilterSpec()

	dashboard := ComputeDashboard(record.Events, filters)
	animation := ComputeAnimation(record.Events, filters, 80)
	filtered := ApplyFilters(record.Events, filters)
	infoProfile := InformationalColumnProfile(filtered, record.InformationalColumns)
	mermaidDiagrams := GenerateMermaidExport(dashboard)

	// Build ZIP
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)

	// summary.json
	metadata := map[string]interface{}{
		"exported_at":            time.Now().UTC().Format(time.RFC3339),
		"filename":              record.Filename,
		"log_id":                record.LogID,
		"filters":               req,
		"summary":               dashboard.Summary,
		"column_mapping":        record.ColumnMapping,
		"informational_columns": record.InformationalColumns,
		"filter_only_columns":   record.FilterOnlyColumns,
		"mapping_warnings":      record.MappingWarnings,
	}
	addJSONToZip(zw, "summary.json", metadata)
	addCSVToZip(zw, "nodes.csv", nodeStatToRecords(dashboard.Nodes))
	addCSVToZip(zw, "edges.csv", edgeStatToRecords(dashboard.Edges))
	addCSVToZip(zw, "variants.csv", variantStatToRecords(dashboard.Variants))
	addCSVToZip(zw, "bottlenecks.csv", edgeStatToRecords(dashboard.Bottlenecks))
	addCSVToZip(zw, "activity_stats.csv", activityStatToRecords(dashboard.ActivityStats))
	addJSONToZip(zw, "animation_frames.json", animation)
	addJSONToZip(zw, "informational_columns_profile.json", infoProfile)
	addCSVToZip(zw, "handoff_actor_edges.csv", edgeStatToRecords(dashboard.Handoff.ActorView.Edges))
	addCSVToZip(zw, "handoff_activity_edges.csv", edgeStatToRecords(dashboard.Handoff.ActivityView.Edges))

	// Swimlane nodes/edges
	swimNodes := make([]map[string]string, len(dashboard.Swimlane.Nodes))
	for i, n := range dashboard.Swimlane.Nodes {
		swimNodes[i] = map[string]string{
			"id": n.ID, "label": n.Label, "actor": n.Actor, "lane": n.Lane,
			"frequency": strconv.Itoa(n.Frequency),
		}
	}
	addCSVFromMaps(zw, "swimlane_nodes.csv", swimNodes)

	swimEdges := make([]map[string]string, len(dashboard.Swimlane.Edges))
	for i, e := range dashboard.Swimlane.Edges {
		swimEdges[i] = map[string]string{
			"source": e.Source, "target": e.Target, "frequency": strconv.Itoa(e.Frequency),
			"median_duration_seconds": fmt.Sprintf("%.2f", e.MedianDurationSeconds),
		}
	}
	addCSVFromMaps(zw, "swimlane_edges.csv", swimEdges)

	// Sankey links
	sankeyLinks := make([]map[string]string, len(dashboard.Sankey.Links))
	for i, l := range dashboard.Sankey.Links {
		sankeyLinks[i] = map[string]string{
			"source": l.Source, "target": l.Target, "value": strconv.Itoa(l.Value),
			"median_duration_seconds": fmt.Sprintf("%.2f", l.MedianDurationSeconds),
		}
	}
	addCSVFromMaps(zw, "sankey_links.csv", sankeyLinks)

	// Rework
	reworkActs := make([]map[string]string, len(dashboard.Rework.Activities))
	for i, a := range dashboard.Rework.Activities {
		reworkActs[i] = map[string]string{
			"activity": a.Activity, "cases_with_rework": strconv.Itoa(a.CasesWithRework),
			"rework_events": strconv.Itoa(a.ReworkEvents),
			"rework_case_ratio": fmt.Sprintf("%.4f", a.ReworkCaseRatio),
		}
	}
	addCSVFromMaps(zw, "rework_activity.csv", reworkActs)

	reworkLoops := make([]map[string]string, len(dashboard.Rework.SelfLoops))
	for i, l := range dashboard.Rework.SelfLoops {
		reworkLoops[i] = map[string]string{
			"activity": l.Activity, "frequency": strconv.Itoa(l.Frequency),
		}
	}
	addCSVFromMaps(zw, "rework_self_loops.csv", reworkLoops)

	// Mermaid diagrams
	for name, body := range mermaidDiagrams {
		w2, _ := zw.Create(name + ".mmd")
		w2.Write([]byte(body))
	}

	// Filtered events CSV
	addFilteredEventsCSV(zw, filtered)

	zw.Close()

	safeName := safeExportBasename(record.Filename)
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s-analysis-export.zip"`, safeName))
	w.Write(buf.Bytes())
}

func logExportHTMLHandler(w http.ResponseWriter, r *http.Request, logID string) {
	record := getLogOrError(w, logID)
	if record == nil {
		return
	}

	req, _ := readFilterBody(r)
	filters := req.ToFilterSpec()

	dashboard := ComputeDashboard(record.Events, filters)
	animation := ComputeAnimation(record.Events, filters, 80)
	mermaidDiagrams := GenerateMermaidExport(dashboard)

	exportedAt := time.Now().UTC().Format(time.RFC3339)
	html := BuildHTMLReport(
		record.Filename, record.LogID, exportedAt,
		req, dashboard, animation, mermaidDiagrams,
	)

	safeName := safeExportBasename(record.Filename)
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s-analysis-report.html"`, safeName))
	w.Write([]byte(html))
}

// ---------------------------------------------------------------------------
// ZIP helpers
// ---------------------------------------------------------------------------

func addJSONToZip(zw *zip.Writer, name string, data interface{}) {
	w, _ := zw.Create(name)
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	enc.Encode(data)
}

func addCSVToZip(zw *zip.Writer, name string, records []map[string]string) {
	addCSVFromMaps(zw, name, records)
}

func addCSVFromMaps(zw *zip.Writer, name string, records []map[string]string) {
	w, _ := zw.Create(name)
	if len(records) == 0 {
		w.Write([]byte(""))
		return
	}
	// Collect headers
	headerSet := map[string]bool{}
	var headers []string
	for _, rec := range records {
		for k := range rec {
			if !headerSet[k] {
				headerSet[k] = true
				headers = append(headers, k)
			}
		}
	}
	// Write header line
	w.Write([]byte(strings.Join(headers, ",") + "\n"))
	for _, rec := range records {
		vals := make([]string, len(headers))
		for i, h := range headers {
			vals[i] = csvQuote(rec[h])
		}
		w.Write([]byte(strings.Join(vals, ",") + "\n"))
	}
}

func addFilteredEventsCSV(zw *zip.Writer, events []Event) {
	w, _ := zw.Create("filtered_events.csv")
	if len(events) == 0 {
		return
	}
	// Collect all extra columns
	extraCols := map[string]bool{}
	for _, e := range events {
		for k := range e.Extra {
			extraCols[k] = true
		}
	}
	var extraHeaders []string
	for k := range extraCols {
		extraHeaders = append(extraHeaders, k)
	}
	sort.Strings(extraHeaders)

	headers := []string{"case_id", "activity", "timestamp", "start_timestamp", "end_timestamp", "actor"}
	headers = append(headers, extraHeaders...)
	w.Write([]byte(strings.Join(headers, ",") + "\n"))

	for _, e := range events {
		startTs := ""
		if e.StartTimestamp != nil {
			startTs = e.StartTimestamp.Format(time.RFC3339)
		}
		endTs := ""
		if e.EndTimestamp != nil {
			endTs = e.EndTimestamp.Format(time.RFC3339)
		}
		vals := []string{
			csvQuote(e.CaseID),
			csvQuote(e.Activity),
			e.Timestamp.Format(time.RFC3339),
			startTs,
			endTs,
			csvQuote(e.Actor),
		}
		for _, h := range extraHeaders {
			vals = append(vals, csvQuote(e.Extra[h]))
		}
		w.Write([]byte(strings.Join(vals, ",") + "\n"))
	}
}

func csvQuote(s string) string {
	if strings.ContainsAny(s, ",\"\n\r") {
		return `"` + strings.ReplaceAll(s, `"`, `""`) + `"`
	}
	return s
}

func nodeStatToRecords(nodes []NodeStat) []map[string]string {
	records := make([]map[string]string, len(nodes))
	for i, n := range nodes {
		records[i] = map[string]string{
			"id": n.ID, "label": n.Label,
			"frequency": strconv.Itoa(n.Frequency),
			"start_count": strconv.Itoa(n.StartCount),
			"end_count": strconv.Itoa(n.EndCount),
		}
	}
	return records
}

func edgeStatToRecords(edges []EdgeStat) []map[string]string {
	records := make([]map[string]string, len(edges))
	for i, e := range edges {
		records[i] = map[string]string{
			"source": e.Source, "target": e.Target,
			"frequency":                strconv.Itoa(e.Frequency),
			"mean_duration_seconds":    fmt.Sprintf("%.2f", e.MeanDurationSeconds),
			"median_duration_seconds":  fmt.Sprintf("%.2f", e.MedianDurationSeconds),
			"p90_duration_seconds":     fmt.Sprintf("%.2f", e.P90DurationSeconds),
		}
	}
	return records
}

func variantStatToRecords(variants []VariantStat) []map[string]string {
	records := make([]map[string]string, len(variants))
	for i, v := range variants {
		records[i] = map[string]string{
			"rank":                  strconv.Itoa(v.Rank),
			"variant":              v.Variant,
			"cases":                strconv.Itoa(v.Cases),
			"share":                fmt.Sprintf("%.4f", v.Share),
			"avg_duration_hours":   fmt.Sprintf("%.2f", v.AvgDurationHours),
			"median_duration_hours": fmt.Sprintf("%.2f", v.MedianDurationHours),
		}
	}
	return records
}

func activityStatToRecords(stats []ActivityStat) []map[string]string {
	records := make([]map[string]string, len(stats))
	for i, s := range stats {
		records[i] = map[string]string{
			"activity":      s.Activity,
			"frequency":     strconv.Itoa(s.Frequency),
			"case_coverage": fmt.Sprintf("%.4f", s.CaseCoverage),
		}
	}
	return records
}

func generateUUID() string {
	b := make([]byte, 16)
	rand.Read(b)
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%s-%s-%s-%s-%s",
		hex.EncodeToString(b[0:4]),
		hex.EncodeToString(b[4:6]),
		hex.EncodeToString(b[6:8]),
		hex.EncodeToString(b[8:10]),
		hex.EncodeToString(b[10:16]),
	)
}

func parseColumnList(value string) []string {
	if value == "" {
		return []string{}
	}
	var result []string
	seen := map[string]bool{}
	for _, part := range strings.FieldsFunc(value, func(r rune) bool {
		return r == ',' || r == '\n' || r == ';'
	}) {
		col := strings.TrimSpace(part)
		if col != "" && !seen[col] {
			seen[col] = true
			result = append(result, col)
		}
	}
	return result
}
