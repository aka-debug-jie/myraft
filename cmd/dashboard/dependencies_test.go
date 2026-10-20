package main

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestExperimentDependencyReport(t *testing.T) {
	tests := []struct {
		name                   string
		source, goTool, python bool
		ready                  bool
	}{
		{name: "source missing", goTool: true, python: true},
		{name: "go missing", source: true, python: true},
		{name: "python missing", source: true, goTool: true},
		{name: "all ready", source: true, goTool: true, python: true, ready: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dir := t.TempDir()
			source := filepath.Join(dir, "source")
			bin := filepath.Join(dir, "bin")
			if err := os.MkdirAll(bin, 0700); err != nil {
				t.Fatal(err)
			}
			if tt.source {
				if err := os.MkdirAll(filepath.Join(source, "scripts"), 0700); err != nil {
					t.Fatal(err)
				}
				for _, name := range []string{"scripts/benchmark.py", "go.mod"} {
					if err := os.WriteFile(filepath.Join(source, name), []byte("fixture"), 0600); err != nil {
						t.Fatal(err)
					}
				}
			}
			suffix := ""
			if runtime.GOOS == "windows" {
				suffix = ".exe"
				t.Setenv("PATHEXT", ".EXE")
			}
			for _, tool := range []struct {
				name    string
				present bool
			}{{"go", tt.goTool}, {"python", tt.python}} {
				if tool.present {
					if err := os.WriteFile(filepath.Join(bin, tool.name+suffix), []byte("fixture"), 0700); err != nil {
						t.Fatal(err)
					}
				}
			}
			t.Setenv("PATH", bin)
			d := &dashboard{opts: settings{Source: source, Python: "python"}}
			report := d.experimentDependencyReport()
			if report.Ready != tt.ready || report.Source.Ready != tt.source || report.Go.Ready != tt.goTool || report.Python.Ready != tt.python {
				t.Fatalf("unexpected dependency report: %+v", report)
			}
			if tt.ready && report.Reason != "" || !tt.ready && report.Reason == "" {
				t.Fatalf("unexpected report reason: %q", report.Reason)
			}
			if tt.name == "all ready" {
				recorder := httptest.NewRecorder()
				d.sessionHTTP(recorder, httptest.NewRequest("GET", "/api/session", nil))
				var response map[string]any
				if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
					t.Fatal(err)
				}
				if _, ok := response["experiment_dependencies"]; !ok {
					t.Fatal("session response is missing experiment_dependencies")
				}
			}
		})
	}
}
