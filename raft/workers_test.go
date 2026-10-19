package raft

import (
	"io"
	"log"
	wire "myraft/rpc"
	"runtime"
	"strings"
	"testing"
	"time"
)

func preElectionNodes(t testing.TB, count int) int {
	t.Helper()
	peers, dir := testPeers(t, count), t.TempDir()
	before := runtime.NumGoroutine()
	for id := 1; id <= count; id++ {
		n, err := NewNode(Options{ClusterID: "worker-test", ID: id, Peers: peers, DataDir: dir, Logger: log.New(io.Discard, "", 0), ElectionMin: time.Hour, ElectionJitter: time.Hour})
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(n.Stop)
		if err = n.Start(); err != nil {
			t.Fatal(err)
		}
	}
	return runtime.NumGoroutine() - before
}

func TestFollowersDoNotStartPeerWorkers(t *testing.T) {
	begin := time.Now()
	added := preElectionNodes(t, 100)
	t.Logf("100 pre-election nodes: additional goroutines=%d startup=%s", added, time.Since(begin))
	// Each node needs output, accept and election loops; no per-peer idle loops.
	if added > 400 {
		t.Fatalf("idle followers started peer workers: %d goroutines", added)
	}
}

func TestReplicationWorkersReusedAcrossTerms(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	nodes := map[int]*Node{}
	for id := 1; id <= 3; id++ {
		n := testNode(t, id, peers, dir)
		n.options.ElectionMin, n.options.ElectionJitter = time.Hour, time.Hour
		if err := n.Start(); err != nil {
			t.Fatal(err)
		}
		nodes[id] = n
	}
	leader := nodes[1]
	for round := 0; round < 3; round++ {
		leader.mu.Lock()
		if round > 0 {
			if err := leader.followHigherTermLocked(leader.term + 1); err != nil {
				leader.mu.Unlock()
				t.Fatal(err)
			}
		}
		leader.startElectionLocked()
		leader.mu.Unlock()
		if id, _ := awaitLeader(t, nodes); id != 1 {
			t.Fatalf("unexpected leader %d", id)
		}
		var reply wire.GenerateReply
		if err := leader.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 3, Seed: 42, TimeoutMS: 1000}, &reply); err != nil || !reply.Committed {
			t.Fatalf("write failed %+v: %v", reply, err)
		}
		stack := make([]byte, 1<<20)
		size := runtime.Stack(stack, true)
		if workers := strings.Count(string(stack[:size]), "myraft/raft.(*Node).heartbeatLoop("); workers != 2 {
			t.Fatalf("term %d: got %d workers", reply.Term, workers)
		}
	}
}

func TestFirstLeadershipRacingStop(t *testing.T) {
	for i := 0; i < 20; i++ {
		n := testNode(t, 1, testPeers(t, 3), t.TempDir())
		n.options.ElectionMin = time.Hour
		if err := n.Start(); err != nil {
			t.Fatal(err)
		}
		done := make(chan struct{})
		go func() {
			n.mu.Lock()
			if !n.stopped {
				n.startElectionLocked()
				n.handleVoteReplyLocked(2, n.term, wire.VoteReply{Term: n.term, VoteGranted: true})
			}
			n.mu.Unlock()
			close(done)
		}()
		n.Stop()
		<-done
		n.mu.Lock()
		n.startReplicationLocked()
		n.mu.Unlock()
	}
}

func TestStartAfterLocalLeaderSetup(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 3), t.TempDir())
	n.mu.Lock()
	n.startElectionLocked()
	n.handleVoteReplyLocked(2, n.term, wire.VoteReply{Term: n.term, VoteGranted: true})
	if n.replicationStarted {
		n.mu.Unlock()
		t.Fatal("workers started before listener")
	}
	n.mu.Unlock()
	if err := n.Start(); err != nil {
		t.Fatal(err)
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	if !n.replicationStarted {
		t.Fatal("leader Start omitted workers")
	}
}
