// Package raft implements fixed-membership Raft with a durable arithmetic state machine.
package raft

import (
	"errors"
	"fmt"
	"hash"
	"log"
	"math/rand"
	"net"
	stdrpc "net/rpc"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

type State string

const (
	Follower  State = "Follower"
	Candidate State = "Candidate"
	Leader    State = "Leader"
)

type Options struct {
	ClusterID         string
	ID                int
	Peers             map[int]string
	DataDir           string
	Logger            *log.Logger
	ElectionMin       time.Duration
	ElectionJitter    time.Duration
	HeartbeatInterval time.Duration
	RPCTimeout        time.Duration
	BatchSize         int
}

type Node struct {
	identity                                  config.Identity
	membershipHash                            string
	instanceID                                string
	revision                                  uint64
	events                                    [eventCapacity]wire.Event
	eventSeq                                  uint64
	logQueue                                  chan string
	logStop, logDone                          chan struct{}
	logDropped                                atomic.Uint64
	votePending                               map[int]bool
	committedHash                             string
	commitDigest                              hash.Hash
	recoveryTruncate                          int64
	log                                       []wire.LogEntry
	commitIndex, lastApplied, appliedCommands int
	x                                         int64
	nextIndex, matchIndex                     map[int]int
	wal                                       *os.File
	storageLock                               *os.File
	changed                                   chan struct{}
	electedAt                                 time.Time
	electionMS                                float64
	mu                                        sync.Mutex
	id                                        int
	addr                                      string
	peers                                     map[int]string
	state                                     State
	term                                      int
	votedFor                                  int
	leaderID                                  int
	votes                                     map[int]bool
	deadline                                  time.Time
	electionStarted                           time.Time
	options                                   Options
	statePath                                 string
	logger                                    *log.Logger
	listener                                  net.Listener
	connections                               map[net.Conn]bool
	kicks                                     map[int]chan struct{}
	stop                                      chan struct{}
	stopDone                                  chan struct{}
	errors                                    chan error
	fatalErr                                  error
	started                                   bool
	stopped                                   bool
	wg                                        sync.WaitGroup
}

func NewNode(o Options) (*Node, error) {
	if o.ID < 1 || o.Peers[o.ID] == "" {
		return nil, fmt.Errorf("node %d is missing from configuration", o.ID)
	}
	if o.DataDir == "" {
		return nil, errors.New("data directory is required")
	}
	identity, err := config.FixedIdentity(o.ClusterID, o.Peers)
	if err != nil {
		return nil, err
	}
	if o.ElectionMin == 0 {
		o.ElectionMin = 800 * time.Millisecond
	}
	if o.ElectionJitter == 0 {
		o.ElectionJitter = 800 * time.Millisecond
	}
	if o.HeartbeatInterval == 0 {
		o.HeartbeatInterval = 150 * time.Millisecond
	}
	if o.RPCTimeout == 0 {
		o.RPCTimeout = 350 * time.Millisecond
	}
	if o.BatchSize == 0 {
		o.BatchSize = 128
	}
	if o.BatchSize < 1 || o.BatchSize > 4096 {
		return nil, errors.New("batch size must be 1..4096")
	}
	if o.ElectionMin <= o.HeartbeatInterval+o.RPCTimeout || o.ElectionJitter < 0 || o.HeartbeatInterval <= 0 || o.RPCTimeout <= 0 {
		return nil, errors.New("invalid timing: election minimum must exceed heartbeat interval + RPC timeout")
	}
	if o.Logger == nil {
		o.Logger = log.Default()
	}
	n := &Node{votePending: make(map[int]bool), committedHash: logHash(nil), log: []wire.LogEntry{{}}, changed: make(chan struct{}), id: o.ID, addr: o.Peers[o.ID], peers: make(map[int]string), state: Follower,
		votedFor: -1, leaderID: -1, options: o, logger: o.Logger, stop: make(chan struct{}), stopDone: make(chan struct{}),
		errors: make(chan error, 1), connections: make(map[net.Conn]bool), kicks: make(map[int]chan struct{})}
	n.identity, n.membershipHash = identity, identity.MembershipHash()
	n.instanceID = config.NewClusterID()
	n.logQueue, n.logStop, n.logDone = make(chan string, eventCapacity), make(chan struct{}), make(chan struct{})
	for id, addr := range o.Peers {
		n.peers[id] = addr
		if id != o.ID {
			n.kicks[id] = make(chan struct{}, 1)
		}
	}
	if err := n.loadState(); err != nil {
		return nil, err
	}
	n.startEventOutput()
	n.resetDeadlineLocked()
	return n, nil
}

// Start binds synchronously, so invalid/occupied ports are reported to the caller.
func (n *Node) Start() error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.started || n.stopped {
		return errors.New("node has already been started or stopped")
	}
	server := stdrpc.NewServer()
	if err := server.RegisterName("RaftNode", n); err != nil {
		return err
	}
	listener, err := net.Listen("tcp", n.addr)
	if err != nil {
		return fmt.Errorf("listen on %s: %w", n.addr, err)
	}
	n.listener, n.started = listener, true
	n.resetDeadlineLocked()
	n.eventLocked("started addr=%s members=%d quorum=%d", n.addr, len(n.peers), len(n.peers)/2+1)
	n.wg.Add(2)
	go n.acceptLoop(server)
	go n.electionLoop()
	for id, kick := range n.kicks {
		n.wg.Add(1)
		go n.heartbeatLoop(id, kick)
	}
	return nil
}

func (n *Node) Errors() <-chan error { return n.errors }

func (n *Node) Stop() {
	n.mu.Lock()
	if n.stopped {
		n.mu.Unlock()
		<-n.stopDone
		return
	}
	n.stopped = true
	n.notifyLocked()
	close(n.stop)
	listener := n.listener
	connections := make([]net.Conn, 0, len(n.connections))
	for c := range n.connections {
		connections = append(connections, c)
	}
	n.mu.Unlock()
	if listener != nil {
		listener.Close()
	}
	for _, c := range connections {
		c.Close()
	}
	n.wg.Wait()
	n.mu.Lock()
	if n.wal != nil {
		n.wal.Close()
	}
	if n.storageLock != nil {
		n.storageLock.Close()
	}
	n.eventLocked("stopped")
	close(n.logStop)
	for len(n.logQueue) > 0 {
		select {
		case <-n.logQueue:
			n.logDropped.Add(1)
		default:
		}
	}
	n.mu.Unlock()
	// Ordinary sinks may be uninterruptible io.Writers. Never hold storage hostage.
	select {
	case <-n.logDone:
	case <-time.After(100 * time.Millisecond):
	}
	close(n.stopDone)
}

func (n *Node) acceptLoop(server *stdrpc.Server) {
	defer n.wg.Done()
	for {
		conn, err := n.listener.Accept()
		if err != nil {
			n.mu.Lock()
			if !n.stopped {
				n.failLocked(fmt.Errorf("accept: %w", err))
			}
			n.mu.Unlock()
			return
		}
		n.mu.Lock()
		if n.stopped {
			n.mu.Unlock()
			conn.Close()
			return
		}
		n.connections[conn] = true
		n.wg.Add(1)
		n.mu.Unlock()
		go func() {
			defer n.wg.Done()
			server.ServeConn(conn)
			conn.Close()
			n.mu.Lock()
			delete(n.connections, conn)
			n.mu.Unlock()
		}()
	}
}

func (n *Node) electionLoop() {
	defer n.wg.Done()
	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()
	heartbeat := time.NewTicker(n.options.HeartbeatInterval)
	defer heartbeat.Stop()
	for {
		select {
		case <-n.stop:
			return
		case <-heartbeat.C:
			n.mu.Lock()
			if !n.stopped && n.fatalErr == nil && n.state == Leader {
				n.kickPeersLocked()
			}
			n.mu.Unlock()
		case <-ticker.C:
			n.mu.Lock()
			if !n.stopped && n.fatalErr == nil && n.state != Leader && !time.Now().Before(n.deadline) {
				n.startElectionLocked()
			}
			n.mu.Unlock()
		}
	}
}

func (n *Node) resetDeadlineLocked() {
	n.deadline = time.Now().Add(n.options.ElectionMin + time.Duration(rand.Int63n(int64(n.options.ElectionJitter))))
}

func (n *Node) startElectionLocked() {
	if err := n.persistLocked(n.term+1, n.id); err != nil {
		return
	}
	n.state, n.leaderID = Candidate, -1
	n.votes = map[int]bool{n.id: true}
	n.electionStarted = time.Now()
	n.resetDeadlineLocked()
	n.eventLocked("election_started")
	if len(n.votes) > len(n.peers)/2 {
		n.becomeLeaderLocked()
		return
	}
	args := wire.VoteArgs{ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, Term: n.term, CandidateID: n.id, LastLogIndex: n.lastIndexLocked(), LastLogTerm: n.log[n.lastIndexLocked()].Term}
	for id, addr := range n.peers {
		if id == n.id {
			continue
		}
		if n.votePending[id] {
			continue
		}
		n.votePending[id] = true
		n.wg.Add(1)
		go func(peerID int, address string) {
			defer n.wg.Done()
			var reply wire.VoteReply
			err := wire.Call(address, "RaftNode.RequestVote", &args, &reply, n.options.RPCTimeout)
			n.mu.Lock()
			defer n.mu.Unlock()
			delete(n.votePending, peerID)
			if err == nil {
				n.handleVoteReplyLocked(peerID, args.Term, reply)
			}
		}(id, addr)
	}
}

func (n *Node) handleVoteReplyLocked(peerID, requestTerm int, reply wire.VoteReply) {
	if n.stopped || n.fatalErr != nil {
		return
	}
	if reply.Term > n.term {
		n.followHigherTermLocked(reply.Term)
		return
	}
	if n.state != Candidate || n.term != requestTerm || reply.Term != requestTerm || !reply.VoteGranted {
		return
	}
	n.votes[peerID] = true
	if len(n.votes) > len(n.peers)/2 {
		n.becomeLeaderLocked()
	}
}

func (n *Node) becomeLeaderLocked() {
	last := n.lastIndexLocked()
	if err := n.appendEntriesLocked([]wire.LogEntry{{Index: last + 1, Term: n.term, Command: wire.Command{Op: "noop"}}}); err != nil {
		return
	}
	n.state, n.leaderID = Leader, n.id
	n.nextIndex, n.matchIndex = make(map[int]int), make(map[int]int)
	for id := range n.peers {
		n.nextIndex[id] = last + 1
	}
	n.matchIndex[n.id] = n.lastIndexLocked()
	n.electedAt = time.Now()
	n.electionMS = float64(time.Since(n.electionStarted).Microseconds()) / 1000
	n.eventLocked("leader_elected votes=%d/%d election_ms=%.3f index=%d", len(n.votes), len(n.peers), n.electionMS, n.lastIndexLocked())
	n.notifyLocked()
	n.advanceCommitLocked()
	n.kickPeersLocked()
}

func (n *Node) followHigherTermLocked(term int) error {
	if err := n.persistLocked(term, -1); err != nil {
		return err
	}
	n.state, n.leaderID, n.votes = Follower, -1, nil
	n.notifyLocked()
	n.kickPeersLocked()
	n.eventLocked("higher_term_observed")
	return nil
}

func (n *Node) RequestVote(args *wire.VoteArgs, reply *wire.VoteReply) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if err := n.checkIdentity(args.ClusterID, args.MembershipHash); err != nil {
		return err
	}
	if err := n.availableLocked(); err != nil {
		return err
	}
	if _, ok := n.peers[args.CandidateID]; !ok {
		return errors.New("candidate is not a cluster member")
	}
	if args.Term > n.term {
		if err := n.followHigherTermLocked(args.Term); err != nil {
			return err
		}
	}
	reply.Term, reply.VoteGranted = n.term, false
	if args.Term < n.term || (n.votedFor != -1 && n.votedFor != args.CandidateID) {
		return nil
	}
	last := n.log[n.lastIndexLocked()]
	if args.LastLogTerm < last.Term || (args.LastLogTerm == last.Term && args.LastLogIndex < last.Index) {
		return nil
	}
	if n.votedFor != args.CandidateID {
		if err := n.persistLocked(n.term, args.CandidateID); err != nil {
			return err
		}
		n.eventLocked("vote_granted candidate=%d", args.CandidateID)
	}
	n.resetDeadlineLocked()
	reply.VoteGranted = true
	return nil
}

func (n *Node) heartbeatLoop(peerID int, kick <-chan struct{}) {
	defer n.wg.Done()
	var client wire.PeerClient
	defer client.Close()
	for {
		select {
		case <-n.stop:
			return
		case <-kick:
		}
		for {
			n.mu.Lock()
			if n.stopped || n.fatalErr != nil || n.state != Leader {
				n.mu.Unlock()
				client.Close()
				break
			}
			next := n.nextIndex[peerID]
			end := min(next+n.options.BatchSize, len(n.log))
			args := wire.AppendEntriesArgs{ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, Term: n.term, LeaderID: n.id, PrevLogIndex: next - 1, PrevLogTerm: n.log[next-1].Term, LeaderCommit: n.commitIndex,
				Entries: append([]wire.LogEntry(nil), n.log[next:end]...)}
			n.mu.Unlock()
			var reply wire.AppendEntriesReply
			if err := client.Call(n.peers[peerID], "RaftNode.AppendEntries", &args, &reply, n.options.RPCTimeout); err != nil {
				break
			}
			n.mu.Lock()
			again := n.handleAppendReplyLocked(peerID, args, reply)
			n.mu.Unlock()
			if !again {
				break
			}
		}
	}
}

func (n *Node) Heartbeat(args *wire.HeartbeatArgs, reply *wire.HeartbeatReply) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if err := n.checkIdentity(args.ClusterID, args.MembershipHash); err != nil {
		return err
	}
	if err := n.availableLocked(); err != nil {
		return err
	}
	if _, ok := n.peers[args.LeaderID]; !ok {
		return errors.New("leader is not a cluster member")
	}
	if args.Term > n.term {
		if err := n.followHigherTermLocked(args.Term); err != nil {
			return err
		}
	}
	reply.Term, reply.Accepted = n.term, false
	if args.Term < n.term {
		return nil
	}
	changed := n.state != Follower || n.leaderID != args.LeaderID
	n.state, n.leaderID, n.votes = Follower, args.LeaderID, nil
	n.resetDeadlineLocked()
	if changed {
		n.notifyLocked()
		n.kickPeersLocked()
		n.eventLocked("leader_observed leader=%d", args.LeaderID)
	}
	reply.Accepted = true
	return nil
}

func (n *Node) Status(args *wire.StatusArgs, reply *wire.StatusReply) error {
	if args.Summary && args.TargetIndex != 0 {
		return errors.New("summary status cannot verify a historical prefix")
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	last := n.log[n.lastIndexLocked()]
	fullHash := n.committedHash
	if !args.Summary && n.commitIndex != last.Index {
		fullHash = logHash(n.log[1:])
	}
	if args.Summary {
		fullHash = ""
	}
	*reply = wire.StatusReply{EventSeq: n.eventSeq, DroppedEvents: n.logDropped.Load(), ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, InstanceID: n.instanceID, Revision: n.revision, ID: n.id, State: string(n.state), Term: n.term, LeaderID: n.leaderID, VotedFor: n.votedFor,
		LastLogIndex: last.Index, LastLogTerm: last.Term, CommitIndex: n.commitIndex, LastApplied: n.lastApplied,
		CommittedCommands: n.appliedCommands, AppliedCommands: n.appliedCommands, X: n.x,
		LogHash: fullHash, CommittedHash: n.committedHash, ElectionMS: n.electionMS}
	if n.state == Leader {
		reply.LeaderAgeMS = float64(time.Since(n.electedAt).Microseconds()) / 1000
	}
	if n.fatalErr != nil {
		reply.Error = n.fatalErr.Error()
	}
	if args.Summary {
		return nil
	}
	target := args.TargetIndex
	if target == 0 {
		target = n.commitIndex
	}
	reply.TargetIndex = target
	if target >= 0 && target <= n.commitIndex {
		reply.TargetAvailable = true
		if target == n.commitIndex {
			reply.TargetHash = n.committedHash
			reply.TargetX = n.x
		} else {
			reply.TargetHash = logHash(n.log[1 : target+1])
			for _, entry := range n.log[1 : target+1] {
				reply.TargetX = applyCommand(reply.TargetX, entry.Command)
			}
		}
	}
	return nil
}

func (n *Node) checkIdentity(cluster, members string) error {
	if cluster != n.identity.ClusterID || members != n.membershipHash {
		return errors.New("cluster/member identity mismatch")
	}
	return nil
}

func (n *Node) availableLocked() error {
	if n.stopped {
		return errors.New("node stopped")
	}
	return n.fatalErr
}

func (n *Node) failLocked(err error) {
	if n.fatalErr != nil {
		return
	}
	n.fatalErr, n.state, n.leaderID = err, Follower, -1
	n.notifyLocked()
	n.kickPeersLocked()
	n.eventLocked("fatal_error error=%q", err)
	n.errors <- err
}
