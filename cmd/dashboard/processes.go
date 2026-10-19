package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"time"
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

type operationJob struct{ op *operation }

func (d *dashboard) operationLoop() { defer d.wg.Done(); <-d.ctx.Done() }
