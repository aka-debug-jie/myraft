package raft

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	wire "myraft/rpc"
)

func TestFixedMembershipRestartCannotSplitHistory(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	nodes := map[int]*Node{}
	for id := range peers {
		nodes[id] = testNode(t, id, peers, dir)
		if err := nodes[id].Start(); err != nil {
			t.Fatal(err)
		}
	}
	old, _ := awaitLeader(t, nodes)
	var reply wire.GenerateReply
	if err := nodes[old].Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 17, Seed: 11, TimeoutMS: 3000}, &reply); err != nil || !reply.Committed {
		t.Fatalf("initial write: %+v %v", reply, err)
	}
	awaitLogs(t, nodes, 17)
	checkpoint := snapshot(nodes[old])
	nodes[old].Stop()
	delete(nodes, old)
	wal := filepath.Join(dir, "node-"+strconv.Itoa(old)+"-log.wal")
	before, err := os.ReadFile(wal)
	if err != nil {
		t.Fatal(err)
	}
	for _, o := range []Options{{ClusterID: "test-cluster", ID: old, Peers: map[int]string{old: peers[old]}, DataDir: dir}, {ClusterID: "other-cluster", ID: old, Peers: peers, DataDir: dir}} {
		bad, err := NewNode(o)
		if err == nil {
			bad.Stop()
			t.Fatal("changed fixed identity accepted")
		}
	}
	after, _ := os.ReadFile(wal)
	if !bytes.Equal(before, after) {
		t.Fatal("rejected identity modified WAL")
	}
	leader, _ := awaitLeader(t, nodes)
	if err := nodes[leader].Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 23, Seed: 33, TimeoutMS: 3000}, &reply); err != nil || !reply.Committed {
		t.Fatal("majority write failed")
	}
	nodes[old] = testNode(t, old, peers, dir)
	if err := nodes[old].Start(); err != nil {
		t.Fatal(err)
	}
	awaitLogs(t, nodes, 40)
	for _, n := range nodes {
		var s wire.StatusReply
		n.Status(&wire.StatusArgs{TargetIndex: checkpoint.CommitIndex}, &s)
		if s.TargetHash != checkpoint.CommittedHash || s.TargetX != checkpoint.X {
			t.Fatal("history changed")
		}
	}
}

func TestLegacyClaimIsExplicitBackedUpAndReadOnly(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	n := testNode(t, 1, peers, dir)
	seedNode(t, n, 3, []wire.LogEntry{entry(1, 2, "add", 7), entry(2, 3, "mul", 9)}, 1)
	statePath, walPath := n.statePath, n.wal.Name()
	n.Stop()
	b, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatal(err)
	}
	var s map[string]any
	json.Unmarshal(b, &s)
	delete(s, "identity")
	oldState, _ := json.Marshal(s)
	os.WriteFile(statePath, oldState, 0600)
	w, err := os.ReadFile(walPath)
	if err != nil {
		t.Fatal(err)
	}
	torn := append(append([]byte(nil), w...), 1, 2, 3)
	os.WriteFile(walPath, torn, 0600)
	o := Options{ClusterID: "test-cluster", ID: 1, Peers: peers, DataDir: dir}
	bad, err := NewNode(o)
	if err == nil {
		bad.Stop()
		t.Fatal("legacy data silently claimed")
	}
	if !strings.Contains(err.Error(), "claim") {
		t.Fatal(err)
	}
	after, _ := os.ReadFile(walPath)
	if !bytes.Equal(after, torn) {
		t.Fatal("unclaimed WAL trimmed")
	}
	r, err := ClaimLegacy(o)
	if err != nil {
		t.Fatal(err)
	}
	if r.AlreadyBound || r.RecoveryTruncate != int64(len(w)) {
		t.Fatalf("audit %+v", r)
	}
	for name, data := range map[string][]byte{filepath.Base(statePath): oldState, filepath.Base(walPath): torn} {
		backup, err := os.ReadFile(filepath.Join(dir, r.Backup, name))
		if err != nil || !bytes.Equal(data, backup) {
			t.Fatal("original backup differs")
		}
		h := sha256.Sum256(data)
		if r.OriginalSHA256[name] != hex.EncodeToString(h[:]) {
			t.Fatal("backup hash differs")
		}
	}
	after, _ = os.ReadFile(walPath)
	if !bytes.Equal(after, torn) {
		t.Fatal("claim changed WAL")
	}
	// Different addresses preserve fixed membership and identity.
	routes := testPeers(t, 3)
	o.Peers = routes
	restored, err := NewNode(o)
	if err != nil {
		t.Fatal(err)
	}
	defer restored.Stop()
	if s := snapshot(restored); s.X != 7 || s.CommitIndex != 1 || s.LastLogIndex != 2 {
		t.Fatalf("recovered %+v", s)
	}
	var vote wire.VoteReply
	if err := restored.RequestVote(&wire.VoteArgs{ClusterID: "wrong", MembershipHash: restored.membershipHash, Term: 100, CandidateID: 2}, &vote); err == nil || restored.term != 3 {
		t.Fatal("foreign cluster changed term/vote")
	}
}

func TestLegacyClaimRejectsCorruptionWithoutPublishingIdentity(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	n := testNode(t, 1, peers, dir)
	seedNode(t, n, 1, []wire.LogEntry{entry(1, 1, "add", 7)}, 1)
	statePath, walPath := n.statePath, n.wal.Name()
	n.Stop()
	b, _ := os.ReadFile(statePath)
	var m map[string]any
	json.Unmarshal(b, &m)
	delete(m, "identity")
	old, _ := json.Marshal(m)
	os.WriteFile(statePath, old, 0600)
	w, _ := os.ReadFile(walPath)
	w[len(w)-1] ^= 1
	os.WriteFile(walPath, w, 0600)
	if _, err := ClaimLegacy(Options{ClusterID: "test-cluster", ID: 1, Peers: peers, DataDir: dir}); err == nil {
		t.Fatal("corrupt legacy accepted")
	}
	after, _ := os.ReadFile(statePath)
	if !bytes.Equal(after, old) {
		t.Fatal("identity published after failed audit")
	}
	after, _ = os.ReadFile(walPath)
	if !bytes.Equal(after, w) {
		t.Fatal("failed audit rewrote WAL")
	}
}

func TestLegacyClaimWithoutMetadataOnlyAcceptsEmptyWAL(t *testing.T) {
	for _, populated := range []bool{false, true} {
		t.Run(strconv.FormatBool(populated), func(t *testing.T) {
			peers, dir := testPeers(t, 3), t.TempDir()
			n := testNode(t, 1, peers, dir)
			if populated {
				seedNode(t, n, 1, []wire.LogEntry{entry(1, 1, "add", 3)}, 0)
			}
			path := n.statePath
			n.Stop()
			if err := os.Remove(path); err != nil {
				t.Fatal(err)
			}
			o := Options{ClusterID: "test-cluster", ID: 1, Peers: peers, DataDir: dir}
			r, err := ClaimLegacy(o)
			if populated {
				if err == nil {
					t.Fatal("log with missing election metadata was claimed")
				}
				return
			}
			if err != nil || len(r.OriginallyMissing) != 1 {
				t.Fatalf("claim empty old WAL: %+v %v", r, err)
			}
			recovered, err := NewNode(o)
			if err != nil {
				t.Fatal(err)
			}
			recovered.Stop()
		})
	}
}
