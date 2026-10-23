package main

import (
	"archive/zip"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"myraft/config"
)

func TestExportContainsEvidenceWithoutPathsOrCredentials(t *testing.T) {
	d, s, _ := testConsole(t)
	d.mu.Lock()
	session := d.active
	d.checkpoint = &checkpoint{Index: 1, Hash: "saved-prefix", X: 0}
	d.mu.Unlock()
	id := config.NewClusterID()
	op := &operation{ID: id, SessionID: session.ID, Kind: "export", State: "running"}
	result, err := d.exportEvidence(operationJob{op: op, session: session})
	if err != nil {
		t.Fatal(err)
	}
	if result.(map[string]any)["export_id"] != id {
		t.Fatal("wrong export receipt")
	}
	d.mu.Lock()
	path := d.exports[id]
	d.mu.Unlock()
	z, err := zip.OpenReader(path)
	if err != nil {
		t.Fatal(err)
	}
	defer z.Close()
	names := map[string]bool{}
	for _, file := range z.File {
		r, e := file.Open()
		if e != nil {
			t.Fatal(e)
		}
		b, e := io.ReadAll(r)
		r.Close()
		if e != nil {
			t.Fatal(e)
		}
		names[file.Name] = true
		if strings.Contains(string(b), d.csrf) || strings.Contains(string(b), d.opts.Root) || strings.Contains(string(b), "csrf_token") {
			t.Fatalf("private data in %s", file.Name)
		}
	}
	for _, name := range []string{"manifest.json", "snapshot.json", "receipts.json", "nodes.csv", "owned-processes.json"} {
		if !names[name] {
			t.Fatalf("missing %s", name)
		}
	}
	r, err := s.Client().Get(s.URL + "/api/exports/" + id)
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	if r.StatusCode != 200 {
		t.Fatal("registered export unavailable")
	}
	r, err = s.Client().Get(s.URL + "/api/exports/not-registered")
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	if r.StatusCode != 404 {
		t.Fatal("unregistered export served")
	}
	data, err := d.exportJSON(map[string]any{"x": int64(9007199254740993), "csrf_token": d.csrf, "path": d.opts.Root, "process_id": 123})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), "9007199254740993") || strings.Contains(string(data), d.opts.Root) || strings.Contains(string(data), d.csrf) || strings.Contains(string(data), "process_id") {
		t.Fatal("export redaction changed integer or leaked data")
	}
}

func TestCancellationOnlyTargetsRegisteredActiveExperiment(t *testing.T) {
	d, s, _ := testConsole(t)
	marker := filepath.Join(d.opts.Root, "owned.cancel")
	d.mu.Lock()
	d.control = true
	d.busy = true
	d.activeCancel = marker
	d.operations = append(d.operations, &operation{ID: "active-experiment", Kind: "experiment", State: "running"})
	d.mu.Unlock()
	if code, _ := postOperation(t, d, s, map[string]any{"kind": "cancel_experiment", "operation_id": "other"}); code != 404 {
		t.Fatal("unregistered cancellation accepted")
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("wrong operation wrote marker")
	}
	if code, _ := postOperation(t, d, s, map[string]any{"kind": "cancel_experiment", "operation_id": "active-experiment"}); code != 200 {
		t.Fatal("owned cancellation rejected")
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatal(err)
	}
}

func TestExperimentReadingKeepsSourceGroupsAndPartialStates(t *testing.T) {
	dir := t.TempDir()
	writeJSONFile(filepath.Join(dir, "environment.json"), map[string]any{"platform": "Linux", "source_sha256": map[string]string{"raft.go": "hash"}, "binary_sha256": "binary"})
	writeJSONFile(filepath.Join(dir, "results.json"), []map[string]any{{"nodes": 3, "scenario": "replication", "result": "PASS", "elapsed_seconds": .2}, {"nodes": 3, "scenario": "replication", "result": "INTERRUPTED", "elapsed_seconds": nil}})
	result := readExperiment(dir, experimentResult{Planned: 3})
	if len(result.Rows) != 2 || result.Phase != "running" || result.Rows[0]["platform"] != "Linux" || result.Rows[1]["result"] != "INTERRUPTED" {
		t.Fatalf("wrong progress %+v", result)
	}
	b, _ := json.Marshal(result)
	var published experimentResult
	json.Unmarshal(b, &published)
	os.WriteFile(filepath.Join(dir, "results.json"), []byte("["), 0600)
	readAgain := readExperiment(dir, result)
	if len(readAgain.Rows) != 2 || published.Rows[0]["source_sha256"] != result.Rows[0]["source_sha256"] {
		t.Fatal("partial write discarded progress")
	}
}

func TestExperimentIntegerPrecisionSurvivesJournalAndExport(t *testing.T) {
	const exact = "9007199254740993"
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "results.json"), []byte(`[{"value":`+exact+`,"result":"PASS"}]`), 0600); err != nil {
		t.Fatal(err)
	}
	result := readExperiment(dir, experimentResult{})
	b, err := json.Marshal(result)
	if err != nil {
		t.Fatal(err)
	}
	var published experimentResult
	decoder := json.NewDecoder(strings.NewReader(string(b)))
	decoder.UseNumber()
	if err = decoder.Decode(&published); err != nil {
		t.Fatal(err)
	}
	d := &dashboard{opts: settings{Root: dir}, exports: map[string]string{}}
	d.operations = []*operation{{ID: "precision", Kind: "experiment", State: "succeeded", Result: published}}
	if err = d.persistOperationsLocked(); err != nil {
		t.Fatal(err)
	}
	d.operations = nil
	if err = d.loadOperations(); err != nil {
		t.Fatal(err)
	}
	data, err := d.exportJSON(d.operations[0].Result)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), exact) {
		t.Fatalf("integer precision lost in exported journal result: %s", data)
	}
}

func TestHistoryCheckRejectsEqualCurrentStateWithChangedPrefix(t *testing.T) {
	d, _, _ := testConsole(t)
	d.mu.Lock()
	s := d.active
	d.checkpoint = &checkpoint{Index: 1, Hash: "a-different-saved-prefix", X: 0}
	d.mu.Unlock()
	if _, err := d.verify(context.Background(), s, "verify"); err != nil {
		t.Fatal(err)
	}
	if _, err := d.verify(context.Background(), s, "verify_history"); err == nil {
		t.Fatal("equal final state replaced historical evidence")
	}
}

func TestExperimentCancellationFinishesAndRetainsStatus(t *testing.T) {
	python, err := exec.LookPath("python3")
	if err != nil {
		python, err = exec.LookPath("python")
	}
	if err != nil {
		t.Skip("Python unavailable")
	}
	probeCtx, stopProbe := context.WithTimeout(context.Background(), dependencyProbeTimeout)
	defer stopProbe()
	if check := probeToolVersion(probeCtx, python, "python", "3.12"); !check.Ready {
		t.Skip(check.Reason)
	}
	d, _, _ := testConsole(t)
	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "go.mod"), []byte("module experiment-fixture\n\ngo 1.26.3\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(source, "scripts"), 0700); err != nil {
		t.Fatal(err)
	}
	// A cooperative runner lets us exercise the real controller process lifecycle.
	script := `import pathlib,sys,time
args=sys.argv
out=pathlib.Path(args[args.index('--output')+1]); out.mkdir()
marker=pathlib.Path(args[args.index('--cancel-file')+1])
while not marker.exists(): time.sleep(.01)
(out/'run-status.json').write_text('{"status":"INTERRUPTED","completed":0}')
`
	if err := os.WriteFile(filepath.Join(source, "scripts", "benchmark.py"), []byte(script), 0600); err != nil {
		t.Fatal(err)
	}
	d.opts.Source, d.opts.Python = source, python
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	op := &operation{ID: config.NewClusterID(), State: "running"}
	result, err := d.runExperiment(ctx, operationJob{op: op, request: operationRequest{Nodes: []int{3}, Scenarios: []string{"election"}, Rounds: 1}})
	if err == nil || op.State != "canceled" || result.(experimentResult).RunStatus["status"] != "INTERRUPTED" {
		t.Fatalf("cancel result state=%s result=%+v err=%v", op.State, result, err)
	}
}
