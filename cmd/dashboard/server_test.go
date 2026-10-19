package main

import (
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	stdrpc "net/rpc"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

type consoleRPC struct {
	calls, full        atomic.Int64
	identity           config.Identity
	blockLogs, entered chan struct{}
}

func (p *consoleRPC) Status(args *wire.StatusArgs, r *wire.StatusReply) error {
	p.calls.Add(1)
	if !args.Summary {
		p.full.Add(1)
	}
	*r = wire.StatusReply{ID: 1, ClusterID: p.identity.ClusterID, MembershipHash: p.identity.MembershipHash(), InstanceID: "instance", State: "Leader", LeaderID: 1, Term: 1, CommittedHash: "hash", LogHash: "hash"}
	return nil
}
func (p *consoleRPC) LogRange(args *wire.LogRangeArgs, r *wire.LogRangeReply) error {
	if p.entered != nil {
		p.entered <- struct{}{}
		<-p.blockLogs
	}
	*r = wire.LogRangeReply{NodeID: 1, ClusterID: p.identity.ClusterID, MembershipHash: p.identity.MembershipHash(), From: args.From, Next: args.From}
	return nil
}

func testConsole(t *testing.T) (*dashboard, *httptest.Server, *consoleRPC) {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	c := config.Config{ClusterID: "console-test", Nodes: []config.Node{{ID: 1, Addr: l.Addr().String()}}}
	peers, _ := c.Peers()
	identity, _ := config.FixedIdentity(c.ClusterID, peers)
	p := &consoleRPC{identity: identity}
	rpcServer := stdrpc.NewServer()
	rpcServer.RegisterName("RaftNode", p)
	go func() {
		for {
			conn, e := l.Accept()
			if e != nil {
				return
			}
			go func() { defer conn.Close(); rpcServer.ServeConn(conn) }()
		}
	}()
	t.Cleanup(func() { l.Close() })
	dir := t.TempDir()
	path := filepath.Join(dir, "nodes.json")
	if err = c.Save(path); err != nil {
		t.Fatal(err)
	}
	d, err := newDashboard(settings{Root: filepath.Join(dir, "dashboard"), Config: path, Interval: time.Hour})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewUnstartedServer(d.handler())
	d.opts.Host = server.Listener.Addr().String()
	server.Start()
	t.Cleanup(func() { d.Close(); server.Close() })
	until := time.Now().Add(time.Second)
	for time.Now().Before(until) {
		d.mu.Lock()
		ready := !d.snap.CompletedAt.IsZero()
		d.mu.Unlock()
		if ready {
			return d, server, p
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("collector not ready")
	return nil, nil, nil
}

func TestHTTPHostOriginAndMethodBoundary(t *testing.T) {
	d, s, _ := testConsole(t)
	for _, tc := range []struct {
		method, path, host, origin, token string
		want                              int
	}{
		{"GET", "/api/session", "evil.invalid", "", "", 403},
		{"GET", "/api/session", "", "http://evil.invalid", "", 403},
		{"POST", "/api/operations", "", "", "", 403},
		{"POST", "/api/operations", "", "http://" + d.opts.Host, "wrong", 403},
		{"GET", "/api/session", "", "", "", 200},
	} {
		r, _ := http.NewRequest(tc.method, s.URL+tc.path, strings.NewReader(`{"kind":"stop"}`))
		if tc.host != "" {
			r.Host = tc.host
		}
		r.Header.Set("Origin", tc.origin)
		r.Header.Set("X-CSRF-Token", tc.token)
		res, err := s.Client().Do(r)
		if err != nil {
			t.Fatal(err)
		}
		io.Copy(io.Discard, res.Body)
		res.Body.Close()
		if res.StatusCode != tc.want {
			t.Fatalf("%+v status=%d", tc, res.StatusCode)
		}
		if res.Header.Get("Access-Control-Allow-Origin") != "" {
			t.Fatal("unexpected CORS")
		}
	}
}

func TestSharedCollectorDoesNotMultiplyRPCWithBrowsers(t *testing.T) {
	d, s, p := testConsole(t)
	for _, clients := range []int{1, 5, 10} {
		before := p.calls.Load()
		var responses []*http.Response
		for i := 0; i < clients; i++ {
			r, err := s.Client().Get(s.URL + "/api/events")
			if err != nil {
				t.Fatal(err)
			}
			responses = append(responses, r)
		}
		for i := 0; i < clients; i++ {
			r, err := s.Client().Get(s.URL + "/api/snapshot")
			if err != nil {
				t.Fatal(err)
			}
			io.Copy(io.Discard, r.Body)
			r.Body.Close()
		}
		if p.calls.Load() != before {
			t.Fatal("browser triggered node polling")
		}
		d.collectRound()
		if p.calls.Load() != before+1 || p.full.Load() != 0 {
			t.Fatal("collector did not share one Summary")
		}
		for _, r := range responses {
			r.Body.Close()
		}
	}
}

func TestEventBoundsAndGapAreVisible(t *testing.T) {
	d, _, _ := testConsole(t)
	sub := &subscription{notify: make(chan struct{}, 1)}
	d.mu.Lock()
	d.subs[sub] = true
	for i := 0; i < 600; i++ {
		d.emitLocked(consoleEvent{Source: "observation", Name: "test"})
		d.broadcastLocked()
	}
	frame := d.frameLocked(0, sub.dropped)
	d.mu.Unlock()
	b, _ := json.Marshal(frame)
	var decoded struct {
		Gap     bool           `json:"gap"`
		Dropped int            `json:"stream_dropped"`
		Events  []consoleEvent `json:"events"`
	}
	json.Unmarshal(b, &decoded)
	if !decoded.Gap || decoded.Dropped != 599 || len(decoded.Events) != 512 || len(sub.notify) != 1 {
		t.Fatalf("unbounded or hidden loss: %+v", decoded)
	}
}

func TestLogsRejectStaleSessionAndUnregisteredNode(t *testing.T) {
	d, s, _ := testConsole(t)
	d.mu.Lock()
	id, gen := d.active.ID, d.generation
	d.mu.Unlock()
	for _, path := range []string{"/api/nodes/1/logs?from=1&session_id=old&generation=1", "/api/nodes/999/logs?from=1&session_id=" + id + "&generation=1", "/api/nodes/1/logs?from=1&limit=257&session_id=" + id + "&generation=1"} {
		res, err := s.Client().Get(s.URL + path)
		if err != nil {
			t.Fatal(err)
		}
		res.Body.Close()
		if res.StatusCode == 200 {
			t.Fatal("invalid request accepted")
		}
	}
	if gen != 1 {
		t.Fatal("unexpected generation")
	}
}
