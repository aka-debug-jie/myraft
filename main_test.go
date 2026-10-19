package main

import (
	"net"
	stdrpc "net/rpc"
	"sync/atomic"
	"testing"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

type clientTestServer struct{ calls atomic.Int32 }

func (s *clientTestServer) Status(_ *wire.StatusArgs, r *wire.StatusReply) error {
	*r = wire.StatusReply{ClusterID: "test-client", ID: 7, State: "Leader", LeaderID: 7, Term: 1, LogHash: "hash", CommittedHash: "hash"}
	return nil
}
func (s *clientTestServer) Generate(_ *wire.GenerateArgs, r *wire.GenerateReply) error {
	s.calls.Add(1)
	time.Sleep(150 * time.Millisecond)
	r.Accepted = true
	r.Committed = true
	return nil
}
func serveClientTest(t *testing.T) (string, *clientTestServer) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := stdrpc.NewServer()
	receiver := new(clientTestServer)
	if err = server.RegisterName("RaftNode", receiver); err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() { defer conn.Close(); server.ServeConn(conn) }()
		}
	}()
	t.Cleanup(func() { listener.Close(); <-done })
	return listener.Addr().String(), receiver
}
func TestStatusBindsConfiguredIdentity(t *testing.T) {
	addr, _ := serveClientTest(t)
	c := config.Config{ClusterID: "test-client", Nodes: []config.Node{{ID: 7, Addr: addr}, {ID: 8, Addr: addr}}}
	states := queryAll(c, 0, time.Now().Add(time.Second))
	if states[0].ID != 7 || states[0].Error != "" || states[1].ID != 8 || states[1].Error == "" {
		t.Fatalf("unexpected identities %+v", states)
	}
	if verifyStatuses(states, 0) == nil {
		t.Fatal("duplicate endpoint counted twice")
	}
}
func TestUncertainSubmissionNotRetried(t *testing.T) {
	addr, receiver := serveClientTest(t)
	c := config.Config{ClusterID: "test-client", Nodes: []config.Node{{ID: 7, Addr: addr}}}
	reply, err := submitGenerated(c, map[int]string{7: addr}, 1, 42, time.Now().Add(70*time.Millisecond))
	if err == nil || reply.Committed || receiver.calls.Load() != 1 {
		t.Fatalf("reply %+v err %v calls %d", reply, err, receiver.calls.Load())
	}
	time.Sleep(170 * time.Millisecond)
	if receiver.calls.Load() != 1 {
		t.Fatal("non-idempotent request retried")
	}
}

func TestSubmissionRequiresExplicitClusterIdentity(t *testing.T) {
	addr, receiver := serveClientTest(t)
	c := config.Config{Nodes: []config.Node{{ID: 7, Addr: addr}}}
	if _, err := submitGenerated(c, map[int]string{7: addr}, 1, 42, time.Now().Add(time.Second)); err == nil || receiver.calls.Load() != 0 {
		t.Fatal("write adopted remote identity")
	}
}
