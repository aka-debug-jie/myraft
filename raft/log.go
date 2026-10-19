package raft

import (
	"errors"
	"fmt"
	"sort"
	"time"

	wire "myraft/rpc"
)

func (n *Node) lastIndexLocked() int { return len(n.log) - 1 }
func (n *Node) notifyLocked()        { close(n.changed); n.changed = make(chan struct{}) }
func (n *Node) kickPeersLocked() {
	for _, kick := range n.kicks {
		select {
		case kick <- struct{}{}:
		default:
		}
	}
}

func (n *Node) AppendEntries(args *wire.AppendEntriesArgs, reply *wire.AppendEntriesReply) error {
	n.mu.Lock()
	defer n.mu.Unlock()
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
	*reply = wire.AppendEntriesReply{Term: n.term, ConflictIndex: n.lastIndexLocked() + 1}
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
	if args.PrevLogIndex < 0 || args.LeaderCommit < 0 {
		return errors.New("negative append index")
	}
	if args.PrevLogIndex > n.lastIndexLocked() {
		return nil
	}
	if n.log[args.PrevLogIndex].Term != args.PrevLogTerm {
		conflict := args.PrevLogIndex
		for conflict > 1 && n.log[conflict-1].Term == n.log[args.PrevLogIndex].Term {
			conflict--
		}
		reply.ConflictIndex = max(1, conflict)
		return nil
	}
	previousTerm := args.PrevLogTerm
	for i, e := range args.Entries {
		if e.Index != args.PrevLogIndex+i+1 || e.Term < previousTerm || e.Term > args.Term || e.Term < 1 {
			return fmt.Errorf("invalid append entry at %d", e.Index)
		}
		if err := validateCommand(e.Command); err != nil {
			return err
		}
		previousTerm = e.Term
	}
	for i, e := range args.Entries {
		if e.Index > n.lastIndexLocked() || n.log[e.Index].Term != e.Term {
			if err := n.replaceLogLocked(e.Index, args.Entries[i:]); err != nil {
				return err
			}
			n.eventLocked("log_replicated from=%d index=%d", e.Index, n.lastIndexLocked())
			break
		}
	}
	// Only this request's matching prefix is established, not an arbitrary local tail.
	matched := args.PrevLogIndex + len(args.Entries)
	if err := n.commitLocked(min(args.LeaderCommit, matched)); err != nil {
		return err
	}
	reply.Success = true
	if len(args.Entries) > 0 && n.commitIndex == matched {
		n.eventLocked("log_caught_up index=%d", matched)
	}
	return nil
}

func (n *Node) handleAppendReplyLocked(peerID int, args wire.AppendEntriesArgs, reply wire.AppendEntriesReply) bool {
	if n.stopped || n.fatalErr != nil {
		return false
	}
	if reply.Term > n.term {
		n.followHigherTermLocked(reply.Term)
		return false
	}
	if n.state != Leader || n.term != args.Term || reply.Term != args.Term {
		return false
	}
	if !reply.Success {
		next := max(1, min(n.nextIndex[peerID]-1, reply.ConflictIndex))
		changed := next < n.nextIndex[peerID]
		n.nextIndex[peerID] = next
		return changed
	}
	matched := args.PrevLogIndex + len(args.Entries)
	progress := matched > n.matchIndex[peerID]
	n.matchIndex[peerID] = max(n.matchIndex[peerID], matched)
	n.nextIndex[peerID] = n.matchIndex[peerID] + 1
	if progress {
		n.advanceCommitLocked()
	}
	return n.availableLocked() == nil && n.nextIndex[peerID] <= n.lastIndexLocked()
}

func (n *Node) advanceCommitLocked() {
	if n.commitIndex == n.lastIndexLocked() {
		return
	}
	matches := make([]int, 0, len(n.peers))
	for id := range n.peers {
		if id == n.id {
			matches = append(matches, n.lastIndexLocked())
		} else {
			matches = append(matches, n.matchIndex[id])
		}
	}
	sort.Ints(matches)
	index := matches[len(matches)-(len(matches)/2+1)]
	if index > n.commitIndex && n.log[index].Term == n.term {
		if n.commitLocked(index) == nil {
			n.kickPeersLocked()
		}
	}
}

func (n *Node) Generate(args *wire.GenerateArgs, reply *wire.GenerateReply) error {
	*reply = wire.GenerateReply{}
	if args.Count < 1 || args.Count > 100000 || args.TimeoutMS < 1 || args.TimeoutMS > 600000 {
		reply.Error = "count must be 1..100000 and timeout 1..600000 ms"
		return nil
	}
	commands := generateCommands(args.Count, args.Seed)
	n.mu.Lock()
	if err := n.availableLocked(); err != nil {
		n.mu.Unlock()
		return err
	}
	reply.Term, reply.LeaderID = n.term, n.leaderID
	if n.state != Leader {
		reply.Error = "not leader"
		n.mu.Unlock()
		return nil
	}
	term, first := n.term, n.lastIndexLocked()+1
	entries := make([]wire.LogEntry, len(commands))
	for i, c := range commands {
		entries[i] = wire.LogEntry{Index: first + i, Term: term, Command: c}
	}
	if err := n.appendEntriesLocked(entries); err != nil {
		n.mu.Unlock()
		return err
	}
	reply.Accepted, reply.FirstIndex, reply.LastIndex, reply.Commands = true, first, n.lastIndexLocked(), len(entries)
	n.eventLocked("log_appended from=%d index=%d commands=%d", first, reply.LastIndex, len(entries))
	n.matchIndex[n.id] = n.lastIndexLocked()
	n.advanceCommitLocked()
	n.kickPeersLocked()
	timer := time.NewTimer(time.Duration(args.TimeoutMS) * time.Millisecond)
	defer timer.Stop()
	for {
		if err := n.availableLocked(); err != nil {
			reply.Error = err.Error()
			n.mu.Unlock()
			return nil
		}
		// A committed index alone is insufficient: a new leader may have overwritten this request.
		if n.lastIndexLocked() >= reply.LastIndex && n.log[reply.LastIndex].Term == term && n.commitIndex >= reply.LastIndex {
			reply.Committed = true
			n.mu.Unlock()
			return nil
		}
		if n.state != Leader || n.term != term {
			reply.Error = "leadership changed; outcome not confirmed"
			n.mu.Unlock()
			return nil
		}
		changed := n.changed
		n.mu.Unlock()
		select {
		case <-timer.C:
			reply.Error = "commit timed out; outcome unknown"
			return nil
		case <-changed:
		}
		n.mu.Lock()
	}
}
