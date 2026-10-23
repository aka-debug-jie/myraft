package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

type ownedProcess struct {
	cmd       *exec.Cmd
	path      string
	args      []string
	startedAt time.Time
	running   bool
	done      chan struct{}
	exitError string
}

func (d *dashboard) loadSessions() error {
	entries, err := os.ReadDir(d.opts.Root)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		b, err := os.ReadFile(filepath.Join(d.opts.Root, entry.Name(), "session.json"))
		if os.IsNotExist(err) {
			continue
		}
		if err != nil {
			return err
		}
		var s session
		if err := json.Unmarshal(b, &s); err != nil {
			return err
		}
		if s.ID != entry.Name() {
			return fmt.Errorf("stored session directory identity mismatch")
		}
		if _, err := s.Config.Peers(); err != nil {
			return err
		}
		d.sessions[s.ID] = &s
	}
	var saved struct {
		ID string `json:"id"`
	}
	if b, err := os.ReadFile(filepath.Join(d.opts.Root, "active.json")); err == nil {
		if err = json.Unmarshal(b, &saved); err != nil {
			return err
		}
		d.active = d.sessions[saved.ID]
	}
	return nil
}

func (d *dashboard) stopNode(id int) error {
	d.mu.Lock()
	p := d.processes[id]
	if p == nil {
		d.mu.Unlock()
		return fmt.Errorf("node is not owned by this controller process")
	}
	// Live Go process handles are retained; no PID is accepted or reclaimed from disk.
	if p.cmd.Path != p.path || !slices.Equal(p.cmd.Args, p.args) || p.startedAt.IsZero() {
		d.mu.Unlock()
		return fmt.Errorf("owned process identity changed")
	}
	if !p.running {
		d.mu.Unlock()
		return nil
	}
	d.mu.Unlock()
	if err := p.cmd.Process.Kill(); err != nil && err != os.ErrProcessDone {
		return err
	}
	select {
	case <-p.done:
		return nil
	case <-time.After(5 * time.Second):
		return fmt.Errorf("owned node exit not confirmed")
	}
}
func (d *dashboard) stopOwned() {
	d.mu.Lock()
	ids := make([]int, 0, len(d.processes))
	for id := range d.processes {
		ids = append(ids, id)
	}
	d.mu.Unlock()
	for _, id := range ids {
		d.stopNode(id)
	}
}

func fileSHA(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
func nodeExecutable() string {
	if runtime.GOOS == "windows" {
		return "raft-node.exe"
	}
	return "raft-node"
}
func (d *dashboard) hasLiveOwnedLocked() bool {
	for _, p := range d.processes {
		if p.running {
			return true
		}
	}
	return false
}

func (d *dashboard) activate(s *session) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.hasLiveOwnedLocked() {
		return fmt.Errorf("stop current owned nodes before switching sessions")
	}
	check, target, err := d.readEvidence(s)
	if err != nil {
		return err
	}
	if err := writeJSONFile(filepath.Join(d.opts.Root, "active.json"), map[string]string{"id": s.ID}); err != nil {
		return err
	}
	d.active = s
	d.generation++
	d.processes = map[int]*ownedProcess{}
	d.snap = snapshot{}
	d.events = nil
	d.eventCursors = map[int]eventCursor{}
	d.checkpoint = check
	d.target = target
	d.currentCheck = verification{State: "not_run", Kind: "current"}
	d.historyCheck = verification{State: "not_run", Kind: "history"}
	d.emitLocked(consoleEvent{Source: "control", Name: "session_selected", Message: s.Name})
	d.broadcastLocked()
	return nil
}

func (d *dashboard) readEvidence(s *session) (*checkpoint, int, error) {
	b, err := os.ReadFile(filepath.Join(d.opts.Root, s.ID, "evidence.json"))
	if os.IsNotExist(err) {
		return nil, 0, nil
	}
	if err != nil {
		return nil, 0, err
	}
	var saved struct {
		Checkpoint *checkpoint `json:"checkpoint"`
		Target     int         `json:"target"`
	}
	if err := json.Unmarshal(b, &saved); err != nil {
		return nil, 0, err
	}
	return saved.Checkpoint, saved.Target, nil
}

func (d *dashboard) createSession(ctx context.Context, name string, count, batch int) (*session, error) {
	d.mu.Lock()
	live := d.hasLiveOwnedLocked()
	d.mu.Unlock()
	if live {
		return nil, fmt.Errorf("stop current owned nodes first; existing data is retained")
	}
	s := &session{ID: config.NewClusterID(), Name: name, Managed: true, BatchSize: batch, CreatedAt: time.Now().UTC()}
	s.Config.ClusterID = config.NewClusterID()
	var listeners []net.Listener
	defer func() {
		for _, l := range listeners {
			l.Close()
		}
	}()
	for i := 1; i <= count; i++ {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			return nil, err
		}
		listeners = append(listeners, l)
		s.Config.Nodes = append(s.Config.Nodes, config.Node{ID: i, Addr: l.Addr().String()})
	}
	dir := filepath.Join(d.opts.Root, s.ID)
	if err := os.Mkdir(dir, 0700); err != nil {
		return nil, err
	}
	source, err := os.Open(d.opts.NodeBinary)
	if err != nil {
		return nil, err
	}
	defer source.Close()
	exe := filepath.Join(dir, nodeExecutable())
	out, err := os.OpenFile(exe, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0700)
	if err != nil {
		return nil, err
	}
	_, err = io.Copy(out, source)
	if err == nil {
		err = out.Sync()
	}
	ce := out.Close()
	if err == nil {
		err = ce
	}
	if err != nil {
		return nil, err
	}
	s.BinarySHA256, err = fileSHA(exe)
	if err != nil {
		return nil, err
	}
	if err = s.Config.Save(filepath.Join(dir, "nodes.json")); err != nil {
		return nil, err
	}
	if err = writeJSONFile(filepath.Join(dir, "session.json"), s); err != nil {
		return nil, err
	}
	d.mu.Lock()
	d.sessions[s.ID] = s
	d.mu.Unlock()
	if err = d.activate(s); err != nil {
		return nil, err
	}
	for _, l := range listeners {
		l.Close()
	}
	if err = d.resume(ctx, s); err != nil {
		d.stopOwned()
		return s, err
	}
	return s, nil
}

func (d *dashboard) startNode(ctx context.Context, s *session, id int) error {
	if !s.Managed {
		return fmt.Errorf("session is not managed")
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	peers, _ := s.Config.Peers()
	if peers[id] == "" {
		return fmt.Errorf("unregistered node")
	}
	d.mu.Lock()
	p := d.processes[id]
	running := p != nil && p.running
	d.mu.Unlock()
	if running {
		return fmt.Errorf("node already owned and running")
	}
	dir := filepath.Join(d.opts.Root, s.ID)
	configPath := filepath.Join(dir, "nodes.json")
	disk, err := config.Load(configPath)
	if err != nil {
		return err
	}
	if digestJSON(disk) != digestJSON(s.Config) {
		return fmt.Errorf("stored session configuration changed; stop remains available for owned nodes")
	}
	exe := filepath.Join(dir, nodeExecutable())
	digest, err := fileSHA(exe)
	if err != nil || digest != s.BinarySHA256 {
		return fmt.Errorf("managed executable identity changed")
	}
	args := []string{"-id", strconv.Itoa(id), "-config", configPath, "-data-dir", filepath.Join(dir, "data"), "-log-dir", filepath.Join(dir, "logs"), "-batch-size", strconv.Itoa(s.BatchSize)}
	output, err := os.OpenFile(filepath.Join(dir, fmt.Sprintf("process-%d.log", id)), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	cmd := exec.Command(exe, args...)
	cmd.Stdout = output
	cmd.Stderr = output
	// Older session binaries ignore the opt-out; adding a required CLI flag would prevent their restart.
	cmd.Env = append(os.Environ(), "GOMAXPROCS=1", "MYRAFT_NO_CONSOLE_TITLE=1")
	if err = cmd.Start(); err != nil {
		output.Close()
		return err
	}
	output.Close()
	p = &ownedProcess{cmd: cmd, path: exe, args: append([]string(nil), cmd.Args...), startedAt: time.Now().UTC(), running: true, done: make(chan struct{})}
	d.mu.Lock()
	d.processes[id] = p
	d.emitLocked(consoleEvent{Source: "control", SessionID: s.ID, NodeID: id, Name: "process_started", Message: "自有进程已启动，尚未确认节点可达"})
	d.mu.Unlock()
	go func() {
		err := cmd.Wait()
		d.mu.Lock()
		p.running = false
		if err != nil {
			p.exitError = err.Error()
		}
		d.emitLocked(consoleEvent{Source: "control", SessionID: s.ID, NodeID: id, Name: "process_exited", Message: p.exitError})
		d.broadcastLocked()
		close(p.done)
		d.mu.Unlock()
	}()
	ready := false
	// Cleanup is installed only after this invocation created a new owned process.
	defer func() {
		if !ready {
			d.stopNode(id)
		}
	}()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		select {
		case <-p.done:
			return fmt.Errorf("node exited before readiness: %s", p.exitError)
		default:
		}
		var status wire.StatusReply
		if err := wire.CallContext(ctx, peers[id], "RaftNode.Status", &wire.StatusArgs{Summary: true}, &status, 200*time.Millisecond); err == nil && status.ID == id && status.ClusterID == s.Config.ClusterID && status.ProcessID == cmd.Process.Pid && status.Error == "" {
			ready = true
			return nil
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(50 * time.Millisecond):
		}
	}
	return fmt.Errorf("node endpoint not ready within 5s")
}

func (d *dashboard) resume(ctx context.Context, s *session) error {
	if !s.Managed {
		return fmt.Errorf("cannot resume an attached external session")
	}
	for _, node := range s.Config.Nodes {
		d.mu.Lock()
		p := d.processes[node.ID]
		running := p != nil && p.running
		d.mu.Unlock()
		if !running {
			if err := d.startNode(ctx, s, node.ID); err != nil {
				return err
			}
		}
	}
	return nil
}
