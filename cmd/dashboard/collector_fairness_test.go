package main

import (
	"net"
	"testing"

	"myraft/config"
)

func TestCollectorSlowPrefixCannotStarveHealthyTail(t *testing.T) {
	d, _, peer := testConsole(t)
	fast := d.active.Config.Nodes[0]
	nodes := make([]config.Node, 0, 33)
	for i := 0; i < 32; i++ {
		listener, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { listener.Close() })
		nodes = append(nodes, config.Node{ID: i + 2, Addr: listener.Addr().String()})
	}
	nodes = append(nodes, fast)
	d.mu.Lock()
	d.active.Config.Nodes = nodes
	d.snap.Seq = 0
	peers, err := d.active.Config.Peers()
	d.mu.Unlock()
	if err != nil {
		t.Fatal(err)
	}
	peer.identity, err = config.FixedIdentity(d.active.Config.ClusterID, peers)
	if err != nil {
		t.Fatal(err)
	}
	peer.eventSeq.Store(1)
	before := peer.calls.Load()
	// Five first-worker batches cover all 33 members, even with slow predecessors.
	for round := 0; round < 5; round++ {
		d.collectRound()
		d.mu.Lock()
		tail := d.snap.Nodes[32]
		cursor := d.eventCursors[fast.ID]
		for i, sample := range d.snap.Nodes {
			if sample.ID != nodes[i].ID {
				t.Errorf("sample order changed at %d", i)
			}
		}
		d.mu.Unlock()
		t.Logf("round=%d healthy calls=%d reachable=%v error=%q", round, peer.calls.Load()-before, tail.Reachable, tail.Error)
		if tail.Reachable && tail.IdentityOK && peer.calls.Load() > before {
			if cursor.Seq != 1 {
				t.Fatalf("event cursor mapped incorrectly: %+v", cursor)
			}
			return
		}
	}
	t.Fatal("healthy tail was never sampled")
}
