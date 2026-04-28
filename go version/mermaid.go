package main

import (
	"fmt"
	"strings"
)

// ---------------------------------------------------------------------------
// Mermaid Diagram Generators
// ---------------------------------------------------------------------------

func sanitizeMermaidLabel(text string) string {
	text = strings.ReplaceAll(text, `"`, "'")
	text = strings.ReplaceAll(text, "\n", " ")
	return strings.TrimSpace(text)
}

func mermaidFlowchartFromNodesEdges(direction string, nodes []NodeStat, edges []EdgeStat, sourceKey, targetKey, edgeValueKey string) string {
	lines := []string{fmt.Sprintf("flowchart %s", direction)}
	aliasMap := map[string]string{}

	limit := len(nodes)
	if limit > 220 {
		limit = 220
	}
	for i := 0; i < limit; i++ {
		node := nodes[i]
		alias := fmt.Sprintf("N%d", i)
		aliasMap[node.ID] = alias
		label := sanitizeMermaidLabel(node.Label)
		lines = append(lines, fmt.Sprintf(`%s["%s"]`, alias, label))
	}

	edgeLimit := len(edges)
	if edgeLimit > 300 {
		edgeLimit = 300
	}
	for i := 0; i < edgeLimit; i++ {
		edge := edges[i]
		srcAlias, ok1 := aliasMap[edge.Source]
		tgtAlias, ok2 := aliasMap[edge.Target]
		if !ok1 || !ok2 {
			continue
		}
		lines = append(lines, fmt.Sprintf("%s -->|%d| %s", srcAlias, edge.Frequency, tgtAlias))
	}

	return strings.Join(lines, "\n")
}

func mermaidSwimlane(swimlane SwimlaneView) string {
	if !swimlane.Available {
		return ""
	}

	lines := []string{"flowchart LR"}
	aliasMap := map[string]string{}

	// Group nodes by lane
	laneNodes := map[string][]SwimlaneNode{}
	for _, n := range swimlane.Nodes {
		laneNodes[n.Lane] = append(laneNodes[n.Lane], n)
	}

	idx := 0
	for _, lane := range swimlane.Lanes {
		nodes, ok := laneNodes[lane]
		if !ok || len(nodes) == 0 {
			continue
		}
		lines = append(lines, fmt.Sprintf(`subgraph "%s"`, sanitizeMermaidLabel(lane)))
		for _, n := range nodes {
			alias := fmt.Sprintf("S%d", idx)
			aliasMap[n.ID] = alias
			label := sanitizeMermaidLabel(n.Label)
			lines = append(lines, fmt.Sprintf(`%s["%s"]`, alias, label))
			idx++
		}
		lines = append(lines, "end")
	}

	edgeLimit := len(swimlane.Edges)
	if edgeLimit > 320 {
		edgeLimit = 320
	}
	for i := 0; i < edgeLimit; i++ {
		e := swimlane.Edges[i]
		srcAlias, ok1 := aliasMap[e.Source]
		tgtAlias, ok2 := aliasMap[e.Target]
		if !ok1 || !ok2 {
			continue
		}
		lines = append(lines, fmt.Sprintf("%s -->|%d| %s", srcAlias, e.Frequency, tgtAlias))
	}

	return strings.Join(lines, "\n")
}

func mermaidSankey(sankey SankeyView) string {
	if !sankey.Available {
		return ""
	}

	lines := []string{"sankey-beta"}
	limit := len(sankey.Links)
	if limit > 400 {
		limit = 400
	}
	for i := 0; i < limit; i++ {
		l := sankey.Links[i]
		src := strings.ReplaceAll(l.Source, ",", " ")
		tgt := strings.ReplaceAll(l.Target, ",", " ")
		lines = append(lines, fmt.Sprintf("%s,%s,%d", src, tgt, l.Value))
	}
	return strings.Join(lines, "\n")
}

func mermaidRework(rework ReworkView) string {
	if len(rework.Activities) == 0 {
		return ""
	}

	lines := []string{"flowchart LR"}
	limit := len(rework.Activities)
	if limit > 80 {
		limit = 80
	}
	for i := 0; i < limit; i++ {
		a := rework.Activities[i]
		alias := fmt.Sprintf("R%d", i)
		label := sanitizeMermaidLabel(a.Activity)
		lines = append(lines, fmt.Sprintf(`%s["%s"]`, alias, label))

		ratioText := ""
		if a.ReworkCaseRatio > 0 {
			ratioText = fmt.Sprintf(" | %.1f%% cases", a.ReworkCaseRatio*100)
		}
		lines = append(lines, fmt.Sprintf("%s -->|%d%s| %s", alias, a.ReworkEvents, ratioText, alias))
	}
	return strings.Join(lines, "\n")
}

// GenerateMermaidExport generates all Mermaid diagram exports from a dashboard.
func GenerateMermaidExport(dashboard DashboardPayload) map[string]string {
	result := map[string]string{}

	result["process_map"] = mermaidFlowchartFromNodesEdges(
		"LR", dashboard.Nodes, dashboard.Edges, "source", "target", "frequency",
	)

	if dashboard.Handoff.Enabled {
		result["handoff_actor"] = mermaidFlowchartFromNodesEdges(
			"LR", dashboard.Handoff.ActorView.Nodes, dashboard.Handoff.ActorView.Edges,
			"source", "target", "frequency",
		)
		result["handoff_activity"] = mermaidFlowchartFromNodesEdges(
			"LR", dashboard.Handoff.ActivityView.Nodes, dashboard.Handoff.ActivityView.Edges,
			"source", "target", "frequency",
		)
	}

	if swimMermaid := mermaidSwimlane(dashboard.Swimlane); swimMermaid != "" {
		result["swimlane"] = swimMermaid
	}

	if sankeyMermaid := mermaidSankey(dashboard.Sankey); sankeyMermaid != "" {
		result["sankey"] = sankeyMermaid
	}

	if reworkMermaid := mermaidRework(dashboard.Rework); reworkMermaid != "" {
		result["rework"] = reworkMermaid
	}

	return result
}
