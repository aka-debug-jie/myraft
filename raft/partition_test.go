package raft

import (
	"io"
	wire "myraft/rpc"
	"net"
	"sync"
	"testing"
	"time"
)

// Each directed test link owns its sockets, including reused RPC connections.
type partitionProxy struct {
	listener        net.Listener
	target          string
	mu              sync.Mutex
	enabled, closed bool
	conns           map[net.Conn]bool
	wg              sync.WaitGroup
}

func newPartitionProxy(t *testing.T, target string) *partitionProxy {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	p := &partitionProxy{listener: l, target: target, enabled: true, conns: make(map[net.Conn]bool)}
	p.wg.Add(1)
	go func() {
		defer p.wg.Done()
		for {
			c, err := l.Accept()
			if err != nil {
				return
			}
			p.wg.Add(1)
			go p.forward(c)
		}
	}()
	t.Cleanup(func() {
		p.mu.Lock()
		p.closed = true
		p.listener.Close()
		for c := range p.conns {
			c.Close()
		}
		p.mu.Unlock()
		p.wg.Wait()
	})
	return p
}
func (p *partitionProxy) forward(front net.Conn) {
	defer p.wg.Done()
	defer front.Close()
	p.mu.Lock()
	allowed := p.enabled && !p.closed
	p.mu.Unlock()
	if !allowed {
		return
	}
	back, err := net.DialTimeout("tcp", p.target, 100*time.Millisecond)
	if err != nil {
		return
	}
	defer back.Close()
	p.mu.Lock()
	if !p.enabled || p.closed {
		p.mu.Unlock()
		return
	}
	p.conns[front], p.conns[back] = true, true
	p.mu.Unlock()
	defer func() { p.mu.Lock(); delete(p.conns, front); delete(p.conns, back); p.mu.Unlock() }()
	done := make(chan struct{})
	go func() { io.Copy(back, front); back.Close(); front.Close(); close(done) }()
	io.Copy(front, back)
	back.Close()
	front.Close()
	<-done
}
func (p *partitionProxy) setEnabled(enabled bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.enabled = enabled
	if !enabled {
		for c := range p.conns {
			c.Close()
		}
	}
}
func TestPartitionRepairsUncommittedLeaderTail(t *testing.T) {
	addresses, dir := testPeers(t, 3), t.TempDir()
	links := make(map[[2]int]*partitionProxy)
	for src := 1; src <= 3; src++ {
		for dst := 1; dst <= 3; dst++ {
			if src != dst {
				links[[2]int{src, dst}] = newPartitionProxy(t, addresses[dst])
			}
		}
	}
	nodes := make(map[int]*Node)
	for id := 1; id <= 3; id++ {
		peers := map[int]string{id: addresses[id]}
		for other := 1; other <= 3; other++ {
			if id != other {
				peers[other] = links[[2]int{id, other}].listener.Addr().String()
			}
		}
		nodes[id] = testNode(t, id, peers, dir)
	}
	for _, n := range nodes {
		if err := n.Start(); err != nil {
			t.Fatal(err)
		}
	}
	generate := func(id, count int, seed int64, budget int) wire.GenerateReply {
		t.Helper()
		var r wire.GenerateReply
		if err := wire.Call(addresses[id], "RaftNode.Generate", &wire.GenerateArgs{ClusterID: "test-cluster", Count: count, Seed: seed, TimeoutMS: budget}, &r, time.Duration(budget)*time.Millisecond+2*time.Second); err != nil {
			t.Fatal(err)
		}
		return r
	}
	committed := func(r wire.GenerateReply) {
		t.Helper()
		if !r.Accepted || !r.Committed || r.Error != "" {
			t.Fatalf("write not committed: %+v", r)
		}
	}
	status := func(id, index int) wire.StatusReply {
		t.Helper()
		var r wire.StatusReply
		if err := wire.Call(addresses[id], "RaftNode.Status", &wire.StatusArgs{TargetIndex: index}, &r, 2*time.Second); err != nil || r.Error != "" {
			t.Fatalf("status %+v %v", r, err)
		}
		return r
	}
	old, oldTerm := awaitLeader(t, nodes)
	a := generate(old, 17, 11, 10000)
	committed(a)
	awaitLogs(t, nodes, 17)
	checkpoint := status(old, a.LastIndex)
	checkPrefix := func(group map[int]*Node) {
		t.Helper()
		for id := range group {
			s := status(id, a.LastIndex)
			if !s.TargetAvailable || s.TargetIndex != a.LastIndex || s.TargetHash != checkpoint.TargetHash || s.TargetX != checkpoint.TargetX {
				t.Fatalf("node %d changed committed history", id)
			}
		}
	}
	for edge, p := range links {
		if edge[0] == old || edge[1] == old {
			p.setEnabled(false)
		}
	}
	b := generate(old, 5, 22, 150)
	isolated := status(old, a.LastIndex)
	if !b.Accepted || b.Committed || b.Error != "commit timed out; outcome unknown" || b.FirstIndex != a.LastIndex+1 || isolated.LastLogIndex != a.LastIndex+5 || isolated.CommitIndex != checkpoint.CommitIndex || isolated.X != checkpoint.X || isolated.CommittedHash != checkpoint.CommittedHash {
		t.Fatalf("minority result %+v, status %+v", b, isolated)
	}
	majority := make(map[int]*Node)
	for id, n := range nodes {
		if id != old {
			majority[id] = n
		}
	}
	elected, term := awaitLeader(t, majority)
	if term <= oldTerm {
		t.Fatal("term did not advance")
	}
	c := generate(elected, 19, 33, 10000)
	committed(c)
	awaitLogs(t, majority, 36)
	checkPrefix(majority)
	readEntry := func(n *Node, index int) wire.LogEntry { n.mu.Lock(); defer n.mu.Unlock(); return n.log[index] }
	before, after := readEntry(nodes[old], b.FirstIndex), readEntry(nodes[elected], b.FirstIndex)
	if before.Term != oldTerm || after.Term != term || before.Term == after.Term || after.Command.Op != "noop" {
		t.Fatalf("missing conflict: %+v vs %+v", before, after)
	}
	for edge, p := range links {
		if edge[0] == old || edge[1] == old {
			p.setEnabled(true)
		}
	}
	elected, _ = awaitLeader(t, nodes)
	awaitLogs(t, nodes, 36)
	checkPrefix(nodes)
	if readEntry(nodes[old], b.FirstIndex) != after {
		t.Fatal("old leader retained conflicting suffix")
	}
	want := partitionReference(partitionReference(0, generateCommands(17, 11)), generateCommands(19, 33))
	for id := range nodes {
		if status(id, a.LastIndex).X != want {
			t.Fatal("applied minority commands")
		}
	}
	d := generate(elected, 11, 44, 10000)
	committed(d)
	awaitLogs(t, nodes, 47)
	checkPrefix(nodes)
	want = partitionReference(want, generateCommands(11, 44))
	for id := range nodes {
		if status(id, a.LastIndex).X != want {
			t.Fatal("post-heal state differs from arithmetic reference")
		}
	}
}

// Does not call the production applyCommand implementation.
func partitionReference(x int64, commands []wire.Command) int64 {
	for _, c := range commands {
		switch c.Op {
		case "add":
			x += c.Value
		case "sub":
			x -= c.Value
		case "mul":
			x *= c.Value
		case "div":
			x /= c.Value
		case "mod":
			x %= c.Value
		}
	}
	return x
}
