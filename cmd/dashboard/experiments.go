package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"time"
)

type experimentResult struct {
	Phase       string           `json:"phase"`
	Planned     int              `json:"planned"`
	Rows        []map[string]any `json:"rows"`
	Environment map[string]any   `json:"environment"`
	RunStatus   map[string]any   `json:"run_status"`
}

func readExperiment(dir string, previous experimentResult) experimentResult {
	read := func(name string, target any) bool {
		b, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			return false
		}
		decoder := json.NewDecoder(bytes.NewReader(b))
		decoder.UseNumber()
		return decoder.Decode(target) == nil
	}
	var rows []map[string]any
	if read("results.json", &rows) {
		previous.Rows = rows
	}
	var env map[string]any
	if read("environment.json", &env) {
		previous.Environment = env
	}
	var status map[string]any
	if read("run-status.json", &status) {
		previous.RunStatus = status
	}
	previous.Phase = "building"
	if previous.Environment["binary_sha256"] != nil {
		previous.Phase = "running"
	}
	if previous.RunStatus["status"] != nil {
		previous.Phase = "finished"
	}
	// Source/environment are explicit grouping keys, never inferred from old records.
	for _, row := range previous.Rows {
		row["platform"] = previous.Environment["platform"]
		if source := previous.Environment["source_sha256"]; source != nil {
			row["source_sha256"] = digestJSON(source)
		} else {
			row["source_sha256"] = "未记录"
		}
	}
	return previous
}

func (d *dashboard) runExperiment(ctx context.Context, job operationJob) (any, error) {
	dependencies := d.experimentDependencyReport()
	if !dependencies.Ready {
		return map[string]any{"category": "environment_unavailable", "experiment_dependencies": dependencies}, fmt.Errorf("experiment environment not ready: %s", dependencies.Reason)
	}
	r := job.request
	parent := filepath.Join(d.opts.Root, "experiments")
	if err := os.MkdirAll(parent, 0700); err != nil {
		return nil, err
	}
	output := filepath.Join(parent, job.op.ID)
	marker := filepath.Join(parent, job.op.ID+".cancel")
	script := filepath.Join(d.opts.Source, "scripts", "benchmark.py")
	args := []string{script, "--output", output, "--cancel-file", marker, "--entries", strconv.Itoa(r.Count), "--rounds", strconv.Itoa(r.Rounds), "--seed", strconv.FormatInt(r.Seed, 10), "--batch-sizes", strconv.Itoa(r.Batch), "--nodes"}
	for _, n := range r.Nodes {
		args = append(args, strconv.Itoa(n))
	}
	args = append(args, "--scenarios")
	args = append(args, r.Scenarios...)
	logFile, err := os.OpenFile(filepath.Join(parent, job.op.ID+".log"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return nil, err
	}
	defer logFile.Close()
	cmd := exec.Command(d.opts.Python, args...)
	cmd.Dir = d.opts.Source
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	if err = cmd.Start(); err != nil {
		return nil, err
	}
	d.mu.Lock()
	d.activeCancel = marker
	d.mu.Unlock()
	cancelResult := make(chan error, 1)
	stopCancel := context.AfterFunc(ctx, func() { cancelResult <- os.WriteFile(marker, []byte("cancel\n"), 0600) })
	defer stopCancel()
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()
	result := experimentResult{Planned: len(r.Nodes) * len(r.Scenarios) * r.Rounds, Rows: []map[string]any{}}
	var cancelDeadline <-chan time.Time
	var cancelError error
	beginCancel := func() {
		if cancelDeadline == nil {
			cancelDeadline = time.After(15 * time.Second)
		}
	}
	for {
		select {
		case cancelError = <-cancelResult:
			beginCancel()
		case <-cancelDeadline:
			// Killing an unresponsive runner cannot prove its children were cleaned.
			cmd.Process.Kill()
			select {
			case <-done:
			case <-time.After(2 * time.Second):
			}
			d.mu.Lock()
			job.op.State = "cleanup_unconfirmed"
			d.mu.Unlock()
			return readExperiment(output, result), fmt.Errorf("runner did not finish cancellation in 15s; child cleanup unconfirmed (marker error: %v)", cancelError)
		case <-ticker.C:
			if _, e := os.Stat(marker); e == nil {
				beginCancel()
			}
			result = readExperiment(output, result)
			// Decode a fresh copy for publishing; later reads never mutate an SSE frame.
			b, _ := json.Marshal(result)
			var published experimentResult
			decoder := json.NewDecoder(bytes.NewReader(b))
			decoder.UseNumber()
			decoder.Decode(&published)
			d.mu.Lock()
			job.op.Result = published
			d.broadcastLocked()
			d.mu.Unlock()
		case err = <-done:
			result = readExperiment(output, result)
			if result.RunStatus["status"] == "INTERRUPTED" {
				d.mu.Lock()
				job.op.State = "canceled"
				d.mu.Unlock()
				return result, fmt.Errorf("experiment interrupted; partial results retained and owned processes cleaned by runner")
			}
			if err != nil {
				return result, fmt.Errorf("experiment exited unsuccessfully: %w; inspect retained runner output", err)
			}
			if result.RunStatus["status"] != "COMPLETE" || len(result.Rows) != result.Planned {
				return result, fmt.Errorf("runner completion/evidence is incomplete")
			}
			for _, row := range result.Rows {
				if row["result"] != "PASS" {
					return result, fmt.Errorf("one or more trials failed")
				}
			}
			return result, nil
		}
	}
}
