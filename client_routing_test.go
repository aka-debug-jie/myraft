package main

import (
	"myraft/config"
	wire "myraft/rpc"
	"net"
	stdrpc "net/rpc"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type ProbeRPC struct {
	ID       int
	Slow     bool
	Calls    atomic.Int32
	Full     atomic.Int32
	Shutdown chan struct{}
}

func (p *ProbeRPC) Status(a *wire.StatusArgs, r *wire.StatusReply) error {
	if !a.Summary {
		p.Full.Add(1)
	}
	if p.Slow {
		select {
		case <-time.After(1500 * time.Millisecond):
		case <-p.Shutdown:
		}
	}
	*r = wire.StatusReply{ClusterID: "test-client", ID: p.ID, State: "Follower", LeaderID: 1, Term: 1}
	if p.ID == 1 {
		r.State = "Leader"
	}
	return nil
}
func (p *ProbeRPC) Generate(a *wire.GenerateArgs, r *wire.GenerateReply) error {
	p.Calls.Add(1)
	*r = wire.GenerateReply{Accepted: true, Committed: true, Commands: a.Count}
	return nil
}
func serveProbe(t *testing.T, p *ProbeRPC) string {
	t.Helper()
	l, e := net.Listen("tcp", "127.0.0.1:0")
	if e != nil {
		t.Fatal(e)
	}
	p.Shutdown = make(chan struct{})
	s := stdrpc.NewServer()
	s.RegisterName("RaftNode", p)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			c, e := l.Accept()
			if e != nil {
				return
			}
			wg.Add(1)
			go func() { defer wg.Done(); defer c.Close(); s.ServeConn(c) }()
		}
	}()
	t.Cleanup(func() { l.Close(); close(p.Shutdown); wg.Wait() })
	return l.Addr().String()
}
func TestSlowFollowerDoesNotDelaySubmission(t *testing.T) {
	a, b, c := &ProbeRPC{ID: 1}, &ProbeRPC{ID: 2}, &ProbeRPC{ID: 3, Slow: true}
	nodes := []config.Node{{ID: 1, Addr: serveProbe(t, a)}, {ID: 2, Addr: serveProbe(t, b)}, {ID: 3, Addr: serveProbe(t, c)}}
	conf := config.Config{ClusterID: "test-client", Nodes: nodes}
	peers, _ := conf.Peers()
	begin := time.Now()
	r, e := submitGenerated(conf, peers, 3, 42, time.Now().Add(700*time.Millisecond))
	elapsed := time.Since(begin)
	if e != nil || !r.Committed || a.Calls.Load() != 1 || elapsed >= 650*time.Millisecond {
		t.Fatalf("slow follower delayed request: %+v %v calls=%d elapsed=%s", r, e, a.Calls.Load(), elapsed)
	}
	if a.Full.Load()+b.Full.Load()+c.Full.Load() != 0 {
		t.Fatal("leader discovery requested full hashes")
	}

}
