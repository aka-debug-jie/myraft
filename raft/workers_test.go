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
				n.handleVoteReplyLocked(2, n.term, wire.VoteReply{NodeID: 2, ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, Term: n.term, VoteGranted: true})
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
	n.handleVoteReplyLocked(2, n.term, wire.VoteReply{NodeID: 2, ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, Term: n.term, VoteGranted: true})
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

func TestLiveLeaderRotationsKeepWorkersBounded(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	nodes := map[int]*Node{}
	for id := 1; id <= 3; id++ {
		n := testNode(t, id, peers, dir)
		n.options.ElectionMin, n.options.ElectionJitter = time.Hour, time.Hour
		nodes[id] = n
		if err := n.Start(); err != nil {
			t.Fatal(err)
		}
	}
	for round := 0; round < 30; round++ {
		// Trigger a candidate's election; votes still traverse real TCP. All former
		// leaders remain alive so this exercises demotion rather than Stop cleanup.
		id := round%3 + 1
		n := nodes[id]
		n.mu.Lock()
		n.startElectionLocked()
		n.mu.Unlock()
		if leader, _ := awaitLeader(t, nodes); leader != id {
			t.Fatalf("round %d: unexpected leader %d", round, leader)
		}
		var reply wire.GenerateReply
		if err := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 3, Seed: 42, TimeoutMS: 3000}, &reply); err != nil || !reply.Committed {
			t.Fatalf("round %d: write %+v %v", round, reply, err)
		}
		awaitLogs(t, nodes, (round+1)*3)
		stack := make([]byte, 1<<20)
		workers := strings.Count(string(stack[:runtime.Stack(stack, true)]), "myraft/raft.(*Node).heartbeatLoop(")
		if workers != min(round+1, 3)*2 {
			t.Fatalf("round %d: duplicate/missing workers: %d", round, workers)
		}
	}
}
