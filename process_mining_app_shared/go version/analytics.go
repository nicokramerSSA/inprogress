package main

import (
	"encoding/csv"
	"fmt"
	"io"
	"log"
	"math"
	"regexp"
	"sort"
	"strings"
	"time"
)

// ---------------------------------------------------------------------------
// Column constants (matching pm4py conventions)
// ---------------------------------------------------------------------------

const (
	CaseColumn           = "case:concept:name"
	ActivityColumn       = "concept:name"
	TimestampColumn      = "time:timestamp"
	StartTimestampColumn = "time:start_timestamp"
	EndTimestampColumn   = "time:end_timestamp"
	ActorColumn          = "org:resource"
)

var actorColumnCandidates = []string{
	ActorColumn, "resource", "actor", "user", "assignee", "performer", "org:role",
}

// ---------------------------------------------------------------------------
// Event & EventLog
// ---------------------------------------------------------------------------

// Event represents a single row in an event log.
type Event struct {
	CaseID         string
	Activity       string
	Timestamp      time.Time
	StartTimestamp *time.Time
	EndTimestamp   *time.Time
	Actor          string
	Extra          map[string]string // additional columns
}

// EventLog holds the parsed event data.
type EventLog struct {
	Events               []Event
	Columns              []string
	ActorColumn          string
	HasStartTimestamp     bool
	HasEndTimestamp       bool
	ColumnMapping        map[string]string
	InformationalColumns []string
	FilterOnlyColumns    []string
	FilterOnlyValues     map[string][]string
	MappingWarnings      []string
}

// ---------------------------------------------------------------------------
// FilterSpec
// ---------------------------------------------------------------------------

type FilterSpec struct {
	StartTime            *time.Time        `json:"start_time"`
	EndTime              *time.Time        `json:"end_time"`
	IncludeActivities    []string          `json:"include_activities"`
	ExcludeActivities    []string          `json:"exclude_activities"`
	AttributeFilters     map[string][]string `json:"attribute_filters"`
	MinActivityFrequency int               `json:"min_activity_frequency"`
	MinEdgeFrequency     int               `json:"min_edge_frequency"`
	VariantTopK          int               `json:"variant_top_k"`
	RetainTopVariants    *int              `json:"retain_top_variants"`
	MinCaseDurationHours *float64          `json:"min_case_duration_hours"`
	MaxCaseDurationHours *float64          `json:"max_case_duration_hours"`
}

func DefaultFilterSpec() FilterSpec {
	return FilterSpec{
		MinActivityFrequency: 1,
		MinEdgeFrequency:     1,
		VariantTopK:          20,
	}
}

// ---------------------------------------------------------------------------
// AnalyticsError
// ---------------------------------------------------------------------------

type AnalyticsError struct {
	Message string
}

func (e *AnalyticsError) Error() string { return e.Message }

// ---------------------------------------------------------------------------
// Transition
// ---------------------------------------------------------------------------

type Transition struct {
	CaseID          string
	Source          string
	Target          string
	SourceTimestamp time.Time
	TransitionTime time.Time
	DurationSeconds float64
	SourceActor     string
	TargetActor     string
}

// ---------------------------------------------------------------------------
// CSV Parsing
// ---------------------------------------------------------------------------

func parseTimestamp(s string) (time.Time, bool) {
	s = strings.TrimSpace(s)
	if s == "" || s == "NaT" || s == "nan" || s == "None" {
		return time.Time{}, false
	}
	formats := []string{
		time.RFC3339Nano,
		time.RFC3339,
		"2006-01-02T15:04:05",
		"2006-01-02 15:04:05",
		"2006-01-02T15:04:05Z07:00",
		"2006-01-02 15:04:05.000",
		"2006-01-02T15:04:05.000",
		"2006-01-02 15:04:05.000000",
		"2006-01-02T15:04:05.000000",
		"2006-01-02",
		"01/02/2006 15:04:05",
		"01/02/2006 3:04:05 PM",
		"1/2/2006 15:04",
		"02-Jan-2006 15:04:05",
	}
	for _, f := range formats {
		if t, err := time.Parse(f, s); err == nil {
			return t.UTC(), true
		}
	}
	return time.Time{}, false
}

func isCleanActorValue(s string) bool {
	s = strings.TrimSpace(s)
	return s != "" && s != "nan" && s != "None" && s != "NaT"
}

func cleanActorValue(s string) string {
	s = strings.TrimSpace(s)
	if s == "" || s == "nan" || s == "None" || s == "NaT" {
		return ""
	}
	return s
}

// LoadCSVBytes parses CSV content into an EventLog, using column mapping hints.
func LoadCSVBytes(content []byte, caseIDCol, activityCol, startTimestampCol, stopTimestampCol, actorCol, timestampCol string) (*EventLog, error) {
	reader := csv.NewReader(strings.NewReader(string(content)))
	reader.LazyQuotes = true
	reader.TrimLeadingSpace = true
	reader.FieldsPerRecord = -1

	header, err := reader.Read()
	if err != nil {
		return nil, &AnalyticsError{Message: "Could not read CSV header: " + err.Error()}
	}
	if len(header) <= 1 {
		// Try semicolon-separated
		reader2 := csv.NewReader(strings.NewReader(string(content)))
		reader2.Comma = ';'
		reader2.LazyQuotes = true
		reader2.TrimLeadingSpace = true
		reader2.FieldsPerRecord = -1
		h2, err2 := reader2.Read()
		if err2 == nil && len(h2) > 1 {
			header = h2
			reader = reader2
		}
	}

	colIndex := map[string]int{}
	for i, h := range header {
		colIndex[strings.TrimSpace(h)] = i
	}

	// Auto-detect columns using suggestions
	suggestions := suggestMappingFromHeaders(header, colIndex)
	resolve := func(input, suggestionKey string) string {
		input = strings.TrimSpace(input)
		if input != "" {
			if _, ok := colIndex[input]; ok {
				return input
			}
		}
		if s, ok := suggestions[suggestionKey]; ok && s != "" {
			return s
		}
		return input
	}

	caseIDCol = resolve(caseIDCol, "case_id_col")
	activityCol = resolve(activityCol, "activity_col")
	startTimestampCol = resolve(startTimestampCol, "start_timestamp_col")
	stopTimestampCol = resolve(stopTimestampCol, "stop_timestamp_col")
	actorCol = resolve(actorCol, "actor_col")

	if timestampCol != "" && startTimestampCol == "" && stopTimestampCol == "" {
		if _, ok := colIndex[timestampCol]; ok {
			startTimestampCol = timestampCol
		}
	}

	// Fallbacks for timestamps
	if startTimestampCol == "" || colIndex[startTimestampCol] < 0 {
		for _, c := range []string{"start_timestamp", "time:start_timestamp", "start_time", "time:timestamp", "timestamp"} {
			if _, ok := colIndex[c]; ok {
				startTimestampCol = c
				break
			}
		}
	}
	if stopTimestampCol == "" {
		for _, c := range []string{"stop_timestamp", "end_timestamp", "time:end_timestamp", "complete_timestamp", "completion_time"} {
			if _, ok := colIndex[c]; ok {
				stopTimestampCol = c
				break
			}
		}
	}

	if caseIDCol == "" {
		return nil, &AnalyticsError{Message: "CSV mapping could not determine required columns: case id"}
	}
	if activityCol == "" {
		return nil, &AnalyticsError{Message: "CSV mapping could not determine required columns: activity"}
	}
	if startTimestampCol == "" && stopTimestampCol == "" {
		return nil, &AnalyticsError{Message: "CSV must include at least one timestamp column"}
	}

	caseIdx, caseOK := colIndex[caseIDCol]
	actIdx, actOK := colIndex[activityCol]
	if !caseOK || !actOK {
		return nil, &AnalyticsError{Message: "Mapped columns not found in CSV header"}
	}

	startIdx := -1
	if startTimestampCol != "" {
		if i, ok := colIndex[startTimestampCol]; ok {
			startIdx = i
		}
	}
	stopIdx := -1
	if stopTimestampCol != "" {
		if i, ok := colIndex[stopTimestampCol]; ok {
			stopIdx = i
		}
	}
	actorIdx := -1
	if actorCol != "" {
		if i, ok := colIndex[actorCol]; ok {
			actorIdx = i
		}
	}

	hasStart := startIdx >= 0
	hasStop := stopIdx >= 0

	if !hasStart && !hasStop {
		return nil, &AnalyticsError{Message: "No valid timestamp column found in CSV"}
	}

	// Detect actor column from defaults if not specified
	detectedActorCol := actorCol
	if actorIdx < 0 {
		for _, c := range actorColumnCandidates {
			if i, ok := colIndex[c]; ok {
				actorIdx = i
				detectedActorCol = c
				break
			}
		}
	}

	// Parse all rows
	var events []Event
	for {
		record, err := reader.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			continue
		}
		if len(record) <= caseIdx || len(record) <= actIdx {
			continue
		}

		caseID := strings.TrimSpace(record[caseIdx])
		activity := strings.TrimSpace(record[actIdx])
		if caseID == "" || activity == "" {
			continue
		}

		var startTs, stopTs *time.Time
		var mainTs time.Time
		var hasMainTs bool

		if hasStart && len(record) > startIdx {
			if t, ok := parseTimestamp(record[startIdx]); ok {
				startTs = &t
			}
		}
		if hasStop && len(record) > stopIdx {
			if t, ok := parseTimestamp(record[stopIdx]); ok {
				stopTs = &t
			}
		}

		// Derive main timestamp: prefer end, then start
		if stopTs != nil {
			mainTs = *stopTs
			hasMainTs = true
		} else if startTs != nil {
			mainTs = *startTs
			hasMainTs = true
		}
		if !hasMainTs {
			continue
		}

		actor := ""
		if actorIdx >= 0 && len(record) > actorIdx {
			actor = cleanActorValue(record[actorIdx])
		}

		// Capture extra columns
		extra := map[string]string{}
		for colName, idx := range colIndex {
			if idx == caseIdx || idx == actIdx || idx == startIdx || idx == stopIdx || idx == actorIdx {
				continue
			}
			if idx < len(record) {
				extra[colName] = strings.TrimSpace(record[idx])
			}
		}

		events = append(events, Event{
			CaseID:         caseID,
			Activity:       activity,
			Timestamp:      mainTs,
			StartTimestamp: startTs,
			EndTimestamp:   stopTs,
			Actor:          actor,
			Extra:          extra,
		})
	}

	if len(events) == 0 {
		return nil, &AnalyticsError{Message: "No valid events found in CSV"}
	}

	// Sort by case, then timestamp
	sort.SliceStable(events, func(i, j int) bool {
		if events[i].CaseID != events[j].CaseID {
			return events[i].CaseID < events[j].CaseID
		}
		return events[i].Timestamp.Before(events[j].Timestamp)
	})

	el := &EventLog{
		Events:            events,
		Columns:           header,
		ActorColumn:       detectedActorCol,
		HasStartTimestamp: hasStart,
		HasEndTimestamp:   hasStop,
		ColumnMapping: map[string]string{
			"case_id_col":          caseIDCol,
			"activity_col":         activityCol,
			"start_timestamp_col":  startTimestampCol,
			"stop_timestamp_col":   stopTimestampCol,
			"actor_col":            detectedActorCol,
		},
		FilterOnlyValues: map[string][]string{},
	}

	return el, nil
}

// suggestMappingFromHeaders returns best-guess column mappings based on header names.
func suggestMappingFromHeaders(header []string, colIndex map[string]int) map[string]string {
	suggestions := map[string]string{}
	lowerMap := map[string]string{} // lowercase -> original
	for _, h := range header {
		lowerMap[strings.ToLower(strings.TrimSpace(h))] = h
	}

	// Case ID
	for _, candidate := range []string{"case:concept:name", "case_id", "caseid", "trace_id"} {
		if orig, ok := lowerMap[candidate]; ok {
			suggestions["case_id_col"] = orig
			break
		}
	}
	if suggestions["case_id_col"] == "" {
		for _, h := range header {
			lower := strings.ToLower(h)
			if strings.Contains(lower, "case") && strings.Contains(lower, "id") {
				suggestions["case_id_col"] = h
				break
			}
		}
	}

	// Activity
	for _, candidate := range []string{"concept:name", "activity", "task", "event"} {
		if orig, ok := lowerMap[candidate]; ok {
			suggestions["activity_col"] = orig
			break
		}
	}

	// Start timestamp
	for _, candidate := range []string{"time:start_timestamp", "start_timestamp", "start_time"} {
		if orig, ok := lowerMap[candidate]; ok {
			suggestions["start_timestamp_col"] = orig
			break
		}
	}
	if suggestions["start_timestamp_col"] == "" {
		for _, candidate := range []string{"time:timestamp", "timestamp", "datetime", "date", "time"} {
			if orig, ok := lowerMap[candidate]; ok {
				suggestions["start_timestamp_col"] = orig
				break
			}
		}
	}

	// Stop timestamp
	for _, candidate := range []string{"time:end_timestamp", "end_timestamp", "stop_timestamp", "complete_timestamp", "completion_time"} {
		if orig, ok := lowerMap[candidate]; ok {
			suggestions["stop_timestamp_col"] = orig
			break
		}
	}

	// Actor
	for _, candidate := range []string{"org:resource", "resource", "actor", "user", "assignee"} {
		if orig, ok := lowerMap[candidate]; ok {
			suggestions["actor_col"] = orig
			break
		}
	}

	return suggestions
}

// SuggestCSVMapping returns column suggestions for a CSV file.
func SuggestCSVMapping(content []byte) (map[string]interface{}, error) {
	reader := csv.NewReader(strings.NewReader(string(content)))
	reader.LazyQuotes = true
	reader.TrimLeadingSpace = true
	reader.FieldsPerRecord = -1

	header, err := reader.Read()
	if err != nil {
		return nil, &AnalyticsError{Message: "Could not read CSV: " + err.Error()}
	}

	colIndex := map[string]int{}
	for i, h := range header {
		colIndex[strings.TrimSpace(h)] = i
	}

	suggestions := suggestMappingFromHeaders(header, colIndex)
	columns := make([]string, len(header))
	for i, h := range header {
		columns[i] = strings.TrimSpace(h)
	}

	return map[string]interface{}{
		"columns":     columns,
		"suggestions": suggestions,
		"confidence":  map[string]interface{}{},
		"candidates":  map[string]interface{}{},
		"suggested_filter_only_columns":    []string{},
		"suggested_informational_columns":  []string{},
	}, nil
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

func ApplyFilters(events []Event, filters FilterSpec) []Event {
	result := make([]Event, 0, len(events))

	includeSet := toStringSet(filters.IncludeActivities)
	excludeSet := toStringSet(filters.ExcludeActivities)

	for _, e := range events {
		if filters.StartTime != nil && e.Timestamp.Before(*filters.StartTime) {
			continue
		}
		if filters.EndTime != nil && e.Timestamp.After(*filters.EndTime) {
			continue
		}
		if len(includeSet) > 0 && !includeSet[e.Activity] {
			continue
		}
		if excludeSet[e.Activity] {
			continue
		}

		// Attribute filters
		skip := false
		for col, values := range filters.AttributeFilters {
			if len(values) == 0 {
				continue
			}
			valSet := toStringSet(values)
			val := e.Extra[col]
			if e.Actor != "" && col == "actor" {
				val = e.Actor
			}
			if !valSet[strings.TrimSpace(val)] {
				skip = true
				break
			}
		}
		if skip {
			continue
		}

		result = append(result, e)
	}

	// Activity frequency filter
	minFreq := filters.MinActivityFrequency
	if minFreq < 1 {
		minFreq = 1
	}
	if minFreq > 1 && len(result) > 0 {
		actCounts := map[string]int{}
		for _, e := range result {
			actCounts[e.Activity]++
		}
		filtered := make([]Event, 0, len(result))
		for _, e := range result {
			if actCounts[e.Activity] >= minFreq {
				filtered = append(filtered, e)
			}
		}
		result = filtered
	}

	if len(result) == 0 {
		return result
	}

	// Case duration filters
	if filters.MinCaseDurationHours != nil || filters.MaxCaseDurationHours != nil {
		caseMetrics := computeCaseMetrics(result)
		keepCases := map[string]bool{}
		for _, cm := range caseMetrics {
			if filters.MinCaseDurationHours != nil && cm.DurationHours < *filters.MinCaseDurationHours {
				continue
			}
			if filters.MaxCaseDurationHours != nil && cm.DurationHours > *filters.MaxCaseDurationHours {
				continue
			}
			keepCases[cm.CaseID] = true
		}
		filtered := make([]Event, 0, len(result))
		for _, e := range result {
			if keepCases[e.CaseID] {
				filtered = append(filtered, e)
			}
		}
		result = filtered
	}

	// Retain top variants
	if filters.RetainTopVariants != nil && *filters.RetainTopVariants > 0 && len(result) > 0 {
		variants := buildCaseVariants(result)
		variantCounts := map[string]int{}
		for _, v := range variants {
			variantCounts[v.Variant]++
		}
		type vc struct {
			Variant string
			Count   int
		}
		var sorted []vc
		for v, c := range variantCounts {
			sorted = append(sorted, vc{v, c})
		}
		sort.Slice(sorted, func(i, j int) bool { return sorted[i].Count > sorted[j].Count })
		topN := *filters.RetainTopVariants
		if topN > len(sorted) {
			topN = len(sorted)
		}
		topVariants := map[string]bool{}
		for i := 0; i < topN; i++ {
			topVariants[sorted[i].Variant] = true
		}
		variantByCase := map[string]string{}
		for _, v := range variants {
			variantByCase[v.CaseID] = v.Variant
		}
		filtered := make([]Event, 0, len(result))
		for _, e := range result {
			if topVariants[variantByCase[e.CaseID]] {
				filtered = append(filtered, e)
			}
		}
		result = filtered
	}

	// Re-sort
	sort.SliceStable(result, func(i, j int) bool {
		if result[i].CaseID != result[j].CaseID {
			return result[i].CaseID < result[j].CaseID
		}
		return result[i].Timestamp.Before(result[j].Timestamp)
	})

	return result
}

// ---------------------------------------------------------------------------
// Case Metrics
// ---------------------------------------------------------------------------

type CaseMetric struct {
	CaseID        string
	StartTime     time.Time
	EndTime       time.Time
	DurationHours float64
	EventCount    int
}

func computeCaseMetrics(events []Event) []CaseMetric {
	type caseTimes struct {
		start  time.Time
		end    time.Time
		count  int
		hasVal bool
	}
	caseMap := map[string]*caseTimes{}
	for _, e := range events {
		ct, ok := caseMap[e.CaseID]
		if !ok {
			ct = &caseTimes{}
			caseMap[e.CaseID] = ct
		}

		evStart := e.Timestamp
		if e.StartTimestamp != nil {
			evStart = *e.StartTimestamp
		}
		evEnd := e.Timestamp
		if e.EndTimestamp != nil {
			evEnd = *e.EndTimestamp
		}

		if !ct.hasVal || evStart.Before(ct.start) {
			ct.start = evStart
		}
		if !ct.hasVal || evEnd.After(ct.end) {
			ct.end = evEnd
		}
		ct.count++
		ct.hasVal = true
	}

	result := make([]CaseMetric, 0, len(caseMap))
	for caseID, ct := range caseMap {
		dur := ct.end.Sub(ct.start).Hours()
		result = append(result, CaseMetric{
			CaseID:        caseID,
			StartTime:     ct.start,
			EndTime:       ct.end,
			DurationHours: dur,
			EventCount:    ct.count,
		})
	}
	return result
}

// ---------------------------------------------------------------------------
// Variants
// ---------------------------------------------------------------------------

type CaseVariant struct {
	CaseID  string
	Variant string
}

func buildCaseVariants(events []Event) []CaseVariant {
	caseActivities := map[string][]string{}
	for _, e := range events {
		caseActivities[e.CaseID] = append(caseActivities[e.CaseID], e.Activity)
	}
	result := make([]CaseVariant, 0, len(caseActivities))
	for caseID, acts := range caseActivities {
		result = append(result, CaseVariant{
			CaseID:  caseID,
			Variant: strings.Join(acts, " -> "),
		})
	}
	return result
}

// ---------------------------------------------------------------------------
// Transitions
// ---------------------------------------------------------------------------

func computeTransitions(events []Event) []Transition {
	// Group by case
	caseEvents := map[string][]Event{}
	for _, e := range events {
		caseEvents[e.CaseID] = append(caseEvents[e.CaseID], e)
	}

	var transitions []Transition
	for caseID, evts := range caseEvents {
		for i := 0; i < len(evts)-1; i++ {
			src := evts[i]
			tgt := evts[i+1]

			srcTime := src.Timestamp
			if src.EndTimestamp != nil {
				srcTime = *src.EndTimestamp
			}
			tgtTime := tgt.Timestamp
			if tgt.StartTimestamp != nil {
				tgtTime = *tgt.StartTimestamp
			}

			dur := tgtTime.Sub(srcTime).Seconds()
			if dur < 0 {
				dur = 0
			}

			transitions = append(transitions, Transition{
				CaseID:          caseID,
				Source:          src.Activity,
				Target:          tgt.Activity,
				SourceTimestamp: srcTime,
				TransitionTime: tgtTime,
				DurationSeconds: dur,
				SourceActor:     src.Actor,
				TargetActor:     tgt.Actor,
			})
		}
	}
	return transitions
}

// ---------------------------------------------------------------------------
// Edge computation
// ---------------------------------------------------------------------------

type EdgeStat struct {
	Source                string  `json:"source"`
	Target                string  `json:"target"`
	Frequency             int     `json:"frequency"`
	MeanDurationSeconds   float64 `json:"mean_duration_seconds"`
	MedianDurationSeconds float64 `json:"median_duration_seconds"`
	P90DurationSeconds    float64 `json:"p90_duration_seconds"`
}

func computeEdges(transitions []Transition) []EdgeStat {
	type edgeKey struct{ Source, Target string }
	groups := map[edgeKey][]float64{}
	for _, t := range transitions {
		k := edgeKey{t.Source, t.Target}
		groups[k] = append(groups[k], t.DurationSeconds)
	}

	edges := make([]EdgeStat, 0, len(groups))
	for k, durations := range groups {
		sort.Float64s(durations)
		n := len(durations)
		sum := 0.0
		for _, d := range durations {
			sum += d
		}
		edges = append(edges, EdgeStat{
			Source:                k.Source,
			Target:                k.Target,
			Frequency:             n,
			MeanDurationSeconds:   roundN(sum/float64(n), 2),
			MedianDurationSeconds: roundN(percentile(durations, 0.5), 2),
			P90DurationSeconds:    roundN(percentile(durations, 0.9), 2),
		})
	}
	sort.Slice(edges, func(i, j int) bool { return edges[i].Frequency > edges[j].Frequency })
	return edges
}

func computeBottlenecks(edges []EdgeStat) []EdgeStat {
	sorted := make([]EdgeStat, len(edges))
	copy(sorted, edges)
	sort.Slice(sorted, func(i, j int) bool {
		if sorted[i].MedianDurationSeconds != sorted[j].MedianDurationSeconds {
			return sorted[i].MedianDurationSeconds > sorted[j].MedianDurationSeconds
		}
		return sorted[i].Frequency > sorted[j].Frequency
	})
	if len(sorted) > 15 {
		sorted = sorted[:15]
	}
	return sorted
}

// ---------------------------------------------------------------------------
// Nodes
// ---------------------------------------------------------------------------

type NodeStat struct {
	ID         string `json:"id"`
	Label      string `json:"label"`
	Frequency  int    `json:"frequency"`
	StartCount int    `json:"start_count"`
	EndCount   int    `json:"end_count"`
}

func computeNodes(events []Event) []NodeStat {
	actCounts := map[string]int{}
	startCounts := map[string]int{}
	endCounts := map[string]int{}

	caseEvents := map[string][]Event{}
	for _, e := range events {
		actCounts[e.Activity]++
		caseEvents[e.CaseID] = append(caseEvents[e.CaseID], e)
	}
	for _, evts := range caseEvents {
		if len(evts) > 0 {
			startCounts[evts[0].Activity]++
			endCounts[evts[len(evts)-1].Activity]++
		}
	}

	nodes := make([]NodeStat, 0, len(actCounts))
	for act, count := range actCounts {
		nodes = append(nodes, NodeStat{
			ID:         act,
			Label:      act,
			Frequency:  count,
			StartCount: startCounts[act],
			EndCount:   endCounts[act],
		})
	}
	sort.Slice(nodes, func(i, j int) bool { return nodes[i].Frequency > nodes[j].Frequency })
	return nodes
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

type Summary struct {
	TotalCases              int      `json:"total_cases"`
	TotalEvents             int      `json:"total_events"`
	Activities              int      `json:"activities"`
	StartTime               *string  `json:"start_time"`
	EndTime                 *string  `json:"end_time"`
	MedianCaseDurationHours float64  `json:"median_case_duration_hours"`
	AvgCaseDurationHours    float64  `json:"avg_case_duration_hours"`
	MedianEventsPerCase     float64  `json:"median_events_per_case"`
	ReworkCaseRatio         float64  `json:"rework_case_ratio"`
}

func computeSummary(events []Event) Summary {
	if len(events) == 0 {
		return Summary{}
	}

	caseSet := map[string]bool{}
	actSet := map[string]bool{}
	for _, e := range events {
		caseSet[e.CaseID] = true
		actSet[e.Activity] = true
	}

	caseMetrics := computeCaseMetrics(events)

	// Rework: cases where an activity appears > 1 time
	caseActCounts := map[string]map[string]int{}
	for _, e := range events {
		if caseActCounts[e.CaseID] == nil {
			caseActCounts[e.CaseID] = map[string]int{}
		}
		caseActCounts[e.CaseID][e.Activity]++
	}
	reworkCases := 0
	for _, acts := range caseActCounts {
		for _, c := range acts {
			if c > 1 {
				reworkCases++
				break
			}
		}
	}

	durations := make([]float64, len(caseMetrics))
	eventCounts := make([]float64, len(caseMetrics))
	for i, cm := range caseMetrics {
		durations[i] = cm.DurationHours
		eventCounts[i] = float64(cm.EventCount)
	}
	sort.Float64s(durations)
	sort.Float64s(eventCounts)

	sumDur := 0.0
	for _, d := range durations {
		sumDur += d
	}

	var minTime, maxTime time.Time
	first := true
	for _, e := range events {
		st := e.Timestamp
		if e.StartTimestamp != nil {
			st = *e.StartTimestamp
		}
		et := e.Timestamp
		if e.EndTimestamp != nil {
			et = *e.EndTimestamp
		}
		if first || st.Before(minTime) {
			minTime = st
		}
		if first || et.After(maxTime) {
			maxTime = et
		}
		first = false
	}

	startStr := minTime.Format(time.RFC3339)
	endStr := maxTime.Format(time.RFC3339)

	totalCases := len(caseSet)
	return Summary{
		TotalCases:              totalCases,
		TotalEvents:             len(events),
		Activities:              len(actSet),
		StartTime:               &startStr,
		EndTime:                 &endStr,
		MedianCaseDurationHours: roundN(percentile(durations, 0.5), 2),
		AvgCaseDurationHours:    roundN(sumDur/float64(len(durations)), 2),
		MedianEventsPerCase:     roundN(percentile(eventCounts, 0.5), 2),
		ReworkCaseRatio:         roundN(float64(reworkCases)/float64(max(totalCases, 1)), 4),
	}
}

// ---------------------------------------------------------------------------
// Variants Payload
// ---------------------------------------------------------------------------

type VariantStat struct {
	Rank                int     `json:"rank"`
	Variant             string  `json:"variant"`
	Cases               int     `json:"cases"`
	Share               float64 `json:"share"`
	AvgDurationHours    float64 `json:"avg_duration_hours"`
	MedianDurationHours float64 `json:"median_duration_hours"`
}

func computeVariants(events []Event, caseMetrics []CaseMetric, topK int) []VariantStat {
	if len(events) == 0 {
		return nil
	}
	if topK < 1 {
		topK = 20
	}

	caseDuration := map[string]float64{}
	for _, cm := range caseMetrics {
		caseDuration[cm.CaseID] = cm.DurationHours
	}

	caseVariants := buildCaseVariants(events)
	variantCases := map[string][]string{} // variant -> caseIDs
	for _, cv := range caseVariants {
		variantCases[cv.Variant] = append(variantCases[cv.Variant], cv.CaseID)
	}

	type vc struct {
		Variant string
		Cases   []string
	}
	var sorted []vc
	for v, cases := range variantCases {
		sorted = append(sorted, vc{v, cases})
	}
	sort.Slice(sorted, func(i, j int) bool { return len(sorted[i].Cases) > len(sorted[j].Cases) })

	if len(sorted) > topK {
		sorted = sorted[:topK]
	}

	totalCases := len(computeCaseMetrics(events))
	result := make([]VariantStat, len(sorted))
	for i, v := range sorted {
		durations := make([]float64, 0, len(v.Cases))
		for _, cid := range v.Cases {
			durations = append(durations, caseDuration[cid])
		}
		sort.Float64s(durations)
		sum := 0.0
		for _, d := range durations {
			sum += d
		}
		result[i] = VariantStat{
			Rank:                i + 1,
			Variant:             v.Variant,
			Cases:               len(v.Cases),
			Share:               roundN(float64(len(v.Cases))/float64(max(totalCases, 1)), 4),
			AvgDurationHours:    roundN(sum/float64(max(len(durations), 1)), 2),
			MedianDurationHours: roundN(percentile(durations, 0.5), 2),
		}
	}
	return result
}

// ---------------------------------------------------------------------------
// Activity Stats
// ---------------------------------------------------------------------------

type ActivityStat struct {
	Activity     string  `json:"activity"`
	Frequency    int     `json:"frequency"`
	CaseCoverage float64 `json:"case_coverage"`
}

func computeActivityStats(events []Event) []ActivityStat {
	if len(events) == 0 {
		return nil
	}

	actCounts := map[string]int{}
	actCases := map[string]map[string]bool{}
	caseSet := map[string]bool{}

	for _, e := range events {
		actCounts[e.Activity]++
		caseSet[e.CaseID] = true
		if actCases[e.Activity] == nil {
			actCases[e.Activity] = map[string]bool{}
		}
		actCases[e.Activity][e.CaseID] = true
	}

	totalCases := len(caseSet)
	stats := make([]ActivityStat, 0, len(actCounts))
	for act, freq := range actCounts {
		stats = append(stats, ActivityStat{
			Activity:     act,
			Frequency:    freq,
			CaseCoverage: roundN(float64(len(actCases[act]))/float64(max(totalCases, 1)), 4),
		})
	}
	sort.Slice(stats, func(i, j int) bool { return stats[i].Frequency > stats[j].Frequency })
	return stats
}

// ---------------------------------------------------------------------------
// Handoff (Actor) Views
// ---------------------------------------------------------------------------

type HandoffView struct {
	Enabled      bool              `json:"enabled"`
	ActorColumn  string            `json:"actor_column"`
	ActorView    HandoffGraphView  `json:"actor_view"`
	ActivityView HandoffGraphView  `json:"activity_view"`
}

type HandoffGraphView struct {
	Nodes          []NodeStat  `json:"nodes"`
	Edges          []EdgeStat  `json:"edges"`
	TotalHandoffs  int         `json:"total_handoffs"`
}

func computeHandoff(events []Event, transitions []Transition, minEdgeFreq int) HandoffView {
	hasActor := false
	for _, e := range events {
		if e.Actor != "" {
			hasActor = true
			break
		}
	}
	emptyView := HandoffGraphView{Nodes: []NodeStat{}, Edges: []EdgeStat{}, TotalHandoffs: 0}
	if !hasActor {
		return HandoffView{Enabled: false, ActorView: emptyView, ActivityView: emptyView}
	}

	// Filter to handoff transitions (actor changes)
	var handoffs []Transition
	for _, t := range transitions {
		sa := cleanActorValue(t.SourceActor)
		ta := cleanActorValue(t.TargetActor)
		if sa != "" && ta != "" && sa != ta {
			handoffs = append(handoffs, t)
		}
	}

	if len(handoffs) == 0 {
		return HandoffView{Enabled: true, ActorView: emptyView, ActivityView: emptyView}
	}

	// Actor view: group by actor pair
	type actorPair struct{ Source, Target string }
	actorGroups := map[actorPair][]float64{}
	actorCounts := map[string]int{}
	for _, e := range events {
		if e.Actor != "" {
			actorCounts[e.Actor]++
		}
	}
	for _, t := range handoffs {
		sa := cleanActorValue(t.SourceActor)
		ta := cleanActorValue(t.TargetActor)
		k := actorPair{sa, ta}
		actorGroups[k] = append(actorGroups[k], t.DurationSeconds)
	}

	actorNodes := make([]NodeStat, 0)
	for actor, count := range actorCounts {
		actorNodes = append(actorNodes, NodeStat{ID: actor, Label: actor, Frequency: count})
	}

	actorEdges := make([]EdgeStat, 0, len(actorGroups))
	for k, durs := range actorGroups {
		if len(durs) < minEdgeFreq {
			continue
		}
		sort.Float64s(durs)
		sum := 0.0
		for _, d := range durs {
			sum += d
		}
		actorEdges = append(actorEdges, EdgeStat{
			Source:                k.Source,
			Target:                k.Target,
			Frequency:             len(durs),
			MeanDurationSeconds:   roundN(sum/float64(len(durs)), 2),
			MedianDurationSeconds: roundN(percentile(durs, 0.5), 2),
		})
	}
	sort.Slice(actorEdges, func(i, j int) bool { return actorEdges[i].Frequency > actorEdges[j].Frequency })

	// Activity view: group handoffs by source->target activity
	type actPair struct{ Source, Target string }
	actGroups := map[actPair][]float64{}
	for _, t := range handoffs {
		k := actPair{t.Source, t.Target}
		actGroups[k] = append(actGroups[k], t.DurationSeconds)
	}
	actEdges := make([]EdgeStat, 0, len(actGroups))
	for k, durs := range actGroups {
		if len(durs) < minEdgeFreq {
			continue
		}
		sort.Float64s(durs)
		sum := 0.0
		for _, d := range durs {
			sum += d
		}
		actEdges = append(actEdges, EdgeStat{
			Source:                k.Source,
			Target:                k.Target,
			Frequency:             len(durs),
			MeanDurationSeconds:   roundN(sum/float64(len(durs)), 2),
			MedianDurationSeconds: roundN(percentile(durs, 0.5), 2),
		})
	}
	sort.Slice(actEdges, func(i, j int) bool { return actEdges[i].Frequency > actEdges[j].Frequency })

	actNodeSet := map[string]int{}
	for _, e := range actEdges {
		actNodeSet[e.Source] += e.Frequency
		actNodeSet[e.Target] += e.Frequency
	}
	actNodes := make([]NodeStat, 0, len(actNodeSet))
	for act, freq := range actNodeSet {
		actNodes = append(actNodes, NodeStat{ID: act, Label: act, Frequency: freq})
	}

	return HandoffView{
		Enabled:     true,
		ActorColumn: "actor",
		ActorView: HandoffGraphView{
			Nodes:         actorNodes,
			Edges:         actorEdges,
			TotalHandoffs: len(handoffs),
		},
		ActivityView: HandoffGraphView{
			Nodes:         actNodes,
			Edges:         actEdges,
			TotalHandoffs: len(handoffs),
		},
	}
}

// ---------------------------------------------------------------------------
// Swimlane View
// ---------------------------------------------------------------------------

type SwimlaneView struct {
	Available   bool           `json:"available"`
	ActorColumn string         `json:"actor_column"`
	Lanes       []string       `json:"lanes"`
	Nodes       []SwimlaneNode `json:"nodes"`
	Edges       []SwimlaneEdge `json:"edges"`
}

type SwimlaneNode struct {
	ID        string `json:"id"`
	Label     string `json:"label"`
	Activity  string `json:"activity"`
	Actor     string `json:"actor"`
	Lane      string `json:"lane"`
	LaneIndex int    `json:"lane_index"`
	Frequency int    `json:"frequency"`
}

type SwimlaneEdge struct {
	Source                string  `json:"source"`
	Target                string  `json:"target"`
	SourceActor           string  `json:"source_actor"`
	TargetActor           string  `json:"target_actor"`
	Frequency             int     `json:"frequency"`
	MedianDurationSeconds float64 `json:"median_duration_seconds"`
}

func computeSwimlane(events []Event, transitions []Transition, minEdgeFreq int) SwimlaneView {
	hasActor := false
	for _, e := range events {
		if e.Actor != "" {
			hasActor = true
			break
		}
	}
	if !hasActor {
		return SwimlaneView{Available: false, Lanes: []string{}, Nodes: []SwimlaneNode{}, Edges: []SwimlaneEdge{}}
	}

	// Count top actors
	actorCounts := map[string]int{}
	for _, e := range events {
		a := cleanActorValue(e.Actor)
		if a != "" {
			actorCounts[a]++
		}
	}
	type ac struct {
		Actor string
		Count int
	}
	var sortedActors []ac
	for a, c := range actorCounts {
		sortedActors = append(sortedActors, ac{a, c})
	}
	sort.Slice(sortedActors, func(i, j int) bool { return sortedActors[i].Count > sortedActors[j].Count })
	if len(sortedActors) > 10 {
		sortedActors = sortedActors[:10]
	}
	topActors := make([]string, len(sortedActors))
	topActorSet := map[string]bool{}
	for i, a := range sortedActors {
		topActors[i] = a.Actor
		topActorSet[a.Actor] = true
	}

	// Build nodes: actor || activity
	type nodeKey struct{ Actor, Activity string }
	nodeFreqs := map[nodeKey]int{}
	for _, e := range events {
		a := cleanActorValue(e.Actor)
		if topActorSet[a] {
			nodeFreqs[nodeKey{a, e.Activity}]++
		}
	}

	// Take top 8 per actor
	actorNodes := map[string][]nodeKey{}
	for nk := range nodeFreqs {
		actorNodes[nk.Actor] = append(actorNodes[nk.Actor], nk)
	}
	for actor := range actorNodes {
		sort.Slice(actorNodes[actor], func(i, j int) bool {
			return nodeFreqs[actorNodes[actor][i]] > nodeFreqs[actorNodes[actor][j]]
		})
		if len(actorNodes[actor]) > 8 {
			actorNodes[actor] = actorNodes[actor][:8]
		}
	}

	nodeIDSet := map[string]bool{}
	var nodes []SwimlaneNode
	lanePos := map[string]int{}
	for i, a := range topActors {
		lanePos[a] = i
	}
	for actor, nks := range actorNodes {
		for _, nk := range nks {
			id := nk.Actor + " || " + nk.Activity
			nodeIDSet[id] = true
			nodes = append(nodes, SwimlaneNode{
				ID:        id,
				Label:     nk.Activity,
				Activity:  nk.Activity,
				Actor:     actor,
				Lane:      actor,
				LaneIndex: lanePos[actor],
				Frequency: nodeFreqs[nk],
			})
		}
	}

	// Build edges from transitions
	type edgeKey struct{ Source, Target string }
	edgeGroups := map[edgeKey]struct {
		SourceActor string
		TargetActor string
		Durations   []float64
	}{}
	for _, t := range transitions {
		sa := cleanActorValue(t.SourceActor)
		ta := cleanActorValue(t.TargetActor)
		if !topActorSet[sa] || !topActorSet[ta] {
			continue
		}
		srcID := sa + " || " + t.Source
		tgtID := ta + " || " + t.Target
		if !nodeIDSet[srcID] || !nodeIDSet[tgtID] {
			continue
		}
		k := edgeKey{srcID, tgtID}
		g := edgeGroups[k]
		g.SourceActor = sa
		g.TargetActor = ta
		g.Durations = append(g.Durations, t.DurationSeconds)
		edgeGroups[k] = g
	}

	var edges []SwimlaneEdge
	for k, g := range edgeGroups {
		if len(g.Durations) < minEdgeFreq {
			continue
		}
		sort.Float64s(g.Durations)
		edges = append(edges, SwimlaneEdge{
			Source:                k.Source,
			Target:                k.Target,
			SourceActor:           g.SourceActor,
			TargetActor:           g.TargetActor,
			Frequency:             len(g.Durations),
			MedianDurationSeconds: roundN(percentile(g.Durations, 0.5), 2),
		})
	}
	sort.Slice(edges, func(i, j int) bool { return edges[i].Frequency > edges[j].Frequency })
	if len(edges) > 220 {
		edges = edges[:220]
	}

	return SwimlaneView{
		Available:   true,
		ActorColumn: "actor",
		Lanes:       topActors,
		Nodes:       nodes,
		Edges:       edges,
	}
}

// ---------------------------------------------------------------------------
// Sankey View
// ---------------------------------------------------------------------------

type SankeyView struct {
	Available bool         `json:"available"`
	Nodes     []SankeyNode `json:"nodes"`
	Links     []SankeyLink `json:"links"`
}

type SankeyNode struct {
	ID        string `json:"id"`
	Label     string `json:"label"`
	Stage     int    `json:"stage"`
	Frequency int    `json:"frequency"`
}

type SankeyLink struct {
	Source                string  `json:"source"`
	Target                string  `json:"target"`
	Value                 int     `json:"value"`
	MedianDurationSeconds float64 `json:"median_duration_seconds"`
}

func computeSankey(events []Event, transitions []Transition, minEdgeFreq int) SankeyView {
	if len(transitions) == 0 {
		return SankeyView{Available: false, Nodes: []SankeyNode{}, Links: []SankeyLink{}}
	}

	// Edge aggregation
	type edgeKey struct{ Source, Target string }
	edgeGroups := map[edgeKey][]float64{}
	for _, t := range transitions {
		k := edgeKey{t.Source, t.Target}
		edgeGroups[k] = append(edgeGroups[k], t.DurationSeconds)
	}

	var links []SankeyLink
	nodeSet := map[string]bool{}
	for k, durs := range edgeGroups {
		if len(durs) < minEdgeFreq {
			continue
		}
		sort.Float64s(durs)
		links = append(links, SankeyLink{
			Source:                k.Source,
			Target:                k.Target,
			Value:                 len(durs),
			MedianDurationSeconds: roundN(percentile(durs, 0.5), 2),
		})
		nodeSet[k.Source] = true
		nodeSet[k.Target] = true
	}
	sort.Slice(links, func(i, j int) bool { return links[i].Value > links[j].Value })
	if len(links) > 260 {
		links = links[:260]
	}

	if len(links) == 0 {
		return SankeyView{Available: false, Nodes: []SankeyNode{}, Links: []SankeyLink{}}
	}

	// Compute stage position based on median position
	actCounts := map[string]int{}
	for _, e := range events {
		actCounts[e.Activity]++
	}

	// Simple stage: based on first occurrence order
	casePos := map[string][]int{}
	posCounter := map[string]int{}
	for _, e := range events {
		pos := posCounter[e.CaseID]
		casePos[e.Activity] = append(casePos[e.Activity], pos)
		posCounter[e.CaseID]++
	}
	medianPos := map[string]float64{}
	for act, positions := range casePos {
		floats := make([]float64, len(positions))
		for i, p := range positions {
			floats[i] = float64(p)
		}
		sort.Float64s(floats)
		medianPos[act] = percentile(floats, 0.5)
	}
	type actPos struct {
		Act string
		Pos float64
	}
	var orderedActs []actPos
	for act := range nodeSet {
		orderedActs = append(orderedActs, actPos{act, medianPos[act]})
	}
	sort.Slice(orderedActs, func(i, j int) bool { return orderedActs[i].Pos < orderedActs[j].Pos })

	scaleDenom := max(len(orderedActs)-1, 1)
	stageMap := map[string]int{}
	for i, ap := range orderedActs {
		stageMap[ap.Act] = int(math.Round(float64(i) / float64(scaleDenom) * float64(min(8, scaleDenom))))
	}

	var nodes []SankeyNode
	for _, ap := range orderedActs {
		nodes = append(nodes, SankeyNode{
			ID:        ap.Act,
			Label:     ap.Act,
			Stage:     stageMap[ap.Act],
			Frequency: actCounts[ap.Act],
		})
	}

	return SankeyView{Available: true, Nodes: nodes, Links: links}
}

// ---------------------------------------------------------------------------
// Rework View
// ---------------------------------------------------------------------------

type ReworkView struct {
	Activities []ReworkActivity `json:"activities"`
	SelfLoops  []SelfLoop      `json:"self_loops"`
}

type ReworkActivity struct {
	Activity        string  `json:"activity"`
	CasesWithRework int     `json:"cases_with_rework"`
	ReworkEvents    int     `json:"rework_events"`
	MaxRepetitions  int     `json:"max_repetitions"`
	ReworkCaseRatio float64 `json:"rework_case_ratio"`
}

type SelfLoop struct {
	Activity  string `json:"activity"`
	Frequency int    `json:"frequency"`
}

func computeRework(events []Event, transitions []Transition) ReworkView {
	if len(events) == 0 {
		return ReworkView{Activities: []ReworkActivity{}, SelfLoops: []SelfLoop{}}
	}

	// Count activity occurrences per case
	caseActCounts := map[string]map[string]int{}
	caseSet := map[string]bool{}
	for _, e := range events {
		caseSet[e.CaseID] = true
		if caseActCounts[e.CaseID] == nil {
			caseActCounts[e.CaseID] = map[string]int{}
		}
		caseActCounts[e.CaseID][e.Activity]++
	}
	totalCases := len(caseSet)

	// Aggregate rework
	type reworkAgg struct {
		CasesWithRework int
		ReworkEvents    int
		MaxRep          int
	}
	actRework := map[string]*reworkAgg{}
	for _, acts := range caseActCounts {
		for act, count := range acts {
			if count > 1 {
				if actRework[act] == nil {
					actRework[act] = &reworkAgg{}
				}
				actRework[act].CasesWithRework++
				actRework[act].ReworkEvents += count - 1
				if count > actRework[act].MaxRep {
					actRework[act].MaxRep = count
				}
			}
		}
	}

	activities := make([]ReworkActivity, 0, len(actRework))
	for act, agg := range actRework {
		activities = append(activities, ReworkActivity{
			Activity:        act,
			CasesWithRework: agg.CasesWithRework,
			ReworkEvents:    agg.ReworkEvents,
			MaxRepetitions:  agg.MaxRep,
			ReworkCaseRatio: roundN(float64(agg.CasesWithRework)/float64(max(totalCases, 1)), 4),
		})
	}
	sort.Slice(activities, func(i, j int) bool { return activities[i].ReworkEvents > activities[j].ReworkEvents })

	// Self loops from transitions
	loopCounts := map[string]int{}
	for _, t := range transitions {
		if t.Source == t.Target {
			loopCounts[t.Source]++
		}
	}
	selfLoops := make([]SelfLoop, 0, len(loopCounts))
	for act, freq := range loopCounts {
		selfLoops = append(selfLoops, SelfLoop{Activity: act, Frequency: freq})
	}
	sort.Slice(selfLoops, func(i, j int) bool { return selfLoops[i].Frequency > selfLoops[j].Frequency })

	return ReworkView{Activities: activities, SelfLoops: selfLoops}
}

// ---------------------------------------------------------------------------
// Dashboard Payload
// ---------------------------------------------------------------------------

type DashboardPayload struct {
	Summary         Summary          `json:"summary"`
	Nodes           []NodeStat       `json:"nodes"`
	Edges           []EdgeStat       `json:"edges"`
	Variants        []VariantStat    `json:"variants"`
	ActivityStats   []ActivityStat   `json:"activity_stats"`
	Bottlenecks     []EdgeStat       `json:"bottlenecks"`
	ActorColumn     string           `json:"actor_column"`
	Handoff         HandoffView      `json:"handoff"`
	Swimlane        SwimlaneView     `json:"swimlane"`
	Sankey          SankeyView       `json:"sankey"`
	Rework          ReworkView       `json:"rework"`
	Recommendations []Recommendation `json:"recommendations"`
}

type Recommendation struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Why   string `json:"why"`
}

func viewRecommendations() []Recommendation {
	return []Recommendation{
		{ID: "queue_age_heatmap", Title: "Queue Age Heatmap", Why: "Highlights queues with long waiting times over time slices."},
		{ID: "rework_treemap", Title: "Rework Treemap", Why: "Shows which activities consume the most repeated work volume."},
		{ID: "variant_duration_boxplot", Title: "Variant Duration Boxplot", Why: "Compares spread of cycle times across dominant process variants."},
	}
}

func ComputeDashboard(events []Event, filters FilterSpec) DashboardPayload {
	t0 := time.Now()
	filtered := ApplyFilters(events, filters)
	log.Printf("Filtered %d -> %d events (%.1f ms)", len(events), len(filtered), float64(time.Since(t0).Microseconds())/1000)

	if len(filtered) == 0 {
		return DashboardPayload{
			Summary:         Summary{},
			Nodes:           []NodeStat{},
			Edges:           []EdgeStat{},
			Variants:        []VariantStat{},
			ActivityStats:   []ActivityStat{},
			Bottlenecks:     []EdgeStat{},
			Handoff:         HandoffView{Enabled: false, ActorView: HandoffGraphView{Nodes: []NodeStat{}, Edges: []EdgeStat{}}, ActivityView: HandoffGraphView{Nodes: []NodeStat{}, Edges: []EdgeStat{}}},
			Swimlane:        SwimlaneView{Available: false, Lanes: []string{}, Nodes: []SwimlaneNode{}, Edges: []SwimlaneEdge{}},
			Sankey:          SankeyView{Available: false, Nodes: []SankeyNode{}, Links: []SankeyLink{}},
			Rework:          ReworkView{Activities: []ReworkActivity{}, SelfLoops: []SelfLoop{}},
			Recommendations: viewRecommendations(),
		}
	}

	transitions := computeTransitions(filtered)
	log.Printf("Computed %d transitions", len(transitions))

	edges := computeEdges(transitions)
	minEdgeFreq := filters.MinEdgeFrequency
	if minEdgeFreq < 1 {
		minEdgeFreq = 1
	}
	filteredEdges := make([]EdgeStat, 0)
	for _, e := range edges {
		if e.Frequency >= minEdgeFreq {
			filteredEdges = append(filteredEdges, e)
		}
	}

	caseMetrics := computeCaseMetrics(filtered)
	variantTopK := filters.VariantTopK
	if variantTopK < 1 {
		variantTopK = 20
	}

	// Detect actor column
	actorCol := ""
	for _, e := range filtered {
		if e.Actor != "" {
			actorCol = "actor"
			break
		}
	}

	return DashboardPayload{
		Summary:         computeSummary(filtered),
		Nodes:           computeNodes(filtered),
		Edges:           filteredEdges,
		Variants:        computeVariants(filtered, caseMetrics, variantTopK),
		ActivityStats:   computeActivityStats(filtered),
		Bottlenecks:     computeBottlenecks(filteredEdges),
		ActorColumn:     actorCol,
		Handoff:         computeHandoff(filtered, transitions, minEdgeFreq),
		Swimlane:        computeSwimlane(filtered, transitions, minEdgeFreq),
		Sankey:          computeSankey(filtered, transitions, minEdgeFreq),
		Rework:          computeRework(filtered, transitions),
		Recommendations: viewRecommendations(),
	}
}

// ---------------------------------------------------------------------------
// Animation Payload
// ---------------------------------------------------------------------------

type AnimationFrame struct {
	Index            int              `json:"index"`
	StartTime        *string          `json:"start_time"`
	EndTime          *string          `json:"end_time"`
	TotalTransitions int              `json:"total_transitions"`
	Edges            []AnimationEdge  `json:"edges"`
}

type AnimationEdge struct {
	Source string `json:"source"`
	Target string `json:"target"`
	Count  int    `json:"count"`
}

type AnimationPayload struct {
	StartTime                    *string          `json:"start_time"`
	EndTime                      *string          `json:"end_time"`
	FrameCount                   int              `json:"frame_count"`
	FrameIntervalSeconds         float64          `json:"frame_interval_seconds"`
	MaxEdgeCountPerFrame         int              `json:"max_edge_count_per_frame"`
	MaxTotalTransitionsPerFrame  int              `json:"max_total_transitions_per_frame"`
	Frames                       []AnimationFrame `json:"frames"`
}

func ComputeAnimation(events []Event, filters FilterSpec, frameCount int) AnimationPayload {
	filtered := ApplyFilters(events, filters)
	empty := AnimationPayload{Frames: []AnimationFrame{}}
	if len(filtered) == 0 {
		return empty
	}

	transitions := computeTransitions(filtered)
	if len(transitions) == 0 {
		return empty
	}

	// Apply min edge frequency
	minEdgeFreq := filters.MinEdgeFrequency
	if minEdgeFreq < 1 {
		minEdgeFreq = 1
	}
	type edgeKey struct{ Source, Target string }
	edgeCounts := map[edgeKey]int{}
	for _, t := range transitions {
		edgeCounts[edgeKey{t.Source, t.Target}]++
	}
	keepEdges := map[edgeKey]bool{}
	for k, c := range edgeCounts {
		if c >= minEdgeFreq {
			keepEdges[k] = true
		}
	}
	var filteredTrans []Transition
	for _, t := range transitions {
		if keepEdges[edgeKey{t.Source, t.Target}] {
			filteredTrans = append(filteredTrans, t)
		}
	}
	if len(filteredTrans) == 0 {
		return empty
	}

	sort.Slice(filteredTrans, func(i, j int) bool {
		return filteredTrans[i].TransitionTime.Before(filteredTrans[j].TransitionTime)
	})

	startTime := filteredTrans[0].TransitionTime
	endTime := filteredTrans[len(filteredTrans)-1].TransitionTime

	if frameCount < 1 {
		frameCount = 80
	}
	if frameCount > 240 {
		frameCount = 240
	}

	startStr := startTime.Format(time.RFC3339)
	endStr := endTime.Format(time.RFC3339)

	if startTime.Equal(endTime) {
		// Single frame
		grouped := map[edgeKey]int{}
		for _, t := range filteredTrans {
			grouped[edgeKey{t.Source, t.Target}]++
		}
		var edges []AnimationEdge
		maxCount := 0
		for k, c := range grouped {
			edges = append(edges, AnimationEdge{Source: k.Source, Target: k.Target, Count: c})
			if c > maxCount {
				maxCount = c
			}
		}
		return AnimationPayload{
			StartTime:                   &startStr,
			EndTime:                     &endStr,
			FrameCount:                  1,
			FrameIntervalSeconds:        0,
			MaxEdgeCountPerFrame:        maxCount,
			MaxTotalTransitionsPerFrame: len(filteredTrans),
			Frames: []AnimationFrame{{
				Index:            0,
				StartTime:        &startStr,
				EndTime:          &endStr,
				TotalTransitions: len(filteredTrans),
				Edges:            edges,
			}},
		}
	}

	totalDur := endTime.Sub(startTime)
	frameDur := totalDur / time.Duration(frameCount)

	frames := make([]AnimationFrame, frameCount)
	maxEdgeCount := 0
	maxTotalTrans := 0

	tIdx := 0
	for fi := 0; fi < frameCount; fi++ {
		fStart := startTime.Add(frameDur * time.Duration(fi))
		fEnd := startTime.Add(frameDur * time.Duration(fi+1))
		if fi == frameCount-1 {
			fEnd = endTime.Add(time.Second) // include last
		}

		grouped := map[edgeKey]int{}
		totalTrans := 0
		for tIdx < len(filteredTrans) && filteredTrans[tIdx].TransitionTime.Before(fEnd) {
			if !filteredTrans[tIdx].TransitionTime.Before(fStart) {
				k := edgeKey{filteredTrans[tIdx].Source, filteredTrans[tIdx].Target}
				grouped[k]++
				totalTrans++
			}
			tIdx++
		}
		// Reset tIdx for next frame overlap... actually transitions are sorted, use a scan approach
		// This simple approach works since frames are sequential and non-overlapping

		var edges []AnimationEdge
		frameMax := 0
		for k, c := range grouped {
			edges = append(edges, AnimationEdge{Source: k.Source, Target: k.Target, Count: c})
			if c > frameMax {
				frameMax = c
			}
		}
		sort.Slice(edges, func(i, j int) bool { return edges[i].Count > edges[j].Count })
		if len(edges) > 180 {
			edges = edges[:180]
		}

		fStartStr := fStart.Format(time.RFC3339)
		fEndStr := fEnd.Format(time.RFC3339)
		frames[fi] = AnimationFrame{
			Index:            fi,
			StartTime:        &fStartStr,
			EndTime:          &fEndStr,
			TotalTransitions: totalTrans,
			Edges:            edges,
		}

		if frameMax > maxEdgeCount {
			maxEdgeCount = frameMax
		}
		if totalTrans > maxTotalTrans {
			maxTotalTrans = totalTrans
		}
	}

	intervalSec := totalDur.Seconds() / float64(frameCount)
	return AnimationPayload{
		StartTime:                   &startStr,
		EndTime:                     &endStr,
		FrameCount:                  frameCount,
		FrameIntervalSeconds:        roundN(intervalSec, 2),
		MaxEdgeCountPerFrame:        maxEdgeCount,
		MaxTotalTransitionsPerFrame: maxTotalTrans,
		Frames:                      frames,
	}
}

// ---------------------------------------------------------------------------
// Available Activities
// ---------------------------------------------------------------------------

func AvailableActivities(events []Event) []string {
	actSet := map[string]bool{}
	for _, e := range events {
		actSet[e.Activity] = true
	}
	result := make([]string, 0, len(actSet))
	for a := range actSet {
		result = append(result, a)
	}
	sort.Strings(result)
	return result
}

// ---------------------------------------------------------------------------
// Attribute Filter Options
// ---------------------------------------------------------------------------

func AttributeFilterOptions(events []Event, columns []string) map[string][]string {
	result := map[string][]string{}
	for _, col := range columns {
		valueCounts := map[string]int{}
		for _, e := range events {
			v := strings.TrimSpace(e.Extra[col])
			if v != "" && v != "nan" && v != "None" && v != "NaT" {
				valueCounts[v]++
			}
		}
		type vc struct {
			Value string
			Count int
		}
		var sorted []vc
		for v, c := range valueCounts {
			sorted = append(sorted, vc{v, c})
		}
		sort.Slice(sorted, func(i, j int) bool { return sorted[i].Count > sorted[j].Count })
		if len(sorted) > 200 {
			sorted = sorted[:200]
		}
		values := make([]string, len(sorted))
		for i, v := range sorted {
			values[i] = v.Value
		}
		result[col] = values
	}
	return result
}

// ---------------------------------------------------------------------------
// Informational Column Profile
// ---------------------------------------------------------------------------

type InformationalProfile struct {
	Column       string               `json:"column"`
	NonNull      int                  `json:"non_null"`
	UniqueValues int                  `json:"unique_values"`
	TopValues    []InformationalValue `json:"top_values"`
}

type InformationalValue struct {
	Value string `json:"value"`
	Count int    `json:"count"`
}

func InformationalColumnProfile(events []Event, columns []string) []InformationalProfile {
	var profiles []InformationalProfile
	for _, col := range columns {
		valueCounts := map[string]int{}
		nonNull := 0
		for _, e := range events {
			v := strings.TrimSpace(e.Extra[col])
			if v != "" && v != "nan" && v != "None" && v != "NaT" {
				valueCounts[v]++
				nonNull++
			}
		}
		type vc struct {
			Value string
			Count int
		}
		var sorted []vc
		for v, c := range valueCounts {
			sorted = append(sorted, vc{v, c})
		}
		sort.Slice(sorted, func(i, j int) bool { return sorted[i].Count > sorted[j].Count })
		if len(sorted) > 6 {
			sorted = sorted[:6]
		}
		topValues := make([]InformationalValue, len(sorted))
		for i, v := range sorted {
			topValues[i] = InformationalValue{Value: v.Value, Count: v.Count}
		}
		profiles = append(profiles, InformationalProfile{
			Column:       col,
			NonNull:      nonNull,
			UniqueValues: len(valueCounts),
			TopValues:    topValues,
		})
	}
	return profiles
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func toStringSet(slice []string) map[string]bool {
	if len(slice) == 0 {
		return nil
	}
	m := map[string]bool{}
	for _, s := range slice {
		m[s] = true
	}
	return m
}

func percentile(sorted []float64, p float64) float64 {
	if len(sorted) == 0 {
		return 0
	}
	if len(sorted) == 1 {
		return sorted[0]
	}
	idx := p * float64(len(sorted)-1)
	lower := int(math.Floor(idx))
	upper := int(math.Ceil(idx))
	if lower == upper || upper >= len(sorted) {
		return sorted[lower]
	}
	frac := idx - float64(lower)
	return sorted[lower]*(1-frac) + sorted[upper]*frac
}

func roundN(v float64, n int) float64 {
	pow := math.Pow(10, float64(n))
	return math.Round(v*pow) / pow
}

func formatSecondsHuman(seconds float64) string {
	if seconds < 60 {
		return fmt.Sprintf("%.0fs", seconds)
	}
	minutes := seconds / 60
	if minutes < 60 {
		return fmt.Sprintf("%.1fm", minutes)
	}
	hours := minutes / 60
	if hours < 24 {
		return fmt.Sprintf("%.1fh", hours)
	}
	days := hours / 24
	return fmt.Sprintf("%.1fd", days)
}

var safeBasenameRE = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func safeExportBasename(filename string) string {
	// Remove extension
	stem := filename
	if idx := strings.LastIndex(filename, "."); idx > 0 {
		stem = filename[:idx]
	}
	safe := safeBasenameRE.ReplaceAllString(stem, "_")
	safe = strings.Trim(safe, "._")
	if safe == "" {
		return "event_log"
	}
	return safe
}
