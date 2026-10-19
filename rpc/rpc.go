// Package rpc defines the Raft wire format and bounded TCP calls.
package rpc

import (
	"net"
	stdrpc "net/rpc"
	"time"
)

type Command struct {
	Op    string `json:"op"`
	Value int64  `json:"value"`
}
type LogEntry struct {
	Index   int     `json:"index"`
	Term    int     `json:"term"`
	Command Command `json:"command"`
}
type VoteArgs struct{ Term, CandidateID, LastLogIndex, LastLogTerm int }
type VoteReply struct {
	Term        int
	VoteGranted bool
}
type AppendEntriesArgs struct {
	Term, LeaderID, PrevLogIndex, PrevLogTerm int
	Entries                                   []LogEntry
	LeaderCommit                              int
}
type AppendEntriesReply struct {
	Term          int
	Success       bool
	ConflictIndex int
}

// Kept for old clients; this RPC never acknowledges or commits log entries.
type HeartbeatArgs struct{ Term, LeaderID int }
type HeartbeatReply struct {
	Term     int
	Accepted bool
}

type GenerateArgs struct {
	Count     int
	Seed      int64
	TimeoutMS int
}
type GenerateReply struct {
	Accepted   bool   `json:"accepted"`
	Committed  bool   `json:"committed"`
	LeaderID   int    `json:"leader_id"`
	Term       int    `json:"term"`
	FirstIndex int    `json:"first_index"`
	LastIndex  int    `json:"last_index"`
	Commands   int    `json:"commands"`
	Error      string `json:"error,omitempty"`
}
type StatusArgs struct{ TargetIndex int }
type StatusReply struct {
	ID                int     `json:"id"`
	State             string  `json:"state"`
	Term              int     `json:"term"`
	LeaderID          int     `json:"leader_id"`
	VotedFor          int     `json:"voted_for"`
	LastLogIndex      int     `json:"last_log_index"`
	LastLogTerm       int     `json:"last_log_term"`
	CommitIndex       int     `json:"commit_index"`
	LastApplied       int     `json:"last_applied"`
	CommittedCommands int     `json:"committed_commands"`
	AppliedCommands   int     `json:"applied_commands"`
	X                 int64   `json:"x"`
	LogHash           string  `json:"log_hash"`
	CommittedHash     string  `json:"committed_hash"`
	TargetIndex       int     `json:"target_index"`
	TargetAvailable   bool    `json:"target_available"`
	TargetHash        string  `json:"target_hash"`
	TargetX           int64   `json:"target_x"`
	ElectionMS        float64 `json:"election_ms"`
	LeaderAgeMS       float64 `json:"leader_age_ms"`
	Error             string  `json:"error,omitempty"`
}

// The deadline includes both connection and response waits.
func Call(addr, method string, args, reply any, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	conn, err := net.DialTimeout("tcp", addr, timeout)
	if err != nil {
		return err
	}
	if err = conn.SetDeadline(deadline); err != nil {
		conn.Close()
		return err
	}
	client := stdrpc.NewClient(conn)
	defer client.Close()
	return client.Call(method, args, reply)
}

// PeerClient belongs to one replication worker; it is never called concurrently.
// Reusing the connection avoids a TIME_WAIT socket for every idle heartbeat.
type PeerClient struct {
	conn   net.Conn
	client *stdrpc.Client
}

func (p *PeerClient) Close() {
	if p.client != nil {
		p.client.Close()
		p.client = nil
		p.conn = nil
	}
}
func (p *PeerClient) Call(addr, method string, args, reply any, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	if p.client == nil {
		conn, err := net.DialTimeout("tcp", addr, timeout)
		if err != nil {
			return err
		}
		p.conn, p.client = conn, stdrpc.NewClient(conn)
	}
	if err := p.conn.SetDeadline(deadline); err != nil {
		p.Close()
		return err
	}
	if err := p.client.Call(method, args, reply); err != nil {
		p.Close()
		return err
	}
	// net/rpc's background reader must not time out while this connection is idle.
	if err := p.conn.SetDeadline(time.Time{}); err != nil {
		p.Close()
		return err
	}
	return nil
}
