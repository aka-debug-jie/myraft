package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

type operationRequest struct {
	ControllerID  string   `json:"controller_id"`
	Kind          string   `json:"kind"`
	SessionID     string   `json:"session_id"`
	Generation    uint64   `json:"generation"`
	NodeID        int      `json:"node_id,omitempty"`
	Confirm       bool     `json:"confirm,omitempty"`
	Name          string   `json:"name,omitempty"`
	Nodes         []int    `json:"nodes,omitempty"`
	Count         int      `json:"count,omitempty"`
	Seed          int64    `json:"seed,omitempty"`
	Batch         int      `json:"batch,omitempty"`
	Rounds        int      `json:"rounds,omitempty"`
	Scenarios     []string `json:"scenarios,omitempty"`
	SelectSession string   `json:"select_session,omitempty"`
	OperationID   string   `json:"operation_id,omitempty"`
}
type operationJob struct {
	op      *operation
	request operationRequest
	session *session
}

func (d *dashboard) loadOperations() error {
	b, err := os.ReadFile(filepath.Join(d.opts.Root, "operations.json"))
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		return err
	}
	if err = json.Unmarshal(b, &d.operations); err != nil {
		return err
	}
	for _, op := range d.operations {
		if op.EndedAt == nil {
			now := time.Now().UTC()
			op.EndedAt = &now
			op.State = "interrupted"
			if op.Kind == "generate" {
				op.State = "outcome_unknown"
			}
			op.Error = "controller restarted; prior task will not be sent again"
		}
	}
	return d.persistOperationsLocked()
}
func (d *dashboard) persistOperationsLocked() error {
	return writeJSONFile(filepath.Join(d.opts.Root, "operations.json"), d.operations)
}

func (d *dashboard) operationsHTTP(w http.ResponseWriter, r *http.Request) {
	media, _, err := mime.ParseMediaType(r.Header.Get("Content-Type"))
	if err != nil || media != "application/json" {
		failure(w, 415, fmt.Errorf("application/json required"))
		return
	}
	var req operationRequest
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16384))
	decoder.DisallowUnknownFields()
	if err = decoder.Decode(&req); err != nil {
		failure(w, 400, err)
		return
	}
	if err = decoder.Decode(&struct{}{}); err != io.EOF {
		failure(w, 400, fmt.Errorf("one JSON request required"))
		return
	}
	d.mu.Lock()
	if req.ControllerID != d.controllerID || req.Generation != d.generation || (d.active == nil && req.SessionID != "") || (d.active != nil && req.SessionID != d.active.ID) {
		d.mu.Unlock()
		failure(w, 409, fmt.Errorf("session generation changed"))
		return
	}
	if req.Kind == "enable_control" {
		if !d.opts.AllowControl || !req.Confirm {
			d.mu.Unlock()
			failure(w, 403, fmt.Errorf("explicit confirmation and server -allow-control required"))
			return
		}
		d.control = true
		d.emitLocked(consoleEvent{Source: "control", Name: "control_enabled", Message: "使用者明确启用了本机会话控制"})
		d.broadcastLocked()
		d.mu.Unlock()
		respond(w, 200, map[string]string{"state": "enabled"})
		return
	}
	if req.Kind == "cancel_experiment" {
		if !d.control || !d.busy || d.activeCancel == "" {
			d.mu.Unlock()
			failure(w, 409, fmt.Errorf("no cancellable owned experiment"))
			return
		}
		var op *operation
		for _, o := range d.operations {
			if o.ID == req.OperationID && o.Kind == "experiment" && o.EndedAt == nil {
				op = o
			}
		}
		if op == nil {
			d.mu.Unlock()
			failure(w, 404, fmt.Errorf("experiment not registered"))
			return
		}
		path := d.activeCancel
		if err := os.WriteFile(path, []byte("cancel\n"), 0600); err != nil {
			d.mu.Unlock()
			failure(w, 500, err)
			return
		}
		op.State = "cancel_requested"
		d.broadcastLocked()
		copy := *op
		d.mu.Unlock()
		respond(w, 200, copy)
		return
	}
	readOnly := req.Kind == "verify" || req.Kind == "verify_history" || req.Kind == "checkpoint" || req.Kind == "export" || req.Kind == "select_session"
	if !readOnly && !d.control {
		d.mu.Unlock()
		failure(w, 403, fmt.Errorf("console is read-only"))
		return
	}
	if d.busy {
		d.mu.Unlock()
		failure(w, 409, fmt.Errorf("another operation is running; no duplicate request sent"))
		return
	}
	s := d.active
	err = validateOperation(req, s, d.sessions)
	if err != nil {
		d.mu.Unlock()
		failure(w, 400, err)
		return
	}
	op := &operation{ID: config.NewClusterID(), SessionID: req.SessionID, Generation: req.Generation, Kind: req.Kind, State: "queued", CreatedAt: time.Now().UTC()}
	d.operations = append(d.operations, op)
	if len(d.operations) > 128 {
		d.operations = append([]*operation(nil), d.operations[len(d.operations)-128:]...)
	}
	if err = d.persistOperationsLocked(); err != nil {
		d.operations = d.operations[:len(d.operations)-1]
		d.mu.Unlock()
		failure(w, 500, err)
		return
	}
	d.busy = true
	d.emitLocked(consoleEvent{Source: "control", OperationID: op.ID, Name: "operation_queued", Message: req.Kind})
	d.broadcastLocked()
	copy := *op
	d.jobs <- operationJob{op: op, request: req, session: s}
	d.mu.Unlock()
	respond(w, 202, copy)
}

func validateOperation(r operationRequest, s *session, sessions map[string]*session) error {
	if r.Kind != "create_session" && r.Kind != "select_session" && s == nil {
		return fmt.Errorf("no active session")
	}
	switch r.Kind {
	case "create_session":
		if len(r.Nodes) != 1 || r.Nodes[0] < 3 || r.Nodes[0] > 100 || len([]rune(strings.TrimSpace(r.Name))) < 1 || len([]rune(r.Name)) > 60 || r.Batch < 1 || r.Batch > 4096 {
			return fmt.Errorf("new session: 3..100 nodes, name 1..60, batch 1..4096")
		}
	case "select_session":
		if sessions[r.SelectSession] == nil {
			return fmt.Errorf("session not registered")
		}
	case "generate":
		if r.Count < 1 || r.Count > 100000 {
			return fmt.Errorf("count must be 1..100000")
		}
	case "stop", "restart":
		peers, _ := s.Config.Peers()
		if peers[r.NodeID] == "" {
			return fmt.Errorf("unregistered node")
		}
		if r.Kind == "stop" && !r.Confirm {
			return fmt.Errorf("stop requires explicit impact confirmation")
		}
	case "stop_all":
		if !r.Confirm {
			return fmt.Errorf("stop-all requires explicit impact confirmation")
		}
	case "resume", "verify", "verify_history", "checkpoint", "export":
	case "experiment":
		if len(r.Nodes) < 1 || len(r.Nodes) > 4 || len(r.Scenarios) < 1 || len(r.Scenarios) > 5 || r.Rounds < 1 || r.Rounds > 10 || r.Count < 256 || r.Count > 100000 || r.Batch < 1 || r.Batch > 4096 || len(r.Nodes)*len(r.Scenarios)*r.Rounds > 100 {
			return fmt.Errorf("bounded experiment required: <=100 trials, rounds 1..10, entries 256..100000")
		}
		seen := map[int]bool{}
		for _, n := range r.Nodes {
			if n < 3 || n > 100 || seen[n] {
				return fmt.Errorf("nodes must be unique in 3..100")
			}
			seen[n] = true
		}
		seenScenario := map[string]bool{}
		for _, scenario := range r.Scenarios {
			if !slices.Contains([]string{"election", "failover", "catchup", "divergence", "replication"}, scenario) || seenScenario[scenario] {
				return fmt.Errorf("invalid or repeated scenario")
			}
			seenScenario[scenario] = true
		}
	default:
		return fmt.Errorf("unknown operation")
	}
	return nil
}

func (d *dashboard) operationLoop() {
	defer d.wg.Done()
	for {
		select {
		case <-d.ctx.Done():
			return
		case job := <-d.jobs:
			d.mu.Lock()
			job.op.State = "running"
			if job.op.Kind == "generate" {
				job.op.State = "submitted"
				if d.currentCheck.State == "passed" {
					d.currentCheck.State = "stale"
				}
				if d.historyCheck.State == "passed" {
					d.historyCheck.State = "stale"
				}
			}
			err := d.persistOperationsLocked()
			d.broadcastLocked()
			d.mu.Unlock()
			var result any
			if err == nil {
				result, err = d.execute(job)
			}
			d.mu.Lock()
			now := time.Now().UTC()
			job.op.EndedAt = &now
			if result != nil {
				job.op.Result = result
			}
			if job.op.State != "outcome_unknown" && job.op.State != "canceled" {
				if err != nil {
					job.op.State = "failed"
				} else {
					job.op.State = "succeeded"
				}
			}
			if err != nil {
				job.op.Error = err.Error()
			}
			d.busy = false
			d.activeCancel = ""
			if e := d.persistOperationsLocked(); e != nil {
				job.op.Error += "; receipt persistence failed: " + e.Error()
			}
			d.emitLocked(consoleEvent{Source: "control", OperationID: job.op.ID, SessionID: job.op.SessionID, Name: "operation_" + job.op.State, Message: job.op.Kind + ": " + job.op.Error})
			d.broadcastLocked()
			d.mu.Unlock()
		}
	}
}

func (d *dashboard) execute(job operationJob) (any, error) {
	r, s := job.request, job.session
	ctx, cancel := context.WithTimeout(d.ctx, 60*time.Second)
	defer cancel()
	if r.Kind == "experiment" {
		ctx = d.ctx
	}
	switch r.Kind {
	case "create_session":
		created, err := d.createSession(ctx, r.Name, r.Nodes[0], r.Batch)
		if created != nil {
			d.mu.Lock()
			job.op.SessionID = created.ID
			job.op.Generation = d.generation
			d.mu.Unlock()
		}
		return created, err
	case "select_session":
		d.mu.Lock()
		selected := d.sessions[r.SelectSession]
		d.mu.Unlock()
		err := d.activate(selected)
		if err == nil {
			d.mu.Lock()
			job.op.SessionID = selected.ID
			job.op.Generation = d.generation
			d.mu.Unlock()
		}
		return selected, err
	case "stop":
		err := d.stopNode(r.NodeID)
		return map[string]any{"node_id": r.NodeID, "exit_confirmed": err == nil}, err
	case "stop_all":
		d.mu.Lock()
		ids := []int{}
		for id := range d.processes {
			ids = append(ids, id)
		}
		d.mu.Unlock()
		var failed []string
		for _, id := range ids {
			if err := d.stopNode(id); err != nil {
				failed = append(failed, err.Error())
			}
		}
		if len(failed) > 0 {
			return nil, fmt.Errorf("%s", strings.Join(failed, "; "))
		}
		return map[string]any{"stopped_nodes": ids}, nil
	case "restart":
		err := d.startNode(ctx, s, r.NodeID)
		return map[string]any{"node_id": r.NodeID, "endpoint_ready": err == nil, "catchup_verified": false}, err
	case "resume":
		return map[string]string{"message": "原配置节点已启动；追赶需另行校验"}, d.resume(ctx, s)
	case "generate":
		reply, err := wire.SubmitGenerated(ctx, s.Config, r.Count, r.Seed, time.Now().Add(60*time.Second))
		d.mu.Lock()
		if !errors.Is(err, wire.ErrOutcomeUnknown) {
			a, c := reply.Accepted, reply.Committed
			job.op.Accepted = &a
			job.op.Committed = &c
		} else {
			job.op.State = "outcome_unknown"
			if reply.Accepted {
				a := true
				job.op.Accepted = &a
			}
		}
		if reply.Committed && err == nil {
			d.target = reply.LastIndex
		}
		persistErr := d.persistEvidenceLocked()
		d.mu.Unlock()
		if err == nil {
			err = persistErr
		}
		return reply, err
	case "verify", "verify_history", "checkpoint":
		return d.verify(ctx, s, r.Kind)
	case "experiment":
		return d.runExperiment(ctx, job)
	case "export":
		return d.exportEvidence(job)
	}
	return nil, fmt.Errorf("unsupported operation")
}

func (d *dashboard) persistEvidenceLocked() error {
	if d.active == nil {
		return nil
	}
	dir := filepath.Join(d.opts.Root, d.active.ID)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	return writeJSONFile(filepath.Join(dir, "evidence.json"), map[string]any{"checkpoint": d.checkpoint, "target": d.target})
}

func (d *dashboard) verify(ctx context.Context, s *session, kind string) (any, error) {
	d.mu.Lock()
	saved := d.checkpoint
	generation := d.generation
	d.mu.Unlock()
	target := 0
	if kind == "verify_history" {
		if saved == nil {
			return nil, fmt.Errorf("no saved historical checkpoint")
		}
		target = saved.Index
	}
	v := verification{State: "running", Kind: "current", At: time.Now().UTC(), Target: target}
	if kind == "verify_history" {
		v.Kind = "history"
	}
	d.mu.Lock()
	if v.Kind == "current" {
		d.currentCheck = v
	} else {
		d.historyCheck = v
	}
	d.broadcastLocked()
	d.mu.Unlock()
	d.monitorRPCs.Add(uint64(len(s.Config.Nodes)))
	states := wire.QueryStatusesContext(ctx, s.Config, wire.StatusArgs{TargetIndex: target}, time.Now().Add(10*time.Second))
	v.Nodes = states
	var err error
	partial := false
	peers, _ := s.Config.Peers()
	identity, _ := config.FixedIdentity(s.Config.ClusterID, peers)
	signature := []any{}
	for i := range states {
		st := &states[i]
		st.ProcessID = 0
		signature = append(signature, []any{st.ID, st.Error, st.InstanceID, st.Term, st.Revision, st.CommittedHash})
		if st.Error != "" {
			partial = partial || st.InstanceID == ""
			err = fmt.Errorf("node %d: %s", st.ID, st.Error)
		} else if st.MembershipHash != identity.MembershipHash() {
			err = fmt.Errorf("node %d membership mismatch", st.ID)
		}
	}
	if err == nil {
		if kind == "verify_history" {
			for _, st := range states {
				if !st.TargetAvailable || st.TargetIndex != saved.Index || st.TargetHash != saved.Hash || st.TargetX != saved.X {
					err = fmt.Errorf("node %d does not match saved index/hash/x", st.ID)
					break
				}
			}
		} else {
			err = wire.VerifyStatuses(states, 0)
			if err == nil && kind == "checkpoint" && states[0].CommitIndex == 0 {
				err = fmt.Errorf("wait for at least one committed entry before saving a fixed checkpoint")
			}
		}
	}
	v.Fingerprint = digestJSON(signature)
	v.State = "passed"
	if err != nil {
		v.State = "failed"
		v.Error = err.Error()
		if partial {
			v.State = "partial_unreachable"
		}
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.active == nil || d.active.ID != s.ID || d.generation != generation {
		return nil, fmt.Errorf("session changed during verification")
	}
	v.CompletedAt = time.Now().UTC()
	if v.State == "passed" && d.snap.CompletedAt.After(v.At) && d.snap.Fingerprint != v.Fingerprint {
		v.State = "stale"
		v.Error = "a newer shared observation differs; this pass is historical, not current"
	}
	if v.Kind == "current" {
		d.currentCheck = v
	} else {
		d.historyCheck = v
	}
	if kind == "checkpoint" && err == nil {
		st := states[0]
		d.checkpoint = &checkpoint{Index: st.CommitIndex, Hash: st.CommittedHash, X: st.X, SavedAt: time.Now().UTC()}
		d.target = st.CommitIndex
		if e := d.persistEvidenceLocked(); e != nil {
			return nil, e
		}
	}
	return v, err
}

func (d *dashboard) runExperiment(ctx context.Context, job operationJob) (any, error) {
	return nil, fmt.Errorf("experiment runner not configured")
}
func (d *dashboard) exportEvidence(job operationJob) (any, error) {
	return nil, fmt.Errorf("evidence exporter not configured")
}
