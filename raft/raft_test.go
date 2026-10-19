package raft

import (
	"io"
	"log"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	wire "myraft/rpc"
)

func testPeers(t testing.TB, count int) map[int]string {
	t.Helper()
	peers := make(map[int]string)
	var listeners []net.Listener
	defer func() {
		for _, l := range listeners {
			l.Close()
		}
	}()
	for id := 1; id <= count; id++ {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		listeners = append(listeners, l)
		peers[id] = l.Addr().String()
	}
	return peers
}

func testNode(t testing.TB, id int, peers map[int]string, dir string) *Node {
	t.Helper()
	n, err := NewNode(Options{ID: id, Peers: peers, DataDir: dir, Logger: log.New(io.Discard, "", 0),
		ElectionMin: 300 * time.Millisecond, ElectionJitter: 300 * time.Millisecond,
		HeartbeatInterval: 50 * time.Millisecond, RPCTimeout: 100 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(n.Stop)
	return n
}

func snapshot(n *Node) wire.StatusReply {
	var s wire.StatusReply
	n.Status(&wire.StatusArgs{}, &s)
	return s
}

func awaitLeader(t testing.TB, nodes map[int]*Node) (int, int) {
	t.Helper()
	deadline := time.Now().Add(8 * time.Second)
	for time.Now().Before(deadline) {
		leader, term, count := 0, 0, 0
		for id, n := range nodes {
			s := snapshot(n)
			if s.State == string(Leader) {
				leader, term = id, s.Term
				count++
			}
		}
		if count == 1 {
			consistent := true
			for _, n := range nodes {
				s := snapshot(n)
				if s.LeaderID != leader || s.Term != term || s.Error != "" {
					consistent = false
				}
			}
			if consistent {
				return leader, term
			}
		}
		time.Sleep(20 * time.Millisecond)
	}
	for id, n := range nodes {
		t.Logf("node %d: %+v", id, snapshot(n))
	}
	t.Fatal("cluster did not converge to one leader")
	return 0, 0
}

func TestElectionFailoverRestartAndMinority(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	nodes := make(map[int]*Node)
	for id := 1; id <= 3; id++ {
		n := testNode(t, id, peers, dir)
		if err := n.Start(); err != nil {
			t.Fatal(err)
		}
		nodes[id] = n
	}
	leader, term := awaitLeader(t, nodes)
	time.Sleep(1200 * time.Millisecond)
	stableLeader, stableTerm := awaitLeader(t, nodes)
	if stableLeader != leader || stableTerm != term {
		t.Fatal("healthy leader was replaced despite heartbeats")
	}
	nodes[leader].Stop()
	delete(nodes, leader)
	newLeader, newTerm := awaitLeader(t, nodes)
	if newTerm <= term {
		t.Fatal("failover did not advance term")
	}
	restarted := testNode(t, leader, peers, dir)
	if snapshot(restarted).Term < term {
		t.Fatal("restart lost persisted term")
	}
	if err := restarted.Start(); err != nil {
		t.Fatal(err)
	}
	nodes[leader] = restarted
	if id, _ := awaitLeader(t, nodes); id != newLeader {
		t.Fatal("restart disturbed healthy leader")
	}
	// Stop the leader and another follower, leaving one of three voters.
	survivor := leader
	for id, n := range nodes {
		if id != survivor {
			n.Stop()
			delete(nodes, id)
		}
	}
	initial := snapshot(nodes[survivor]).Term
	time.Sleep(1600 * time.Millisecond)
	s := snapshot(nodes[survivor])
	if s.State == string(Leader) {
		t.Fatal("minority elected a leader")
	}
	if s.Term < initial+2 {
		t.Fatalf("candidate failed to retry elections: %+v", s)
	}
}

func TestVoteSurvivesRestart(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	n := testNode(t, 1, peers, dir)
	var reply wire.VoteReply
	if err := n.RequestVote(&wire.VoteArgs{Term: 7, CandidateID: 2}, &reply); err != nil || !reply.VoteGranted {
		t.Fatalf("first vote: %+v %v", reply, err)
	}
	n.Stop()
	n = testNode(t, 1, peers, dir)
	if err := n.RequestVote(&wire.VoteArgs{Term: 7, CandidateID: 3}, &reply); err != nil || reply.VoteGranted {
		t.Fatalf("double vote after restart: %+v %v", reply, err)
	}
	var hb wire.HeartbeatReply
	if err := n.Heartbeat(&wire.HeartbeatArgs{Term: 7, LeaderID: 2}, &hb); err != nil {
		t.Fatal(err)
	}
	if snapshot(n).VotedFor != 2 {
		t.Fatal("same-term heartbeat cleared vote")
	}
	if err := n.RequestVote(&wire.VoteArgs{Term: 6, CandidateID: 3}, &reply); err != nil || reply.VoteGranted || reply.Term != 7 {
		t.Fatalf("stale request: %+v %v", reply, err)
	}
	if err := n.RequestVote(&wire.VoteArgs{Term: 8, CandidateID: 3}, &reply); err != nil || !reply.VoteGranted {
		t.Fatalf("new term: %+v %v", reply, err)
	}
}

func TestStaleVoteResponsesIgnored(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 3), t.TempDir())
	n.term, n.state, n.votes = 4, Candidate, map[int]bool{1: true}
	n.handleVoteReplyLocked(2, 3, wire.VoteReply{Term: 3, VoteGranted: true})
	if n.state != Candidate || len(n.votes) != 1 {
		t.Fatal("old-term response counted")
	}
	n.state = Follower
	n.handleVoteReplyLocked(2, 4, wire.VoteReply{Term: 4, VoteGranted: true})
	if n.state != Follower {
		t.Fatal("follower promoted by delayed response")
	}
}

func TestSingleNodeAndIdempotentStop(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 1), t.TempDir())
	if err := n.Start(); err != nil {
		t.Fatal(err)
	}
	awaitLeader(t, map[int]*Node{1: n})
	n.Stop()
	n.Stop()
	l, err := net.Listen("tcp", n.addr)
	if err != nil {
		t.Fatalf("stop did not release listener: %v", err)
	}
	l.Close()
}

func TestCorruptStateRejected(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "node-1-state.json"), []byte("broken"), 0644); err != nil {
		t.Fatal(err)
	}
	if _, err := NewNode(Options{ID: 1, Peers: testPeers(t, 1), DataDir: dir}); err == nil {
		t.Fatal("corrupt state silently reset")
	}
}

func TestPersistenceFailureDoesNotGrantVote(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 3), t.TempDir())
	// Renaming a file onto an existing directory must fail.
	n.statePath = n.options.DataDir
	var reply wire.VoteReply
	err := n.RequestVote(&wire.VoteArgs{Term: 1, CandidateID: 2}, &reply)
	if err == nil || reply.VoteGranted || snapshot(n).Error == "" {
		t.Fatalf("storage error ignored: %+v %v", reply, err)
	}
}
