package raft

import (
	"net"
	"testing"
	"time"

	wire "myraft/rpc"
)

// Distinct routing names may reach the same honest member (DNS or a proxy).
func aliasCluster(t *testing.T, aliasID int) map[int]*Node {
	t.Helper()
	peers, dir := testPeers(t, 5), t.TempDir()
	_, port, _ := net.SplitHostPort(peers[2])
	peers[aliasID] = "localhost:" + port
	nodes := make(map[int]*Node)
	for id := 1; id < aliasID; id++ {
		n := testNode(t, id, peers, dir)
		n.options.ElectionMin, n.options.ElectionJitter = time.Hour, time.Hour
		if err := n.Start(); err != nil {
			t.Fatal(err)
		}
		nodes[id] = n
	}
	return nodes
}

func TestAliasedVoterCannotAuthorizeLeader(t *testing.T) {
	n := aliasCluster(t, 3)[1] // Five configured voters, only two actual members.
	n.mu.Lock()
	n.startElectionLocked()
	n.mu.Unlock()
	deadline := time.Now().Add(2 * time.Second)
	for {
		n.mu.Lock()
		pending, state, votes := len(n.votePending), n.state, len(n.votes)
		n.mu.Unlock()
		if pending == 0 {
			if state == Leader || votes > 2 {
				t.Fatalf("two actual members authorized a five-member leader: state=%s votes=%d", state, votes)
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("bounded vote calls did not finish")
		}
		time.Sleep(time.Millisecond)
	}
}

func TestAliasedReplicaCannotCommitMinorityWrite(t *testing.T) {
	nodes := aliasCluster(t, 4) // Three real members first authorize a legitimate leader.
	n := nodes[1]
	n.mu.Lock()
	n.startElectionLocked()
	n.mu.Unlock()
	if id, _ := awaitLeader(t, nodes); id != 1 {
		t.Fatalf("leader=%d", id)
	}
	var first wire.GenerateReply
	if err := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 1, Seed: 1, TimeoutMS: 2000}, &first); err != nil || !first.Committed {
		t.Fatalf("majority write failed: %+v %v", first, err)
	}
	awaitLogs(t, nodes, 1)
	checkpoint := snapshot(n)
	nodes[3].Stop()
	var reply wire.GenerateReply
	if err := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 1, Seed: 2, TimeoutMS: 300}, &reply); err != nil {
		t.Fatal(err)
	}
	if !reply.Accepted || reply.Committed || snapshot(n).CommitIndex != checkpoint.CommitIndex {
		t.Fatalf("one replica counted twice: reply=%+v state=%+v", reply, snapshot(n))
	}
}

func TestPeerReplyIdentityPrecedesTermAndProgress(t *testing.T) {
	for _, kind := range []string{"node", "cluster", "members", "missing"} {
		t.Run(kind, func(t *testing.T) {
			n := testNode(t, 1, testPeers(t, 3), t.TempDir())
			seedNode(t, n, 2, []wire.LogEntry{entry(1, 2, "add", 1)}, 0)
			n.state, n.votes = Candidate, map[int]bool{1: true}
			r := wire.VoteReply{NodeID: 2, ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, Term: 99, VoteGranted: true}
			switch kind {
			case "node":
				r.NodeID = 3
			case "cluster":
				r.ClusterID = "other"
			case "members":
				r.MembershipHash = "other"
			case "missing":
				r.NodeID, r.ClusterID, r.MembershipHash = 0, "", ""
			}
			n.handleVoteReplyLocked(2, 2, r)
			if n.term != 2 || n.state != Candidate || len(n.votes) != 1 {
				t.Fatal("unverified vote changed state")
			}
			n.state = Leader
			n.matchIndex, n.nextIndex = map[int]int{1: 1, 2: 0}, map[int]int{2: 1}
			args := wire.AppendEntriesArgs{TargetID: 2, Term: 2, Entries: n.log[1:]}
			n.handleAppendReplyLocked(2, args, wire.AppendEntriesReply{NodeID: r.NodeID, ClusterID: r.ClusterID, MembershipHash: r.MembershipHash, Term: 99, Success: true})
			if n.term != 2 || n.state != Leader || n.matchIndex[2] != 0 || n.commitIndex != 0 {
				t.Fatal("unverified append reply changed state")
			}
			// A verified higher-term response still wins over an obsolete request.
			args.Term = 1
			n.handleAppendReplyLocked(2, args, wire.AppendEntriesReply{NodeID: 2, ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, Term: 3})
			if n.term != 3 || n.state != Follower {
				t.Fatal("verified higher term ignored")
			}
		})
	}
}

func TestWrongTargetRejectedBeforePersistentChanges(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 3), t.TempDir())
	var vote wire.VoteReply
	var appendReply wire.AppendEntriesReply
	var heartbeat wire.HeartbeatReply
	if err := n.RequestVote(&wire.VoteArgs{TargetID: 3, ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, CandidateID: 2, Term: 99}, &vote); err == nil {
		t.Fatal("wrong vote target accepted")
	}
	if err := n.AppendEntries(&wire.AppendEntriesArgs{TargetID: 3, ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, LeaderID: 2, Term: 99}, &appendReply); err == nil {
		t.Fatal("wrong append target accepted")
	}
	if err := n.Heartbeat(&wire.HeartbeatArgs{TargetID: 3, ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, LeaderID: 2, Term: 99}, &heartbeat); err == nil {
		t.Fatal("wrong heartbeat target accepted")
	}
	if n.term != 0 || n.votedFor != -1 || n.lastIndexLocked() != 0 {
		t.Fatal("wrong target mutated persistent state")
	}
}
