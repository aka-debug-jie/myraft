package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

type dependencyCheck struct {
	Ready  bool   `json:"ready"`
	Reason string `json:"reason,omitempty"`
}

type experimentDependencies struct {
	Ready  bool            `json:"ready"`
	Source dependencyCheck `json:"source"`
	Go     dependencyCheck `json:"go"`
	Python dependencyCheck `json:"python"`
	Reason string          `json:"reason"`
}

// experimentDependencyReport performs only filesystem and PATH lookups. Source
// is the controller-configured checkout; no request value is used as a path.
func (d *dashboard) experimentDependencyReport() experimentDependencies {
	report := experimentDependencies{Ready: true}
	for _, name := range []string{"scripts/benchmark.py", "go.mod"} {
		path := filepath.Join(d.opts.Source, name)
		info, err := os.Stat(path)
		if err != nil || !info.Mode().IsRegular() {
			report.Source = dependencyCheck{Reason: fmt.Sprintf("configured source is missing %s", name)}
			break
		}
		report.Source = dependencyCheck{Ready: true}
	}
	_, err := exec.LookPath("go")
	if err != nil {
		report.Go = dependencyCheck{Reason: "go executable not found in PATH"}
	} else {
		report.Go = dependencyCheck{Ready: true}
	}
	if _, err := exec.LookPath(d.opts.Python); err != nil {
		report.Python = dependencyCheck{Reason: "configured Python executable is unavailable"}
	} else {
		report.Python = dependencyCheck{Ready: true}
	}
	reasons := make([]string, 0, 3)
	for _, check := range []dependencyCheck{report.Source, report.Go, report.Python} {
		if !check.Ready {
			reasons = append(reasons, check.Reason)
		}
	}
	report.Ready = len(reasons) == 0
	if len(reasons) > 0 {
		report.Reason = strings.Join(reasons, "; ")
	}
	return report
}
