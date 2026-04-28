package main

import (
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ---------------------------------------------------------------------------
// CORS middleware
// ---------------------------------------------------------------------------

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == "OPTIONS" {
			w.WriteHeader(200)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// ---------------------------------------------------------------------------
// Request logging middleware
// ---------------------------------------------------------------------------

func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		t0 := time.Now()
		log.Printf("REQ %s %s", r.Method, r.URL.Path)
		next.ServeHTTP(w, r)
		log.Printf("RES %s %s (%.1f ms)", r.Method, r.URL.Path, float64(time.Since(t0).Microseconds())/1000)
	})
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

func setupRouter() http.Handler {
	mux := http.NewServeMux()

	// API endpoints
	mux.HandleFunc("/api/health", healthHandler)
	mux.HandleFunc("/api/logs/upload", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", 405)
			return
		}
		uploadLogHandler(w, r)
	})
	mux.HandleFunc("/api/logs/suggest-mapping", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", 405)
			return
		}
		suggestMappingHandler(w, r)
	})
	mux.HandleFunc("/api/logs", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet && r.URL.Path == "/api/logs" {
			listLogsHandler(w, r)
			return
		}
		// Route log-specific endpoints
		routeLogEndpoint(w, r)
	})

	// Catch-all for /api/logs/{log_id}/...
	mux.HandleFunc("/api/logs/", routeLogEndpoint)

	// Serve frontend files
	execDir := getExecDir()
	frontendDir := filepath.Join(execDir, "frontend")
	if _, err := os.Stat(frontendDir); os.IsNotExist(err) {
		// Try relative to working directory
		frontendDir = "frontend"
	}

	// Static assets at /assets/
	fs := http.FileServer(http.Dir(frontendDir))
	mux.Handle("/assets/", http.StripPrefix("/assets/", fs))

	// Root serves index.html
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			http.NotFound(w, r)
			return
		}
		indexPath := filepath.Join(frontendDir, "index.html")
		http.ServeFile(w, r, indexPath)
	})

	return loggingMiddleware(corsMiddleware(mux))
}

func routeLogEndpoint(w http.ResponseWriter, r *http.Request) {
	// Parse /api/logs/{log_id}/{action}
	path := strings.TrimPrefix(r.URL.Path, "/api/logs/")
	parts := strings.SplitN(path, "/", 2)
	if len(parts) == 0 || parts[0] == "" {
		http.NotFound(w, r)
		return
	}

	logID := parts[0]
	action := ""
	if len(parts) > 1 {
		action = parts[1]
	}

	switch {
	case action == "overview" && r.Method == http.MethodGet:
		logOverviewHandler(w, r, logID)
	case action == "dashboard" && r.Method == http.MethodPost:
		logDashboardHandler(w, r, logID)
	case action == "conformance" && r.Method == http.MethodPost:
		logConformanceHandler(w, r, logID)
	case action == "animation" && r.Method == http.MethodPost:
		logAnimationHandler(w, r, logID)
	case action == "export" && r.Method == http.MethodPost:
		logExportZipHandler(w, r, logID)
	case action == "export/html" && r.Method == http.MethodPost:
		logExportHTMLHandler(w, r, logID)
	default:
		http.NotFound(w, r)
	}
}

func getExecDir() string {
	ex, err := os.Executable()
	if err != nil {
		return "."
	}
	return filepath.Dir(ex)
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8000"
	}

	handler := setupRouter()

	addr := fmt.Sprintf(":%s", port)
	log.Printf("FlowScope Miner (Go) starting on http://127.0.0.1%s", addr)
	log.Printf("Frontend served from ./frontend/")

	if err := http.ListenAndServe(addr, handler); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}
