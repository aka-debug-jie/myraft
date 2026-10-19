package raft

import (
	"testing"
	"time"

	wire "myraft/rpc"
)

func TestElectionDeadlineEvents(t *testing.T) {
	for _, name := range []string{"stale-log-vote", "grant-vote", "expired-append", "mismatched-append", "higher-vote-reply", "higher-append-reply", "expired-heartbeat", "valid-heartbeat"} {
		t.Run(name, func(t *testing.T) {
			n := testNode(t, 1, testPeers(t, 3), t.TempDir())
			seedNode(t, n, 2, []wire.LogEntry{entry(1, 2, "add", 3)}, 0)
			before := time.Unix(100, 0)
			n.deadline, n.state = before, Candidate
			reset := false
			switch name {
			case "stale-log-vote", "grant-vote":
				lastTerm := 1
				if name == "grant-vote" {
					lastTerm, reset = 2, true
				}
				var reply wire.VoteReply
				if err := n.RequestVote(&wire.VoteArgs{ClusterID: "test-cluster", MembershipHash: n.membershipHash, Term: 3, CandidateID: 2, LastLogIndex: 1, LastLogTerm: lastTerm}, &reply); err != nil {
					t.Fatal(err)
				}
				if reply.Term != 3 || reply.VoteGranted != reset || n.state != Follower {
					t.Fatalf("vote %+v, role %s", reply, n.state)
				}
			case "expired-append", "mismatched-append":
				term := 1
				if name == "mismatched-append" {
					term, reset = 3, true
				}
				var reply wire.AppendEntriesReply
				if err := n.AppendEntries(&wire.AppendEntriesArgs{ClusterID: "test-cluster", MembershipHash: n.membershipHash, Term: term, LeaderID: 2, PrevLogIndex: 8, PrevLogTerm: 2}, &reply); err != nil {
					t.Fatal(err)
				}
				if reply.Success {
					t.Fatal("unexpected matching prefix")
				}
			case "higher-vote-reply":
				n.handleVoteReplyLocked(2, 2, wire.VoteReply{Term: 3})
			case "higher-append-reply":
				n.handleAppendReplyLocked(2, wire.AppendEntriesArgs{ClusterID: "test-cluster", MembershipHash: n.membershipHash, Term: 2}, wire.AppendEntriesReply{Term: 3})
			case "expired-heartbeat", "valid-heartbeat":
				term := 1
				if name == "valid-heartbeat" {
					term, reset = 3, true
				}
				var reply wire.HeartbeatReply
				if err := n.Heartbeat(&wire.HeartbeatArgs{ClusterID: "test-cluster", MembershipHash: n.membershipHash, Term: term, LeaderID: 2}, &reply); err != nil {
					t.Fatal(err)
				}
				if reply.Accepted != reset {
					t.Fatalf("heartbeat %+v", reply)
				}
			}
			if reset && !n.deadline.After(before) {
				t.Fatal("valid event did not reset deadline")
			}
			if !reset && !n.deadline.Equal(before) {
				t.Fatal("rejected request or higher-term reply postponed election")
			}
		})
	}
}

func TestGenerateReplyReuse(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 1), t.TempDir())
	n.startElectionLocked()
	var reply wire.GenerateReply
	succeed := func() {
		t.Helper()
		if err := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 2, Seed: 42, TimeoutMS: 100}, &reply); err != nil || !reply.Accepted || !reply.Committed || reply.Error != "" {
			t.Fatalf("success %+v %v", reply, err)
		}
	}
	succeed()
	if err := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster"}, &reply); err != nil || reply.Accepted || reply.Committed || reply.Commands != 0 || reply.Error == "" {
		t.Fatalf("invalid args reused success: %+v %v", reply, err)
	}
	succeed()
	n.state = Follower
	if err := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 1, TimeoutMS: 10}, &reply); err != nil || reply.Accepted || reply.Committed || reply.Error != "not leader" {
		t.Fatalf("rejection reused success: %+v %v", reply, err)
	}
	n.state = Leader
	succeed()
	minority := testNode(t, 1, testPeers(t, 3), t.TempDir())
	seedNode(t, minority, 1, nil, 0)
	minority.electionStarted = time.Now()
	minority.becomeLeaderLocked()
	if err := minority.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 1, TimeoutMS: 10}, &reply); err != nil || !reply.Accepted || reply.Committed || reply.Error == "" {
		t.Fatalf("timeout reused success: %+v %v", reply, err)
	}
}

func BenchmarkAdvanceCommitIdle(b *testing.B) {
	n := &Node{peers: make(map[int]string), matchIndex: make(map[int]int), log: []wire.LogEntry{{}}}
	for i := 1; i <= 100; i++ {
		n.peers[i] = "unused"
	}
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		n.advanceCommitLocked()
	}
}

func TestIncrementalCommittedHashRecoveryAndFailure(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	n := testNode(t, 1, peers, dir)
	if n.committedHash != logHash(nil) {
		t.Fatal("empty digest differs")
	}
	seedNode(t, n, 1, benchmarkEntries(2101), 0)
	for _, index := range []int{1, 17, 128, 777, 2000} {
		if err := n.commitLocked(index); err != nil {
			t.Fatal(err)
		}
		if n.committedHash != logHash(n.log[1:index+1]) {
			t.Fatalf("digest differs at %d", index)
		}
	}
	n.Stop()
	n = testNode(t, 1, peers, dir)
	if n.committedHash != logHash(n.log[1:2001]) {
		t.Fatal("recovered digest differs")
	}
	if err := n.persistLocked(2, -1); err != nil {
		t.Fatal(err)
	}
	if err := n.replaceLogLocked(2001, []wire.LogEntry{entry(2001, 2, "noop", 0), entry(2002, 2, "add", 7)}); err != nil {
		t.Fatal(err)
	}
	if err := n.commitLocked(2002); err != nil {
		t.Fatal(err)
	}
	if n.committedHash != logHash(n.log[1:]) {
		t.Fatal("digest after uncommitted replacement differs")
	}
	if err := n.appendEntriesLocked([]wire.LogEntry{entry(2003, 2, "add", 11)}); err != nil {
		t.Fatal(err)
	}
	before := snapshot(n)
	original := n.statePath
	n.statePath = n.options.DataDir
	if err := n.commitLocked(2003); err == nil {
		t.Fatal("failed save accepted")
	}
	after := snapshot(n)
	if after.CommitIndex != before.CommitIndex || after.CommittedHash != before.CommittedHash || after.X != before.X {
		t.Fatal("failed save published state")
	}
	n.statePath = original
	if err := n.commitLocked(2003); err == nil {
		t.Fatal("failed node reused advanced digest")
	}
	n.Stop()
	n = testNode(t, 1, peers, dir)
	if n.commitIndex != before.CommitIndex || n.committedHash != before.CommittedHash {
		t.Fatal("recovery applied uncommitted suffix")
	}
	if err := n.commitLocked(2003); err != nil {
		t.Fatal(err)
	}
	if n.committedHash != logHash(n.log[1:]) {
		t.Fatal("digest after recovery differs")
	}
}
