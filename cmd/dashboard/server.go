package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

type settings struct {
	Root, NodeBinary, Source, Python, Config, Host string
	AllowControl                                   bool
	Interval                                       time.Duration
}
type session struct {
	ID           string        `json:"id"`
	Name         string        `json:"name"`
	Config       config.Config `json:"config"`
	Managed      bool          `json:"managed"`
	BinarySHA256 string        `json:"binary_sha256,omitempty"`
	BatchSize    int           `json:"batch_size"`
	CreatedAt    time.Time     `json:"created_at"`
}
type nodeSample struct {
	ID         int               `json:"id"`
	Reachable  bool              `json:"reachable"`
	IdentityOK bool              `json:"identity_ok"`
	Owned      bool              `json:"owned"`
	SampledAt  time.Time         `json:"sampled_at"`
	Status     *wire.StatusReply `json:"status"`
	Error      string            `json:"error,omitempty"`
}
type snapshot struct {
	SessionID   string       `json:"session_id"`
	Generation  uint64       `json:"generation"`
	Seq         uint64       `json:"seq"`
	StartedAt   time.Time    `json:"started_at"`
	CompletedAt time.Time    `json:"completed_at"`
	Nodes       []nodeSample `json:"nodes"`
	Fingerprint string       `json:"fingerprint"`
	MonitorRPCs uint64       `json:"monitor_rpcs"`
}
type consoleEvent struct {
	Seq         uint64      `json:"seq"`
	ReceivedAt  time.Time   `json:"received_at"`
	Source      string      `json:"source"`
	SessionID   string      `json:"session_id"`
	NodeID      int         `json:"node_id,omitempty"`
	OperationID string      `json:"operation_id,omitempty"`
	Name        string      `json:"name"`
	Message     string      `json:"message"`
	NodeEvent   *wire.Event `json:"node_event,omitempty"`
}
type checkpoint struct {
	Index   int       `json:"index"`
	Hash    string    `json:"hash"`
	X       int64     `json:"x"`
	SavedAt time.Time `json:"saved_at"`
}
type verification struct {
	State       string             `json:"state"`
	Kind        string             `json:"kind"`
	Fingerprint string             `json:"fingerprint"`
	At          time.Time          `json:"at"`
	CompletedAt time.Time          `json:"completed_at"`
	Error       string             `json:"error,omitempty"`
	Target      int                `json:"target"`
	Nodes       []wire.StatusReply `json:"nodes,omitempty"`
}
type operation struct {
	ID         string     `json:"id"`
	SessionID  string     `json:"session_id"`
	Generation uint64     `json:"generation"`
	Kind       string     `json:"kind"`
	State      string     `json:"state"`
	CreatedAt  time.Time  `json:"created_at"`
	EndedAt    *time.Time `json:"ended_at,omitempty"`
	Accepted   *bool      `json:"accepted"`
	Committed  *bool      `json:"committed"`
	Result     any        `json:"result,omitempty"`
	Error      string     `json:"error,omitempty"`
}
type subscription struct {
	notify  chan struct{}
	dropped uint64
}

type eventCursor struct {
	Instance string
	Seq      uint64
}
type dashboard struct {
	mu                         sync.Mutex
	opts                       settings
	ctx                        context.Context
	cancel                     context.CancelFunc
	closeOnce                  sync.Once
	wg                         sync.WaitGroup
	csrf                       string
	controllerID               string
	control                    bool
	sessions                   map[string]*session
	active                     *session
	generation                 uint64
	snap                       snapshot
	events                     []consoleEvent
	eventSeq                   uint64
	eventCursors               map[int]eventCursor
	subs                       map[*subscription]bool
	operations                 []*operation
	currentCheck, historyCheck verification
	checkpoint                 *checkpoint
	target                     int
	monitorRPCs                atomic.Uint64
	processes                  map[int]*ownedProcess
	busy                       bool
	jobs                       chan operationJob
	exports                    map[string]string
	activeCancel               string
}

func newDashboard(o settings) (*dashboard, error) {
	if o.Interval < 200*time.Millisecond {
		return nil, fmt.Errorf("poll interval must be >=200ms")
	}
	if err := os.MkdirAll(o.Root, 0700); err != nil {
		return nil, err
	}
	ctx, cancel := context.WithCancel(context.Background())
	d := &dashboard{opts: o, ctx: ctx, cancel: cancel, csrf: config.NewClusterID() + config.NewClusterID(), sessions: map[string]*session{}, generation: 1, subs: map[*subscription]bool{}, processes: map[int]*ownedProcess{}, jobs: make(chan operationJob, 1), exports: map[string]string{}, currentCheck: verification{State: "not_run", Kind: "current"}, historyCheck: verification{State: "not_run", Kind: "history"}}
	d.controllerID = config.NewClusterID()
	d.eventCursors = map[int]eventCursor{}
	if err := d.loadSessions(); err != nil {
		cancel()
		return nil, err
	}
	if err := d.loadOperations(); err != nil {
		cancel()
		return nil, err
	}
	if o.Config != "" {
		c, err := config.Load(o.Config)
		if err != nil {
			cancel()
			return nil, err
		}
		peers, _ := c.Peers()
		if _, err := config.FixedIdentity(c.ClusterID, peers); err != nil {
			cancel()
			return nil, err
		}
		var s *session
		for _, existing := range d.sessions {
			if digestJSON(existing.Config) == digestJSON(c) {
				s = existing
				break
			}
		}
		if s == nil {
			s = &session{ID: config.NewClusterID(), Name: "已登记的只读集群", Config: c, CreatedAt: time.Now().UTC()}
			dir := filepath.Join(o.Root, s.ID)
			if err := os.MkdirAll(dir, 0700); err != nil {
				cancel()
				return nil, err
			}
			if err := writeJSONFile(filepath.Join(dir, "session.json"), s); err != nil {
				cancel()
				return nil, err
			}
		}
		d.active = s
		d.sessions[s.ID] = s
	}
	if d.active != nil {
		var err error
		d.checkpoint, d.target, err = d.readEvidence(d.active)
		if err != nil {
			cancel()
			return nil, err
		}
		if err := writeJSONFile(filepath.Join(o.Root, "active.json"), map[string]string{"id": d.active.ID}); err != nil {
			cancel()
			return nil, err
		}
	}
	d.wg.Add(2)
	go d.collectLoop()
	go d.operationLoop()
	return d, nil
}

func (d *dashboard) Close() {
	d.closeOnce.Do(func() {
		d.cancel()
		d.mu.Lock()
		cancelFile := d.activeCancel
		d.mu.Unlock()
		if cancelFile != "" {
			os.WriteFile(cancelFile, []byte("cancel\n"), 0600)
		}
		d.wg.Wait()
		d.stopOwned()
	})
}

func (d *dashboard) emitLocked(e consoleEvent) {
	d.eventSeq++
	e.Seq = d.eventSeq
	e.ReceivedAt = time.Now().UTC()
	if e.SessionID == "" && d.active != nil {
		e.SessionID = d.active.ID
	}
	d.events = append(d.events, e)
	if len(d.events) > 512 {
		copy(d.events, d.events[len(d.events)-512:])
		d.events = d.events[:512]
	}
}
func (d *dashboard) broadcastLocked() {
	for sub := range d.subs {
		select {
		case sub.notify <- struct{}{}:
		default:
			sub.dropped++
		}
	}
}
func digestJSON(v any) string {
	b, _ := json.Marshal(v)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func writeJSONFile(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".state-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	_, err = f.Write(append(b, '\n'))
	if err == nil {
		err = f.Sync()
	}
	ce := f.Close()
	if err == nil {
		err = ce
	}
	if err != nil {
		return err
	}
	return os.Rename(f.Name(), path)
}
