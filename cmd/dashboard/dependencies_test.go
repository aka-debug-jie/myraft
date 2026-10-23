package main

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestExperimentDependencyReport(t *testing.T) {
	tests := []struct {
		name                          string
		source, goTool, python, ready bool
	}{
		{name: "source missing", goTool: true, python: true},
		{name: "go missing", source: true, python: true},
		{name: "python missing", source: true, goTool: true},
		{name: "all ready", source: true, goTool: true, python: true, ready: true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			d := versionFixture(t, "go1.26.3", "3.12.9")
			if !tt.source {
				if err := os.Remove(filepath.Join(d.opts.Source, "scripts", "benchmark.py")); err != nil {
					t.Fatal(err)
				}
			}
			for name, present := range map[string]bool{"go": tt.goTool, "python": tt.python} {
				if !present {
					path, err := exec.LookPath(name)
					if err != nil {
						t.Fatal(err)
					}
					if err = os.Remove(path); err != nil {
						t.Fatal(err)
					}
				}
			}
			report := d.experimentDependencyReport(false)
			if report.Ready != tt.ready || report.Source.Ready != tt.source || tt.source && (report.Go.Ready != tt.goTool || report.Python.Ready != tt.python) {
				t.Fatalf("unexpected report: %+v", report)
			}
			if tt.ready && report.Reason != "" || !tt.ready && report.Reason == "" {
				t.Fatalf("unexpected reason: %q", report.Reason)
			}
			recorder := httptest.NewRecorder()
			d.sessionHTTP(recorder, httptest.NewRequest("GET", "/api/session", nil))
			var response struct {
				Dependencies experimentDependencies `json:"experiment_dependencies"`
			}
			if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
				t.Fatal(err)
			}
			if response.Dependencies != report {
				t.Fatal("session did not return shared report")
			}
		})
	}
}
