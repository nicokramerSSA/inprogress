package main

import (
	"encoding/json"
	"fmt"
	"html"
	"math"
	"strings"
)

// ---------------------------------------------------------------------------
// HTML Report Builder (matches Python _build_html_report)
// ---------------------------------------------------------------------------

func BuildHTMLReport(
	filename, logID, exportedAt string,
	filters DashboardFilterRequest,
	dashboard DashboardPayload,
	animation AnimationPayload,
	mermaidExports map[string]string,
) string {
	summary := dashboard.Summary
	nodes := dashboard.Nodes
	edges := dashboard.Edges
	variants := dashboard.Variants
	bottlenecks := dashboard.Bottlenecks
	activityStats := dashboard.ActivityStats
	handoff := dashboard.Handoff
	swimlane := dashboard.Swimlane
	sankey := dashboard.Sankey
	rework := dashboard.Rework
	recommendations := dashboard.Recommendations

	// Summary cards
	startTime := "-"
	if summary.StartTime != nil {
		startTime = *summary.StartTime
	}
	endTime := "-"
	if summary.EndTime != nil {
		endTime = *summary.EndTime
	}
	cards := []struct{ Label, Value string }{
		{"Cases", fmtInt(summary.TotalCases)},
		{"Events", fmtInt(summary.TotalEvents)},
		{"Activities", fmtInt(summary.Activities)},
		{"Median Case Duration (h)", fmtDec(summary.MedianCaseDurationHours)},
		{"Average Case Duration (h)", fmtDec(summary.AvgCaseDurationHours)},
		{"Median Events / Case", fmtDec(summary.MedianEventsPerCase)},
		{"Rework Case Ratio", fmtPct(summary.ReworkCaseRatio)},
		{"Start Time", html.EscapeString(startTime)},
		{"End Time", html.EscapeString(endTime)},
	}
	var cardsHTML strings.Builder
	for _, c := range cards {
		cardsHTML.WriteString(fmt.Sprintf(
			`<article class="metric"><div class="metric-label">%s</div><div class="metric-value">%s</div></article>`,
			html.EscapeString(c.Label), c.Value,
		))
	}

	// Tables
	edgeRows := make([][]string, 0, len(edges))
	for _, e := range edges {
		if len(edgeRows) >= 160 {
			break
		}
		edgeRows = append(edgeRows, []string{
			html.EscapeString(e.Source + " -> " + e.Target),
			fmtInt(e.Frequency),
			formatSecondsHuman(e.MedianDurationSeconds),
			formatSecondsHuman(e.P90DurationSeconds),
		})
	}
	topEdgesTable := htmlTable([]string{"Path", "Frequency", "Median Wait", "p90 Wait"}, edgeRows)

	variantRows := make([][]string, len(variants))
	for i, v := range variants {
		variantRows[i] = []string{
			fmtInt(v.Rank), html.EscapeString(v.Variant), fmtInt(v.Cases),
			fmtPct(v.Share), fmtDec(v.MedianDurationHours),
		}
	}
	variantsTable := htmlTable([]string{"Rank", "Variant", "Cases", "Share", "Median Duration (h)"}, variantRows)

	bottleneckRows := make([][]string, len(bottlenecks))
	for i, b := range bottlenecks {
		bottleneckRows[i] = []string{
			html.EscapeString(b.Source + " -> " + b.Target),
			formatSecondsHuman(b.MedianDurationSeconds),
			formatSecondsHuman(b.P90DurationSeconds),
			fmtInt(b.Frequency),
		}
	}
	bottlenecksTable := htmlTable([]string{"Path", "Median Wait", "p90 Wait", "Frequency"}, bottleneckRows)

	actRows := make([][]string, len(activityStats))
	for i, s := range activityStats {
		actRows[i] = []string{html.EscapeString(s.Activity), fmtInt(s.Frequency), fmtPct(s.CaseCoverage)}
	}
	actTable := htmlTable([]string{"Activity", "Frequency", "Case Coverage"}, actRows)

	// Handoff tables
	handoffActorRows := make([][]string, len(handoff.ActorView.Edges))
	for i, e := range handoff.ActorView.Edges {
		handoffActorRows[i] = []string{
			html.EscapeString(e.Source), html.EscapeString(e.Target),
			fmtInt(e.Frequency), formatSecondsHuman(e.MedianDurationSeconds),
		}
	}
	handoffActorTable := htmlTable([]string{"From Actor", "To Actor", "Frequency", "Median Wait"}, handoffActorRows)

	handoffActEdgeRows := make([][]string, len(handoff.ActivityView.Edges))
	for i, e := range handoff.ActivityView.Edges {
		handoffActEdgeRows[i] = []string{
			html.EscapeString(e.Source), html.EscapeString(e.Target),
			fmtInt(e.Frequency), formatSecondsHuman(e.MedianDurationSeconds),
		}
	}
	handoffActTable := htmlTable([]string{"From Activity", "To Activity", "Frequency", "Median Wait"}, handoffActEdgeRows)

	swimRows := make([][]string, len(swimlane.Nodes))
	for i, n := range swimlane.Nodes {
		swimRows[i] = []string{html.EscapeString(n.Actor), html.EscapeString(n.Activity), fmtInt(n.Frequency)}
	}
	swimTable := htmlTable([]string{"Actor Lane", "Activity", "Frequency"}, swimRows)

	sankeyRows := make([][]string, len(sankey.Links))
	for i, l := range sankey.Links {
		sankeyRows[i] = []string{
			html.EscapeString(l.Source), html.EscapeString(l.Target),
			fmtInt(l.Value), formatSecondsHuman(l.MedianDurationSeconds),
		}
	}
	sankeyTable := htmlTable([]string{"Source", "Target", "Flow", "Median Wait"}, sankeyRows)

	reworkRows := make([][]string, len(rework.Activities))
	for i, a := range rework.Activities {
		reworkRows[i] = []string{
			html.EscapeString(a.Activity), fmtInt(a.CasesWithRework),
			fmtInt(a.ReworkEvents), fmtPct(a.ReworkCaseRatio),
		}
	}
	reworkTable := htmlTable([]string{"Activity", "Cases With Rework", "Rework Events", "Rework Case Ratio"}, reworkRows)

	// Conformance (not available in Go version)
	conformanceHTML := `<p class="empty">Conformance checking requires pm4py (Python version).</p>`

	// Animation summary
	animStartTime := "-"
	if animation.StartTime != nil {
		animStartTime = *animation.StartTime
	}
	animEndTime := "-"
	if animation.EndTime != nil {
		animEndTime = *animation.EndTime
	}
	animHTML := fmt.Sprintf(`<div class="conformance"><div><strong>Frames:</strong> %s</div><div><strong>Frame interval:</strong> %s</div><div><strong>Max transitions / frame:</strong> %s</div><div><strong>Animation range:</strong> %s to %s</div></div>`,
		fmtInt(animation.FrameCount),
		formatSecondsHuman(animation.FrameIntervalSeconds),
		fmtInt(animation.MaxTotalTransitionsPerFrame),
		html.EscapeString(animStartTime),
		html.EscapeString(animEndTime),
	)

	// Recommendations
	var recHTML strings.Builder
	for _, rec := range recommendations {
		recHTML.WriteString(fmt.Sprintf(
			"<li><strong>%s:</strong> %s</li>",
			html.EscapeString(rec.Title), html.EscapeString(rec.Why),
		))
	}
	if recHTML.Len() == 0 {
		recHTML.WriteString("<li>No additional recommendations for this filter state.</li>")
	}

	// Mermaid section
	mermaidSection := `<p class="empty">No Mermaid exports in this report.</p>`
	if len(mermaidExports) > 0 {
		var mb strings.Builder
		for name, body := range mermaidExports {
			mb.WriteString(fmt.Sprintf("<h3>%s</h3><pre>%s</pre>", html.EscapeString(name), html.EscapeString(body)))
		}
		mermaidSection = mb.String()
	}

	// Process map SVG
	mapSVG := reportMapSVG(nodes, edges)

	// Filters JSON
	filtersJSON, _ := json.MarshalIndent(filters, "", "  ")

	title := html.EscapeString(filename)
	return fmt.Sprintf(`<!doctype html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/><title>%s - Process Analysis Report</title><style>:root{--ink:#142027;--muted:#5b6d77;--line:#d1dde3;--panel:#f8fcff;--brand:#0b7a75;--bg:#eef4f7}*{box-sizing:border-box}body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--ink)}.page{max-width:1600px;margin:0 auto;padding:18px}.hero{background:linear-gradient(120deg,#0b7a75,#116087);color:#f7fffe;border-radius:16px;padding:16px 20px}.subtitle{opacity:.9}.meta{font-size:.9rem;opacity:.9}.grid{display:grid;gap:12px}.metrics{grid-template-columns:repeat(4,minmax(0,1fr));margin-top:12px}.metric{background:#fff;border:1px solid #dce8ee;border-radius:12px;padding:10px}.metric-label{font-size:.72rem;text-transform:uppercase;color:#50707f;letter-spacing:.06em}.metric-value{margin-top:6px;font-weight:700;font-size:1.2rem}.card{background:var(--panel);border:1px solid #d7e3ea;border-radius:14px;padding:12px;margin-top:12px}.card h2{margin:0 0 8px 0;font-size:1rem}.map-wrap{border:1px solid #d7e5eb;border-radius:12px;background:#fff;overflow:hidden}.map-wrap svg{width:100%%;height:auto;display:block}.table-wrap{overflow:auto;max-height:420px}table{width:100%%;border-collapse:collapse;font-size:.84rem}th,td{text-align:left;padding:8px;border-bottom:1px solid #e0eaef;vertical-align:top}th{position:sticky;top:0;background:#f6fbfd;font-size:.72rem;text-transform:uppercase;color:#4d6674}.empty{color:var(--muted);font-size:.9rem}.split{display:grid;grid-template-columns:1fr 1fr;gap:12px}.conformance{display:grid;gap:6px;font-size:.9rem;background:#fff;border:1px solid #dce8ee;border-radius:10px;padding:10px}pre{margin:0;background:#0f1d24;color:#d7f4ff;border-radius:10px;padding:10px;overflow:auto;font-size:.76rem}@media(max-width:1200px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.split{grid-template-columns:1fr}}@media(max-width:760px){.metrics{grid-template-columns:1fr}}</style></head><body><main class="page"><header class="hero"><h1 style="margin:0 0 8px 0;">Process Analysis Report</h1><div class="subtitle">%s</div><div class="meta">Exported at: %s | Log ID: %s</div></header><section class="grid metrics">%s</section><section class="card"><h2>Process Map Snapshot</h2>%s</section><section class="split"><section class="card"><h2>Conformance</h2>%s</section><section class="card"><h2>Animation Summary</h2>%s</section></section><section class="card"><h2>Top Paths</h2>%s</section><section class="card"><h2>Variants</h2>%s</section><section class="card"><h2>Bottlenecks</h2>%s</section><section class="card"><h2>Activity Statistics</h2>%s</section><section class="card"><h2>Actor Handoff (Actor Focused)</h2>%s</section><section class="card"><h2>Actor Handoff (Activity Focused)</h2>%s</section><section class="card"><h2>Swimlane View Data</h2>%s</section><section class="card"><h2>Sankey View Data</h2>%s</section><section class="card"><h2>Rework View</h2>%s</section><section class="card"><h2>Recommended Additional Views</h2><ul>%s</ul></section><section class="card"><h2>Mermaid Diagrams</h2>%s</section><section class="card"><h2>Applied Filters (JSON)</h2><pre>%s</pre></section></main></body></html>`,
		title, title, html.EscapeString(exportedAt), html.EscapeString(logID),
		cardsHTML.String(), mapSVG,
		conformanceHTML, animHTML,
		topEdgesTable, variantsTable, bottlenecksTable, actTable,
		handoffActorTable, handoffActTable,
		swimTable, sankeyTable, reworkTable,
		recHTML.String(), mermaidSection,
		html.EscapeString(string(filtersJSON)),
	)
}

// reportMapSVG generates a simple circular-layout process map SVG.
func reportMapSVG(nodes []NodeStat, edges []EdgeStat) string {
	if len(nodes) == 0 || len(edges) == 0 {
		return `<p class="empty">No process-map edges for current filters.</p>`
	}

	width := 1200.0
	height := 760.0
	cx := width / 2
	cy := height / 2
	radius := math.Min(width, height) * 0.33

	nodeMax := 1
	edgeMax := 1
	for _, n := range nodes {
		if n.Frequency > nodeMax {
			nodeMax = n.Frequency
		}
	}
	for _, e := range edges {
		if e.Frequency > edgeMax {
			edgeMax = e.Frequency
		}
	}

	type nodePos struct {
		X, Y float64
		Node NodeStat
	}
	positions := map[string]nodePos{}
	for i, n := range nodes {
		angle := (2*math.Pi*float64(i)/math.Max(float64(len(nodes)), 1)) - (math.Pi / 2)
		x := cx + radius*math.Cos(angle)
		y := cy + radius*0.74*math.Sin(angle)
		positions[n.ID] = nodePos{x, y, n}
	}

	var edgeLines, edgeLabels, nodeMarks strings.Builder

	edgeCount := len(edges)
	if edgeCount > 170 {
		edgeCount = 170
	}
	labelCount := 0
	for i := 0; i < edgeCount; i++ {
		e := edges[i]
		sp, sok := positions[e.Source]
		tp, tok := positions[e.Target]
		if !sok || !tok {
			continue
		}
		strength := math.Max(float64(e.Frequency)/float64(edgeMax), 0.05)
		strokeWidth := 1 + strength*8
		hue := 185 - int(strength*75)
		stroke := fmt.Sprintf("hsl(%d, 58%%, 43%%)", hue)
		opacity := 0.2 + strength*0.7

		if e.Source == e.Target {
			edgeLines.WriteString(fmt.Sprintf(
				`<path d="M %.2f %.2f C %.2f %.2f, %.2f %.2f, %.2f %.2f" fill="none" stroke="%s" stroke-width="%.2f" opacity="%.2f"/>`,
				sp.X, sp.Y-18, sp.X+32, sp.Y-48, sp.X+32, sp.Y+2, sp.X, sp.Y+10,
				stroke, strokeWidth, opacity,
			))
		} else {
			edgeLines.WriteString(fmt.Sprintf(
				`<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="%.2f" opacity="%.2f"/>`,
				sp.X, sp.Y, tp.X, tp.Y, stroke, strokeWidth, opacity,
			))
			if labelCount < 38 {
				lx := (sp.X + tp.X) / 2
				ly := (sp.Y + tp.Y) / 2
				edgeLabels.WriteString(fmt.Sprintf(
					`<text x="%.2f" y="%.2f" text-anchor="middle" font-size="12" fill="#214f61" font-family="IBM Plex Mono, monospace">%s</text>`,
					lx, ly, fmtInt(e.Frequency),
				))
				labelCount++
			}
		}
	}

	for _, pos := range positions {
		size := 16 + math.Max(float64(pos.Node.Frequency)/float64(nodeMax), 0.08)*34
		label := html.EscapeString(pos.Node.Label)
		nodeMarks.WriteString(fmt.Sprintf(
			`<circle cx="%.2f" cy="%.2f" r="%.2f" fill="rgba(11,122,117,0.16)"/>`,
			pos.X, pos.Y, size+5,
		))
		nodeMarks.WriteString(fmt.Sprintf(
			`<circle cx="%.2f" cy="%.2f" r="%.2f" fill="#0b7a75" stroke="#f7ffff" stroke-width="3"/>`,
			pos.X, pos.Y, size,
		))
		nodeMarks.WriteString(fmt.Sprintf(
			`<text x="%.2f" y="%.2f" text-anchor="middle" font-size="12" fill="#ecffff" font-family="IBM Plex Mono, monospace">%s</text>`,
			pos.X, pos.Y+4, fmtInt(pos.Node.Frequency),
		))
		nodeMarks.WriteString(fmt.Sprintf(
			`<text x="%.2f" y="%.2f" text-anchor="middle" font-size="12" fill="#1c495d" font-family="IBM Plex Mono, monospace">%s</text>`,
			pos.X, pos.Y+size+18, label,
		))
	}

	return fmt.Sprintf(
		`<div class="map-wrap"><svg viewBox="0 0 %.0f %.0f" role="img" aria-label="Process map snapshot">%s%s%s</svg></div>`,
		width, height, edgeLines.String(), edgeLabels.String(), nodeMarks.String(),
	)
}

// ---------------------------------------------------------------------------
// HTML table helper
// ---------------------------------------------------------------------------

func htmlTable(headers []string, rows [][]string) string {
	if len(rows) == 0 {
		return `<p class="empty">No rows for current filters.</p>`
	}
	var b strings.Builder
	b.WriteString(`<div class="table-wrap"><table><thead><tr>`)
	for _, h := range headers {
		b.WriteString(fmt.Sprintf("<th>%s</th>", html.EscapeString(h)))
	}
	b.WriteString("</tr></thead><tbody>")
	for _, row := range rows {
		b.WriteString("<tr>")
		for _, cell := range row {
			b.WriteString(fmt.Sprintf("<td>%s</td>", cell))
		}
		b.WriteString("</tr>")
	}
	b.WriteString("</tbody></table></div>")
	return b.String()
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

func fmtInt(v int) string {
	if v == 0 {
		return "0"
	}
	s := fmt.Sprintf("%d", v)
	if v < 0 {
		return s
	}
	// Add thousands separators
	n := len(s)
	if n <= 3 {
		return s
	}
	var result strings.Builder
	for i, c := range s {
		if i > 0 && (n-i)%3 == 0 {
			result.WriteByte(',')
		}
		result.WriteRune(c)
	}
	return result.String()
}

func fmtDec(v float64) string {
	return fmt.Sprintf("%.2f", v)
}

func fmtPct(v float64) string {
	return fmt.Sprintf("%.2f%%", v*100)
}
