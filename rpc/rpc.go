// Package rpc defines the Raft wire format and bounded TCP calls.
package rpc

import (
	"context"
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
type VoteArgs struct {
	Term, CandidateID, LastLogIndex, LastLogTerm int
	ClusterID, MembershipHash                    string
}
type VoteReply struct {
	Term        int
	VoteGranted bool
}
type AppendEntriesArgs struct {
	ClusterID, MembershipHash                 string
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
type HeartbeatArgs struct {
	Term, LeaderID            int
	ClusterID, MembershipHash string
}
type HeartbeatReply struct {
	Term     int
	Accepted bool
}

type GenerateArgs struct {
	ClusterID string
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
type StatusArgs struct {
	TargetIndex int
	Summary     bool // Monitoring only; no full-log or historical-prefix verification.
}
type StatusReply struct {
	ProcessID         int     `json:"process_id,omitempty"`
	EventSeq          uint64  `json:"event_seq"`
	ClusterID         string  `json:"cluster_id"`
	MembershipHash    string  `json:"membership_hash"`
	InstanceID        string  `json:"instance_id"`
	Revision          uint64  `json:"revision"`
	DroppedEvents     uint64  `json:"dropped_events"`
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

type Event struct {
	Seq     uint64    `json:"seq"`
	At      time.Time `json:"at"`
	NodeID  int       `json:"node_id"`
	Term    int       `json:"term"`
	Role    string    `json:"role"`
	Index   int       `json:"index"`
	Name    string    `json:"name"`
	Message string    `json:"message"`
}
type EventArgs struct {
	After uint64
	Limit int
}
type EventReply struct {
	NodeID     int     `json:"node_id"`
	ClusterID  string  `json:"cluster_id"`
	InstanceID string  `json:"instance_id"`
	LastSeq    uint64  `json:"last_seq"`
	Gap        bool    `json:"gap"`
	Dropped    uint64  `json:"dropped"`
	Events     []Event `json:"events"`
}
type LogRangeArgs struct{ From, Limit int }
type LogRangeReply struct {
	NodeID         int        `json:"node_id"`
	ClusterID      string     `json:"cluster_id"`
	MembershipHash string     `json:"membership_hash"`
	InstanceID     string     `json:"instance_id"`
	Term           int        `json:"term"`
	Revision       uint64     `json:"revision"`
	From           int        `json:"from"`
	Next           int        `json:"next"`
	LastLogIndex   int        `json:"last_log_index"`
	CommitIndex    int        `json:"commit_index"`
	LastApplied    int        `json:"last_applied"`
	Truncated      bool       `json:"truncated"`
	Entries        []LogEntry `json:"entries"`
}

// The deadline includes both connection and response waits.
func Call(addr, method string, args, reply any, timeout time.Duration) error {
	return CallContext(context.Background(), addr, method, args, reply, timeout)
}

func CallContext(ctx context.Context, addr, method string, args, reply any, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	if end, ok := ctx.Deadline(); ok && end.Before(deadline) {
		deadline = end
	}
	dialer := net.Dialer{Timeout: timeout}
	conn, err := dialer.DialContext(ctx, "tcp", addr)
	if err != nil {
		return err
	}
	if err = conn.SetDeadline(deadline); err != nil {
		conn.Close()
		return err
	}
	client := stdrpc.NewClient(conn)
	defer client.Close()
	stopCancel := context.AfterFunc(ctx, func() { conn.Close() })
	defer stopCancel()
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
