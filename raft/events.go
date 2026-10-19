package raft

import (
	"fmt"
	"strings"
	"time"

	wire "myraft/rpc"
)

const eventCapacity = 256

func (n *Node) eventLocked(format string, args ...any) {
	n.eventSeq++
	message := fmt.Sprintf(format, args...)
	name, _, _ := strings.Cut(message, " ")
	e := wire.Event{Seq: n.eventSeq, At: time.Now().UTC(), NodeID: n.id, Term: n.term, Role: string(n.state), Index: n.lastIndexLocked(), Name: name, Message: message}
	n.events[(e.Seq-1)%eventCapacity] = e
	select {
	case n.logQueue <- fmt.Sprintf("node=%d term=%d role=%s | %s", n.id, n.term, n.state, message):
	default:
		n.logDropped.Add(1)
	}
}

func (n *Node) startEventOutput() {
	go func() {
		defer close(n.logDone)
		for {
			select {
			case <-n.logStop:
				return
			case message := <-n.logQueue:
				select {
				case <-n.logStop:
					n.logDropped.Add(1)
					return
				default:
				}
				n.logger.Print(message)
			}
		}
	}()
}

func (n *Node) EventRange(args *wire.EventArgs, reply *wire.EventReply) error {
	n.rpcCalls.Add(1)
	limit := args.Limit
	if limit == 0 {
		limit = 64
	}
	if limit < 1 || limit > eventCapacity {
		return fmt.Errorf("event limit must be 1..256")
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	first := uint64(1)
	if n.eventSeq >= eventCapacity {
		first = n.eventSeq - eventCapacity + 1
	}
	*reply = wire.EventReply{NodeID: n.id, ClusterID: n.identity.ClusterID, InstanceID: n.instanceID, LastSeq: n.eventSeq, Gap: args.After+1 < first, Dropped: n.logDropped.Load()}
	for seq := max(first, args.After+1); seq <= n.eventSeq && len(reply.Events) < limit; seq++ {
		reply.Events = append(reply.Events, n.events[(seq-1)%eventCapacity])
	}
	return nil
}

func (n *Node) LogRange(args *wire.LogRangeArgs, reply *wire.LogRangeReply) error {
	n.rpcCalls.Add(1)
	limit := args.Limit
	if limit == 0 {
		limit = 128
	}
	if args.From < 1 || limit < 1 || limit > 256 {
		return fmt.Errorf("from must be positive; limit 1..256")
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	if err := n.availableLocked(); err != nil {
		return err
	}
	*reply = wire.LogRangeReply{NodeID: n.id, ClusterID: n.identity.ClusterID, MembershipHash: n.membershipHash, InstanceID: n.instanceID, Term: n.term, Revision: n.revision, From: args.From, Next: args.From, LastLogIndex: n.lastIndexLocked(), CommitIndex: n.commitIndex, LastApplied: n.lastApplied}
	if args.From <= n.lastIndexLocked() {
		end := min(args.From+limit, len(n.log))
		reply.Entries = append([]wire.LogEntry(nil), n.log[args.From:end]...)
		reply.Next = end
		reply.Truncated = end < len(n.log)
	}
	return nil
}
