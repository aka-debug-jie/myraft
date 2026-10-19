package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func postOperation(t *testing.T, d *dashboard, s *httptest.Server, fields map[string]any) (int, operation) {
	t.Helper()
	d.mu.Lock()
	fields["session_id"] = d.active.ID
	fields["generation"] = d.generation
	fields["controller_id"] = d.controllerID
	token, host := d.csrf, d.opts.Host
	d.mu.Unlock()
	b, _ := json.Marshal(fields)
	req, _ := http.NewRequest("POST", s.URL+"/api/operations", strings.NewReader(string(b)))
	req.Header.Set("Origin", "http://"+host)
	req.Header.Set("X-CSRF-Token", token)
	req.Header.Set("Content-Type", "application/json")
	response, err := s.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(response.Body)
	var op operation
	json.Unmarshal(body, &op)
	return response.StatusCode, op
}

func TestOwnershipChild(t *testing.T) {
	if os.Getenv("MYRAFT_DASHBOARD_HELPER") == "1" {
		io.Copy(io.Discard, os.Stdin)
	}
}

func TestRestartRunningNodeNeverKillsExistingProcess(t *testing.T) {
	d, s, _ := testConsole(t)
	cmd := exec.Command(os.Args[0], "-test.run=^TestOwnershipChild$")
	cmd.Env = append(os.Environ(), "MYRAFT_DASHBOARD_HELPER=1")
	input, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	defer input.Close()
	if err = cmd.Start(); err != nil {
		t.Fatal(err)
	}
	p := &ownedProcess{cmd: cmd, path: cmd.Path, args: append([]string(nil), cmd.Args...), startedAt: time.Now(), running: true, done: make(chan struct{})}
	d.mu.Lock()
	clone := *d.active
	clone.Managed = true
	d.active = &clone
	d.processes[1] = p
	d.control = true
	d.mu.Unlock()
	go func() { cmd.Wait(); d.mu.Lock(); p.running = false; close(p.done); d.mu.Unlock() }()
	code, op := postOperation(t, d, s, map[string]any{"kind": "restart", "node_id": 1})
	if code != 202 {
		t.Fatal(code)
	}
	op = awaitOperation(t, d, op.ID)
	d.mu.Lock()
	running := p.running
	d.mu.Unlock()
	if op.State != "failed" || !running {
		t.Fatal("failed restart killed the existing owned process")
	}
	// Even corrupt/missing configuration must not prevent stopping a real owned handle.
	if err := d.stopNode(1); err != nil {
		t.Fatal(err)
	}
}

func TestCheckpointSurvivesControllerRestart(t *testing.T) {
	d, _, _ := testConsole(t)
	d.mu.Lock()
	id := d.active.ID
	d.checkpoint = &checkpoint{Index: 17, Hash: "saved-prefix", X: 25}
	d.target = 17
	err := d.persistEvidenceLocked()
	opts := d.opts
	d.mu.Unlock()
	if err != nil {
		t.Fatal(err)
	}
	d.Close()
	restarted, err := newDashboard(opts)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted.Close()
	if restarted.active.ID != id || restarted.checkpoint == nil || restarted.checkpoint.Index != 17 || restarted.checkpoint.Hash != "saved-prefix" || restarted.target != 17 {
		t.Fatal("saved checkpoint was lost")
	}
}

func TestFailedEventReadDoesNotAdvanceCursor(t *testing.T) {
	d, _, p := testConsole(t)
	p.eventSeq.Store(1)
	p.eventFailure.Store(true)
	d.collectRound()
	d.mu.Lock()
	cursor := d.eventCursors[1]
	d.mu.Unlock()
	if cursor.Seq != 0 {
		t.Fatal("failed event fetch consumed sequence")
	}
	p.eventFailure.Store(false)
	d.collectRound()
	d.collectRound()
	d.mu.Lock()
	cursor = d.eventCursors[1]
	count := 0
	for _, e := range d.events {
		if e.Name == "real_event" {
			count++
		}
	}
	d.mu.Unlock()
	if cursor.Seq != 1 || p.eventCalls.Load() != 2 || count != 1 {
		t.Fatalf("events lost or duplicated: %+v calls=%d events=%d", cursor, p.eventCalls.Load(), count)
	}
}

func TestOldVerificationCannotOverwriteNewObservation(t *testing.T) {
	d, _, p := testConsole(t)
	p.revision.Store(1)
	d.collectRound()
	p.holdFull.Store(true)
	defer close(p.fullRelease)
	d.mu.Lock()
	s := d.active
	sampleTime := d.snap.CompletedAt
	d.mu.Unlock()
	done := make(chan error, 1)
	go func() { _, err := d.verify(context.Background(), s, "verify"); done <- err }()
	<-p.fullEntered
	p.revision.Store(2)
	d.collectRound()
	d.mu.Lock()
	// A coarse or adjusted wall clock can give a later round the same timestamp.
	d.snap.CompletedAt = sampleTime
	d.mu.Unlock()
	p.fullRelease <- struct{}{}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	d.mu.Lock()
	state := d.currentCheck.State
	d.mu.Unlock()
	if state != "stale" {
		t.Fatalf("old result repainted current pass: %s", state)
	}
}
func awaitOperation(t *testing.T, d *dashboard, id string) operation {
	t.Helper()
	until := time.Now().Add(3 * time.Second)
	for time.Now().Before(until) {
		d.mu.Lock()
		for _, op := range d.operations {
			if op.ID == id && op.EndedAt != nil {
				copy := *op
				d.mu.Unlock()
				return copy
			}
		}
		d.mu.Unlock()
		time.Sleep(time.Millisecond)
	}
	t.Fatal("operation did not finish")
	return operation{}
}

func TestReadOnlyControlAndClosedInputs(t *testing.T) {
	d, s, p := testConsole(t)
	if code, _ := postOperation(t, d, s, map[string]any{"kind": "generate", "count": 1}); code != 403 {
		t.Fatal("readonly write allowed")
	}
	if code, _ := postOperation(t, d, s, map[string]any{"kind": "enable_control", "confirm": true}); code != 403 {
		t.Fatal("server permission bypassed")
	}
	d.mu.Lock()
	d.opts.AllowControl = true
	d.mu.Unlock()
	if code, _ := postOperation(t, d, s, map[string]any{"kind": "enable_control"}); code != 403 {
		t.Fatal("missing opt-in accepted")
	}
	if code, _ := postOperation(t, d, s, map[string]any{"kind": "enable_control", "confirm": true}); code != 200 {
		t.Fatal("control opt-in failed")
	}
	for _, body := range []map[string]any{{"kind": "stop", "node_id": 1}, {"kind": "stop", "node_id": 999, "confirm": true}, {"kind": "stop", "node_id": 1, "confirm": true, "pid": 1}, {"kind": "create_session", "nodes": []int{101}, "batch": 128, "name": "test"}, {"kind": "generate", "count": 100001}} {
		if code, _ := postOperation(t, d, s, body); code != 400 {
			t.Fatalf("invalid input accepted: %+v %d", body, code)
		}
	}
	code, op := postOperation(t, d, s, map[string]any{"kind": "generate", "count": 2, "seed": 42})
	if code != 202 {
		t.Fatal(code)
	}
	op = awaitOperation(t, d, op.ID)
	if op.State != "succeeded" || op.Accepted == nil || !*op.Accepted || op.Committed == nil || !*op.Committed || p.generates.Load() != 1 {
		t.Fatalf("wrong write receipt %+v", op)
	}
	code, op = postOperation(t, d, s, map[string]any{"kind": "stop", "node_id": 1, "confirm": true})
	if code != 202 {
		t.Fatal(code)
	}
	op = awaitOperation(t, d, op.ID)
	b, _ := json.Marshal(op.Result)
	if op.State != "failed" || !strings.Contains(string(b), `"exit_confirmed":false`) {
		t.Fatal("unowned process falsely confirmed stopped")
	}
}

func TestUnknownWriteAndConcurrentClicksAreNotResent(t *testing.T) {
	d, s, p := testConsole(t)
	d.mu.Lock()
	d.control = true
	d.mu.Unlock()
	p.hold.Store(true)
	p.unknown.Store(true)
	defer close(p.writeRelease)
	code, op := postOperation(t, d, s, map[string]any{"kind": "generate", "count": 2})
	if code != 202 {
		t.Fatal(code)
	}
	select {
	case <-p.writeEntered:
	case <-time.After(time.Second):
		t.Fatal("write never reached node")
	}
	if code, _ := postOperation(t, d, s, map[string]any{"kind": "generate", "count": 2}); code != 409 {
		t.Fatal("double click queued another write")
	}
	p.writeRelease <- struct{}{}
	finished := awaitOperation(t, d, op.ID)
	if finished.State != "outcome_unknown" || finished.Committed != nil || p.generates.Load() != 1 {
		t.Fatalf("unknown write retried/confirmed %+v", finished)
	}
}

func TestOperationJournalNeverReplaysUncertainWrites(t *testing.T) {
	d, _, p := testConsole(t)
	d.mu.Lock()
	d.operations = []*operation{{ID: "prior-operation", Kind: "generate", State: "submitted", CreatedAt: time.Now()}}
	if err := d.persistOperationsLocked(); err != nil {
		t.Fatal(err)
	}
	d.operations = nil
	d.mu.Unlock()
	if err := d.loadOperations(); err != nil {
		t.Fatal(err)
	}
	if len(d.operations) != 1 || d.operations[0].State != "outcome_unknown" || len(d.jobs) != 0 || p.generates.Load() != 0 {
		t.Fatal("prior task replayed")
	}
}

func TestStaleGenerationCannotMutateAndOldLogResponseIsDiscarded(t *testing.T) {
	d, s, p := testConsole(t)
	p.blockLogs = make(chan struct{})
	p.entered = make(chan struct{}, 1)
	defer close(p.blockLogs)
	d.mu.Lock()
	sessionID, gen := d.active.ID, d.generation
	d.mu.Unlock()
	done := make(chan int, 1)
	go func() {
		response, err := s.Client().Get(fmt.Sprintf("%s/api/nodes/1/logs?from=1&session_id=%s&generation=%d", s.URL, sessionID, gen))
		if err != nil {
			done <- 0
			return
		}
		response.Body.Close()
		done <- response.StatusCode
	}()
	<-p.entered
	d.mu.Lock()
	d.generation++
	d.mu.Unlock()
	p.blockLogs <- struct{}{}
	if code := <-done; code != 409 {
		t.Fatalf("old log response accepted: %d", code)
	}
	body := fmt.Sprintf(`{"kind":"generate","count":1,"session_id":%q,"generation":%d}`, sessionID, gen)
	req, _ := http.NewRequest("POST", s.URL+"/api/operations", strings.NewReader(body))
	req.Header.Set("Origin", "http://"+d.opts.Host)
	req.Header.Set("X-CSRF-Token", d.csrf)
	req.Header.Set("Content-Type", "application/json")
	r, err := s.Client().Do(req)
	if err != nil {
		t.Fatal(err)
	}
	r.Body.Close()
	if r.StatusCode != 409 || p.generates.Load() != 0 {
		t.Fatal("old mutation accepted")
	}
}
