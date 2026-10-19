package raft

import (
	"fmt"
	wire "myraft/rpc"
	"testing"
)

func TestSummaryIsNotLogVerification(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 3), t.TempDir())
	seedNode(t, n, 1, []wire.LogEntry{entry(1, 1, "add", 7), entry(2, 1, "mul", 3)}, 1)
	var full, summary wire.StatusReply
	if err := n.Status(&wire.StatusArgs{}, &full); err != nil {
		t.Fatal(err)
	}
	summary = full
	if err := n.Status(&wire.StatusArgs{Summary: true}, &summary); err != nil {
		t.Fatal(err)
	}
	if summary.ID != full.ID || summary.CommitIndex != full.CommitIndex || summary.LastLogIndex != full.LastLogIndex || summary.X != 7 || summary.CommittedHash != full.CommittedHash {
		t.Fatalf("summary lost cached state: %+v", summary)
	}
	if summary.LogHash != "" || summary.TargetAvailable || summary.TargetHash != "" {
		t.Fatal("summary claimed full verification")
	}
	if err := n.Status(&wire.StatusArgs{Summary: true, TargetIndex: 1}, &summary); err == nil {
		t.Fatal("summary accepted historical target")
	}
	if err := n.Status(&wire.StatusArgs{TargetIndex: 1}, &full); err != nil || !full.TargetAvailable || full.TargetHash != logHash(n.log[1:2]) {
		t.Fatal("full status lost historical validation")
	}
}
func TestReplicationBatchSizes(t *testing.T) {
	for _, batch := range []int{64, 128, 256} {
		t.Run(fmt.Sprint(batch), func(t *testing.T) {
			peers, dir := testPeers(t, 3), t.TempDir()
			nodes := map[int]*Node{}
			for id := range peers {
				n := testNode(t, id, peers, dir)
				n.options.BatchSize = batch
				nodes[id] = n
				if err := n.Start(); err != nil {
					t.Fatal(err)
				}
			}
			leader, _ := awaitLeader(t, nodes)
			var reply wire.GenerateReply
			if err := nodes[leader].Generate(&wire.GenerateArgs{Count: 513, Seed: 42, TimeoutMS: 5000}, &reply); err != nil || !reply.Committed {
				t.Fatalf("%+v %v", reply, err)
			}
			awaitLogs(t, nodes, 513)
		})
	}
	for _, size := range []int{-1, 4097} {
		if n, err := NewNode(Options{ID: 1, Peers: map[int]string{1: "127.0.0.1:1"}, DataDir: t.TempDir(), BatchSize: size}); err == nil {
			n.Stop()
			t.Fatal("invalid batch size accepted")
		}
	}
}
