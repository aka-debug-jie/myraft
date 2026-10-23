package main

import (
	"context"
	"fmt"
	"go/version"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	dependencyProbeTimeout = 3 * time.Second
	dependencyCacheTTL     = time.Minute
)

type dependencyCheck struct {
	Ready    bool   `json:"ready"`
	State    string `json:"state"`
	Version  string `json:"version,omitempty"`
	Required string `json:"required,omitempty"`
	Reason   string `json:"reason,omitempty"`
}

type experimentDependencies struct {
	Ready     bool            `json:"ready"`
	Source    dependencyCheck `json:"source"`
	Go        dependencyCheck `json:"go"`
	Python    dependencyCheck `json:"python"`
	Reason    string          `json:"reason"`
	CheckedAt time.Time       `json:"checked_at"`
	ExpiresAt time.Time       `json:"expires_at"`
}

type dependencyCache struct {
	mu     sync.Mutex
	report experimentDependencies
}

// This lock only serializes tool probes, never snapshots or Raft monitoring.
// An experiment refreshes before starting; browser requests share a minute's result.
func (d *dashboard) experimentDependencyReport(refresh bool) experimentDependencies {
	d.dependencies.mu.Lock()
	defer d.dependencies.mu.Unlock()
	if !refresh && time.Now().Before(d.dependencies.report.ExpiresAt) {
		return d.dependencies.report
	}
	ctx, cancel := context.WithTimeout(d.ctx, dependencyProbeTimeout)
	defer cancel()
	report := probeDependencies(ctx, d.opts)
	report.CheckedAt = time.Now().UTC()
	report.ExpiresAt = report.CheckedAt.Add(dependencyCacheTTL)
	d.dependencies.report = report
	return report
}

func probeDependencies(ctx context.Context, opts settings) experimentDependencies {
	report := experimentDependencies{
		Source: dependencyCheck{State: "error"},
		Go:     dependencyCheck{State: "not_checked"},
		Python: dependencyCheck{State: "not_checked", Required: "3.12"},
	}
	required := ""
	for _, name := range []string{"scripts/benchmark.py", "go.mod"} {
		path := filepath.Join(opts.Source, name)
		info, err := os.Stat(path)
		if err != nil || !info.Mode().IsRegular() {
			report.Source.Reason = fmt.Sprintf("configured source is missing %s", name)
			report.Reason = report.Source.Reason
			return report
		}
	}
	module, err := os.ReadFile(filepath.Join(opts.Source, "go.mod"))
	if err == nil {
		for _, line := range strings.Split(string(module), "\n") {
			fields := strings.Fields(line)
			if len(fields) >= 2 && fields[0] == "go" && version.IsValid("go"+fields[1]) {
				required = fields[1]
				break
			}
		}
	}
	if required == "" {
		report.Source.Reason = "configured go.mod has no readable Go version requirement"
		report.Reason = report.Source.Reason
		return report
	}
	report.Source = dependencyCheck{Ready: true, State: "ready"}
	report.Go = probeToolVersion(ctx, "go", "go", required)
	report.Python = probeToolVersion(ctx, opts.Python, "python", "3.12")
	reasons := []string{}
	for _, check := range []dependencyCheck{report.Go, report.Python} {
		if !check.Ready {
			reasons = append(reasons, check.Reason)
		}
	}
	report.Ready = len(reasons) == 0
	report.Reason = strings.Join(reasons, "; ")
	return report
}

func probeToolVersion(ctx context.Context, executable, kind, required string) dependencyCheck {
	result := dependencyCheck{State: "missing", Required: required}
	path, err := exec.LookPath(executable)
	if err != nil {
		result.Reason = kind + " executable not found in PATH"
		if kind == "python" {
			result.Reason = "configured Python executable is unavailable"
		}
		return result
	}
	result.State = "error"
	arg := "--version"
	if kind == "go" {
		arg = "version"
	}
	cmd := exec.CommandContext(ctx, path, arg)
	cmd.Env = append(os.Environ(), "GOTOOLCHAIN=local")
	cmd.WaitDelay = 100 * time.Millisecond
	output, err := cmd.Output()
	if err != nil {
		result.Reason = kind + " version probe failed"
		if ctx.Err() != nil {
			result.Reason = kind + " version probe canceled or timed out"
		}
		return result
	}
	fields := strings.Fields(string(output))
	compatible := false
	if kind == "go" {
		if len(fields) < 3 || fields[0] != "go" || fields[1] != "version" || !version.IsValid(fields[2]) {
			result.Reason = "unrecognized go version output"
			return result
		}
		result.Version = fields[2]
		compatible = version.Compare(result.Version, "go"+required) >= 0
	} else {
		if len(fields) != 2 || fields[0] != "Python" {
			result.Reason = "unrecognized Python version output"
			return result
		}
		numbers := strings.Split(fields[1], ".")
		if len(numbers) != 3 {
			result.Reason = "unrecognized Python version output"
			return result
		}
		v := [3]int{}
		for i, n := range numbers {
			v[i], err = strconv.Atoi(n)
			if err != nil || v[i] < 0 {
				result.Reason = "unrecognized Python version output"
				return result
			}
		}
		result.Version = fields[1]
		compatible = v[0] > 3 || v[0] == 3 && v[1] >= 12
	}
	if !compatible {
		result.State = "unsupported"
		result.Reason = fmt.Sprintf("%s %s or newer required, found %s", kind, required, result.Version)
		return result
	}
	result.Ready = true
	result.State = "ready"
	return result
}
