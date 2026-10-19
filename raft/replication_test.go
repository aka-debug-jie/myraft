package raft

import (
	wire "myraft/rpc"
	"net"
	"testing"
	"time"
)

func entry(i, term int, op string, v int64) wire.LogEntry {
	return wire.LogEntry{Index: i, Term: term, Command: wire.Command{Op: op, Value: v}}
}
func seedNode(t *testing.T, n *Node, term int, entries []wire.LogEntry, commit int) {
	t.Helper()
	if err := n.persistLocked(term, -1); err != nil {
		t.Fatal(err)
	}
	if len(entries) > 0 {
		if err := n.appendEntriesLocked(entries); err != nil {
			t.Fatal(err)
		}
	}
	if err := n.commitLocked(commit); err != nil {
		t.Fatal(err)
	}
}
func waitFor(t *testing.T, description string, ready func() bool) {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if ready() {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("timeout: " + description)
}
func awaitLogs(t *testing.T, nodes map[int]*Node, commands int) {
	t.Helper()
	waitFor(t, "consistent logs/state", func() bool {
		var first wire.StatusReply
		have := false
		for _, n := range nodes {
			s := snapshot(n)
			if s.Error != "" || s.CommitIndex != s.LastLogIndex || s.LastApplied != s.CommitIndex || s.AppliedCommands != commands {
				return false
			}
			if have && (s.LogHash != first.LogHash || s.CommittedHash != first.CommittedHash || s.X != first.X || s.CommitIndex != first.CommitIndex) {
				return false
			}
			first, have = s, true
		}
		return have
	})
}
func TestVoteLogFreshness(t *testing.T) {
	for _, c := range []struct {
		name        string
		index, term int
		want        bool
	}{{"older", 99, 1, false}, {"shorter", 1, 2, false}, {"equal", 2, 2, true}, {"longer", 3, 2, true}, {"newer", 1, 3, true}} {
		t.Run(c.name, func(t *testing.T) {
			n := testNode(t, 1, testPeers(t, 3), t.TempDir())
			seedNode(t, n, 3, []wire.LogEntry{entry(1, 1, "add", 2), entry(2, 2, "add", 3)}, 0)
			var r wire.VoteReply
			err := n.RequestVote(&wire.VoteArgs{Term: 4, CandidateID: 2, LastLogIndex: c.index, LastLogTerm: c.term}, &r)
			if err != nil || r.VoteGranted != c.want {
				t.Fatalf("vote %+v %v", r, err)
			}
		})
	}
}
func TestAppendBoundsAndDuplicates(t *testing.T) {
	for _, c := range []struct {
		name       string
		prev, term int
		entries    []wire.LogEntry
		ok         bool
		commit     int
	}{{"missing", 4, 2, nil, false, 0}, {"wrong term", 2, 1, nil, false, 0}, {"empty", 1, 1, nil, true, 1}, {"sentinel", 0, 0, nil, true, 0}, {"duplicate", 0, 0, []wire.LogEntry{entry(1, 1, "add", 2)}, true, 1}} {
		t.Run(c.name, func(t *testing.T) {
			n := testNode(t, 1, testPeers(t, 3), t.TempDir())
			seedNode(t, n, 3, []wire.LogEntry{entry(1, 1, "add", 2), entry(2, 2, "mul", 3), entry(3, 2, "add", 4)}, 0)
			before := snapshot(n)
			args := wire.AppendEntriesArgs{Term: 3, LeaderID: 2, PrevLogIndex: c.prev, PrevLogTerm: c.term, Entries: c.entries, LeaderCommit: 3}
			for repeat := 0; repeat < 2; repeat++ {
				var r wire.AppendEntriesReply
				if err := n.AppendEntries(&args, &r); err != nil {
					t.Fatal(err)
				}
				s := snapshot(n)
				if r.Success != c.ok || s.CommitIndex != c.commit || s.LastApplied != c.commit || s.LogHash != before.LogHash {
					t.Fatalf("reply %+v state %+v", r, s)
				}
				if c.commit == 1 && s.X != 2 {
					t.Fatal("entry applied twice")
				}
			}
		})
	}
}
func TestConflictRepairAndCommittedProtection(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	n := testNode(t, 1, peers, dir)
	seedNode(t, n, 3, []wire.LogEntry{entry(1, 1, "add", 2), entry(2, 2, "mul", 3), entry(3, 2, "add", 4)}, 1)
	args := wire.AppendEntriesArgs{Term: 3, LeaderID: 2, PrevLogIndex: 1, PrevLogTerm: 1, Entries: []wire.LogEntry{entry(2, 3, "add", 8)}, LeaderCommit: 1}
	var r wire.AppendEntriesReply
	if err := n.AppendEntries(&args, &r); err != nil || !r.Success {
		t.Fatalf("%+v %v", r, err)
	}
	n.Stop()
	n = testNode(t, 1, peers, dir)
	s := snapshot(n)
	if s.LastLogIndex != 2 || s.LastLogTerm != 3 || s.X != 2 || s.CommitIndex != 1 {
		t.Fatalf("bad recovery %+v", s)
	}
	if err := n.commitLocked(2); err != nil {
		t.Fatal(err)
	}
	before := snapshot(n)
	args.Term = 4
	args.Entries = []wire.LogEntry{entry(2, 4, "add", 99)}
	r = wire.AppendEntriesReply{}
	err := n.AppendEntries(&args, &r)
	after := snapshot(n)
	if err == nil || r.Success || before.LogHash != after.LogHash || before.X != after.X || before.CommitIndex != after.CommitIndex {
		t.Fatal("committed prefix overwritten")
	}
}
func TestCurrentTermCommitAndStaleReply(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 3), t.TempDir())
	seedNode(t, n, 3, []wire.LogEntry{entry(1, 2, "add", 7)}, 0)
	n.state, n.leaderID = Leader, 1
	n.matchIndex = map[int]int{1: 1, 2: 1}
	n.nextIndex = map[int]int{2: 2, 3: 1}
	n.advanceCommitLocked()
	if n.commitIndex != 0 {
		t.Fatal("old term committed directly")
	}
	if err := n.appendEntriesLocked([]wire.LogEntry{entry(2, 3, "noop", 0)}); err != nil {
		t.Fatal(err)
	}
	n.advanceCommitLocked()
	if n.commitIndex != 0 {
		t.Fatal("no majority")
	}
	n.handleAppendReplyLocked(2, wire.AppendEntriesArgs{Term: 2, PrevLogIndex: 2}, wire.AppendEntriesReply{Term: 2, Success: true})
	if n.matchIndex[2] != 1 || n.commitIndex != 0 {
		t.Fatal("stale response counted")
	}
	n.matchIndex[2] = 2
	n.advanceCommitLocked()
	if n.commitIndex != 2 || n.x != 7 {
		t.Fatal("current term failed to commit prefix")
	}
	n.state = Follower
	n.matchIndex[3] = 0
	n.handleAppendReplyLocked(3, wire.AppendEntriesArgs{Term: 3, PrevLogIndex: 2}, wire.AppendEntriesReply{Term: 3, Success: true})
	if n.matchIndex[3] != 0 {
		t.Fatal("follower used delayed reply")
	}
}
func TestReplication2101EmptyNodeFailoverRestart(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	nodes := make(map[int]*Node)
	// Node 3 is preconfigured but has never voted or stored a log.
	for id := 1; id <= 2; id++ {
		n := testNode(t, id, peers, dir)
		if err := n.Start(); err != nil {
			t.Fatal(err)
		}
		nodes[id] = n
	}
	leader, term := awaitLeader(t, nodes)
	var r wire.GenerateReply
	if err := nodes[leader].Generate(&wire.GenerateArgs{Count: 2101, Seed: 42, TimeoutMS: 10000}, &r); err != nil || !r.Committed {
		t.Fatalf("generate %+v %v", r, err)
	}
	awaitLogs(t, nodes, 2101)
	n := testNode(t, 3, peers, dir)
	if err := n.Start(); err != nil {
		t.Fatal(err)
	}
	nodes[3] = n
	awaitLogs(t, nodes, 2101)
	nodes[leader].Stop()
	delete(nodes, leader)
	newLeader, newTerm := awaitLeader(t, nodes)
	if newTerm <= term {
		t.Fatal("term did not advance")
	}
	if err := nodes[newLeader].Generate(&wire.GenerateArgs{Count: 23, Seed: 9, TimeoutMS: 10000}, &r); err != nil || !r.Committed {
		t.Fatalf("generate %+v %v", r, err)
	}
	restarted := testNode(t, leader, peers, dir)
	if err := restarted.Start(); err != nil {
		t.Fatal(err)
	}
	nodes[leader] = restarted
	awaitLogs(t, nodes, 2124)
}
func TestSingleNodeCommandsAndConcurrentSubmit(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 1), t.TempDir())
	if err := n.Start(); err != nil {
		t.Fatal(err)
	}
	awaitLeader(t, map[int]*Node{1: n})
	done := make(chan wire.GenerateReply, 8)
	for i := 0; i < 8; i++ {
		go func(seed int64) {
			var r wire.GenerateReply
			_ = n.Generate(&wire.GenerateArgs{Count: 31, Seed: seed, TimeoutMS: 10000}, &r)
			done <- r
		}(int64(i))
	}
	for i := 0; i < 8; i++ {
		if r := <-done; !r.Committed || r.Commands != 31 {
			t.Fatalf("generate %+v", r)
		}
	}
	awaitLogs(t, map[int]*Node{1: n}, 248)
}
func TestMinorityCannotCommitAndStopWakesRequest(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	nodes := make(map[int]*Node)
	for id := 1; id <= 3; id++ {
		n := testNode(t, id, peers, dir)
		if err := n.Start(); err != nil {
			t.Fatal(err)
		}
		nodes[id] = n
	}
	leader, _ := awaitLeader(t, nodes)
	awaitLogs(t, nodes, 0)
	n := nodes[leader]
	for id, peer := range nodes {
		if id != leader {
			peer.Stop()
		}
	}
	before := snapshot(n)
	var r wire.GenerateReply
	_ = n.Generate(&wire.GenerateArgs{Count: 5, Seed: 3, TimeoutMS: 150}, &r)
	after := snapshot(n)
	if r.Committed || after.CommitIndex != before.CommitIndex || after.X != before.X {
		t.Fatal("minority committed")
	}
	done := make(chan wire.GenerateReply, 1)
	go func() {
		var p wire.GenerateReply
		_ = n.Generate(&wire.GenerateArgs{Count: 1, Seed: 1, TimeoutMS: 10000}, &p)
		done <- p
	}()
	waitFor(t, "request appended", func() bool { return snapshot(n).LastLogIndex > after.LastLogIndex })
	stopped := make(chan struct{})
	go func() { n.Stop(); close(stopped) }()
	select {
	case <-stopped:
	case <-time.After(2 * time.Second):
		t.Fatal("Stop blocked")
	}
	select {
	case r := <-done:
		if r.Committed {
			t.Fatal("stopped minority committed")
		}
	case <-time.After(time.Second):
		t.Fatal("waiter not woken")
	}
}

func TestElectionRequestsBoundedAcrossTerms(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	accepted := make(chan net.Conn, 128)
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			accepted <- conn
		}
	}()
	defer func() {
		listener.Close()
		<-done
		close(accepted)
		for conn := range accepted {
			conn.Close()
		}
	}()
	peers := testPeers(t, 3)
	peers[2], peers[3] = listener.Addr().String(), listener.Addr().String()
	n := testNode(t, 1, peers, t.TempDir())
	n.options.RPCTimeout = 5 * time.Second
	n.mu.Lock()
	n.startElectionLocked()
	var conns []net.Conn
	for i := 0; i < 2; i++ {
		select {
		case conn := <-accepted:
			conns = append(conns, conn)
		case <-time.After(time.Second):
			n.mu.Unlock()
			for _, conn := range conns {
				conn.Close()
			}
			t.Fatal("vote call did not start")
		}
	}
	for i := 0; i < 20; i++ {
		n.startElectionLocked()
	}
	pending := len(n.votePending)
	n.mu.Unlock()
	time.Sleep(30 * time.Millisecond)
	extra := len(accepted)
	for _, conn := range conns {
		conn.Close()
	}
	if pending != 2 || extra != 0 {
		t.Fatalf("unbounded vote calls: pending=%d extra connections=%d", pending, extra)
	}
	waitFor(t, "vote slots released", func() bool { n.mu.Lock(); defer n.mu.Unlock(); return len(n.votePending) == 0 })
	n.mu.Lock()
	n.options.RPCTimeout = 500 * time.Millisecond
	n.startElectionLocked()
	n.mu.Unlock()
	conns = nil
	for i := 0; i < 2; i++ {
		select {
		case conn := <-accepted:
			conns = append(conns, conn)
		case <-time.After(time.Second):
			for _, conn := range conns {
				conn.Close()
			}
			t.Fatal("next term could not reuse vote slots")
		}
	}
	begin := time.Now()
	n.Stop()
	for _, conn := range conns {
		conn.Close()
	}
	if time.Since(begin) > 2*time.Second || len(n.votePending) != 0 {
		t.Fatal("Stop did not drain deadline-bound vote calls")
	}
}
