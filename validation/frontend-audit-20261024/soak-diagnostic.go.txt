package raft

import (
	"encoding/json"
	"io"
	"log"
	"os"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	wire "myraft/rpc"
)

// Opt in: RAFT_SOAK_NODES=100 RAFT_SOAK_ROTATIONS=20 RAFT_SOAK_DURATION=30m.
// Uses real TCP in one process. Runtime figures are not multiprocess RSS.
func TestResourceSoak(t *testing.T) {
	if os.Getenv("RAFT_SOAK_NODES") == "" {
		t.Skip("set RAFT_SOAK_NODES for the explicit resource experiment")
	}
	count, err := strconv.Atoi(os.Getenv("RAFT_SOAK_NODES"))
	if err != nil || count < 3 || count > 100 {
		t.Fatal("invalid RAFT_SOAK_NODES")
	}
	rotations, err := strconv.Atoi(os.Getenv("RAFT_SOAK_ROTATIONS"))
	if err != nil || rotations < 1 || rotations > 50 {
		t.Fatal("invalid RAFT_SOAK_ROTATIONS")
	}
	duration, err := time.ParseDuration(os.Getenv("RAFT_SOAK_DURATION"))
	if err != nil || duration < 0 {
		t.Fatal("invalid RAFT_SOAK_DURATION")
	}
	before := runtime.NumGoroutine()
	start := time.Now()
	peers, dir := testPeers(t, count), t.TempDir()
	nodes := map[int]*Node{}
	defer func() {
		for _, n := range nodes {
			n.Stop()
		}
	}()
	add := func(id int) {
		n, err := NewNode(Options{ClusterID: "test-cluster", ID: id, Peers: peers, DataDir: dir,
			Logger: log.New(io.Discard, "", 0), ElectionMin: 3 * time.Second, ElectionJitter: 3 * time.Second,
			HeartbeatInterval: 150 * time.Millisecond, RPCTimeout: time.Second})
		if err != nil {
			data, readErr := os.ReadFile("/proc/net/tcp")
            t.Logf("port failure tcp snapshot (%v): %s", readErr, data)
            t.Fatal(err)
        }
		nodes[id] = n
		if err = n.Start(); err != nil {
			data, readErr := os.ReadFile("/proc/net/tcp")
            t.Logf("port failure tcp snapshot (%v): %s", readErr, data)
            t.Fatal(err)
        }
	}
	for id := 1; id <= count; id++ {
		add(id)
	}
	commands := 0
	write := func(n *Node, count int) {
		var r wire.GenerateReply
		if err := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: count, Seed: 42, TimeoutMS: 15000}, &r); err != nil || !r.Committed {
			t.Fatalf("uncertain/failed write, no retry: %+v %v", r, err)
		}
		commands += count
		awaitLogs(t, nodes, commands)
	}
	leader, _ := awaitLeader(t, nodes)
	write(nodes[leader], 2101)
	checkpoint := snapshot(nodes[leader])
	record := func(phase string, round int) {
		connections, allowedWorkers := 0, 0
		for _, n := range nodes {
			var s wire.StatusReply
			n.Status(&wire.StatusArgs{TargetIndex: checkpoint.CommitIndex}, &s)
			if s.TargetHash != checkpoint.CommittedHash || s.TargetX != checkpoint.X {
				t.Fatal("fixed committed checkpoint changed")
			}
			n.mu.Lock()
			connections += len(n.connections)
			if n.replicationStarted {
				allowedWorkers += count - 1
			}
			n.mu.Unlock()
		}
		stack := make([]byte, 8<<20)
		workers := strings.Count(string(stack[:runtime.Stack(stack, true)]), "myraft/raft.(*Node).heartbeatLoop(")
		if workers > allowedWorkers {
			t.Fatalf("duplicate peer workers: %d > %d", workers, allowedWorkers)
		}
		runtime.GC()
		var mem runtime.MemStats
		runtime.ReadMemStats(&mem)
		b, _ := json.Marshal(map[string]any{"phase": phase, "round": round, "elapsed_seconds": time.Since(start).Seconds(),
			"goroutines": runtime.NumGoroutine(), "workers": workers, "worker_bound": allowedWorkers,
			"accepted_connections": connections, "heap_live_bytes": mem.HeapAlloc, "commands": commands})
		t.Log(string(b))
	}
	record("initial", 0)
	for round := 1; round <= rotations; round++ {
		leader, _ = awaitLeader(t, nodes)
		nodes[leader].Stop()
		delete(nodes, leader)
		replacement, _ := awaitLeader(t, nodes)
		write(nodes[replacement], 16)
		add(leader)
		awaitLogs(t, nodes, commands)
		record("rotation", round)
	}
	for time.Since(start) < duration {
		phase := "idle"
		if time.Since(start) < duration/2 {
			leader, _ = awaitLeader(t, nodes)
			write(nodes[leader], 16)
			phase = "writing"
		}
		record(phase, 0)
		time.Sleep(min(10*time.Second, max(0, duration-time.Since(start))))
	}
	for _, n := range nodes {
		n.Stop()
	}
	waitFor(t, "owned goroutines return after Stop", func() bool { return runtime.NumGoroutine() <= before+4 })
	t.Logf("stopped baseline_goroutines=%d final_goroutines=%d", before, runtime.NumGoroutine())
}
