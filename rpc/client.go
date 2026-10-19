package rpc

import (
	"context"
	"errors"
	"fmt"
	"myraft/config"
	"sync"
	"time"
)

func QueryStatuses(c config.Config, args StatusArgs, deadline time.Time) []StatusReply {
	return QueryStatusesContext(context.Background(), c, args, deadline)
}

func QueryStatusesContext(ctx context.Context, c config.Config, args StatusArgs, deadline time.Time) []StatusReply {
	states := make([]StatusReply, len(c.Nodes))
	jobs := make(chan int, len(c.Nodes))
	for i := range c.Nodes {
		jobs <- i
	}
	close(jobs)
	var wg sync.WaitGroup
	for worker := 0; worker < min(16, len(c.Nodes)); worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				node := c.Nodes[i]
				s := StatusReply{ID: node.ID}
				left := min(time.Second, time.Until(deadline))
				if left <= 0 {
					s.Error = "status deadline exceeded"
				} else if err := CallContext(ctx, node.Addr, "RaftNode.Status", &args, &s, left); err != nil {
					s = StatusReply{ID: node.ID, Error: err.Error()}
				}
				if s.Error == "" && c.ClusterID != "" && s.ClusterID != c.ClusterID {
					s.Error = "cluster identity mismatch"
				}
				if s.Error == "" && s.ID != node.ID {
					s = StatusReply{ID: node.ID, Error: fmt.Sprintf("endpoint returned node %d; expected %d", s.ID, node.ID)}
				}
				states[i] = s
			}
		}()
	}
	wg.Wait()
	return states
}

func VerifyStatuses(states []StatusReply, target int) error {
	if len(states) == 0 {
		return fmt.Errorf("no nodes")
	}
	first := states[0]
	for _, s := range states {
		if s.Error != "" {
			return fmt.Errorf("node %d: %s", s.ID, s.Error)
		}
		if s.LastApplied != s.CommitIndex || s.CommitIndex != s.LastLogIndex {
			return fmt.Errorf("node %d has uncommitted or unapplied entries", s.ID)
		}
		if s.ClusterID != first.ClusterID || s.MembershipHash != first.MembershipHash {
			return fmt.Errorf("node %d cluster identity differs", s.ID)
		}
		if s.LogHash == "" || s.CommittedHash == "" || s.LastLogIndex != first.LastLogIndex || s.CommitIndex != first.CommitIndex || s.LogHash != first.LogHash || s.CommittedHash != first.CommittedHash || s.X != first.X || s.AppliedCommands != first.AppliedCommands || s.CommittedCommands != first.CommittedCommands {
			return fmt.Errorf("node %d log/state differs", s.ID)
		}
		if target > 0 && (!s.TargetAvailable || s.TargetIndex != target || s.TargetHash != first.TargetHash || s.TargetX != first.TargetX) {
			return fmt.Errorf("node %d has not matched target %d", s.ID, target)
		}
	}
	return nil
}

var ErrOutcomeUnknown = errors.New("submission outcome unknown; do not retry automatically")

// Discovery observes local roles, not a quorum or a linearizable leadership lease.
func DiscoverLeader(ctx context.Context, c config.Config, deadline time.Time) (StatusReply, error) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	jobs := make(chan config.Node, len(c.Nodes))
	for _, n := range c.Nodes {
		jobs <- n
	}
	close(jobs)
	results := make(chan StatusReply, len(c.Nodes))
	for i := 0; i < min(8, len(c.Nodes)); i++ {
		go func() {
			for node := range jobs {
				if ctx.Err() != nil {
					return
				}
				var s StatusReply
				err := CallContext(ctx, node.Addr, "RaftNode.Status", &StatusArgs{Summary: true}, &s, min(time.Second, time.Until(deadline)))
				if err != nil || s.ID != node.ID || (c.ClusterID != "" && s.ClusterID != c.ClusterID) {
					s = StatusReply{ID: node.ID, Error: "unavailable or identity mismatch"}
				}
				select {
				case results <- s:
				case <-ctx.Done():
					return
				}
			}
		}()
	}
	timer := time.NewTimer(max(0, time.Until(deadline)))
	defer timer.Stop()
	for range c.Nodes {
		select {
		case s := <-results:
			if s.Error == "" && s.State == "Leader" && s.LeaderID == s.ID {
				return s, nil
			}
		case <-timer.C:
			return StatusReply{}, context.DeadlineExceeded
		case <-ctx.Done():
			return StatusReply{}, ctx.Err()
		}
	}
	return StatusReply{}, fmt.Errorf("no leader observed")
}

func SubmitGenerated(ctx context.Context, c config.Config, count int, seed int64, deadline time.Time) (GenerateReply, error) {
	if c.ClusterID == "" {
		return GenerateReply{}, fmt.Errorf("explicit cluster_id required for submission")
	}
	peers, err := c.Peers()
	if err != nil {
		return GenerateReply{}, err
	}
	for time.Until(deadline) > 0 && ctx.Err() == nil {
		leader, err := DiscoverLeader(ctx, c, deadline)
		if err != nil {
			select {
			case <-ctx.Done():
				return GenerateReply{}, ctx.Err()
			case <-time.After(min(100*time.Millisecond, max(0, time.Until(deadline)))):
			}
			continue
		}
		left := time.Until(deadline)
		if left < time.Millisecond {
			break
		}
		var reply GenerateReply
		args := GenerateArgs{ClusterID: c.ClusterID, Count: count, Seed: seed, TimeoutMS: int(left / time.Millisecond)}
		if err := CallContext(ctx, peers[leader.ID], "RaftNode.Generate", &args, &reply, left); err != nil {
			reply.Error = fmt.Sprintf("%s: %v", ErrOutcomeUnknown, err)
			return reply, fmt.Errorf("%w: %v", ErrOutcomeUnknown, err)
		}
		if reply.Accepted && reply.Committed && reply.Error == "" {
			return reply, nil
		}
		if !reply.Accepted && reply.Error == "not leader" {
			select {
			case <-ctx.Done():
				return reply, ctx.Err()
			case <-time.After(min(100*time.Millisecond, max(0, time.Until(deadline)))):
			}
			continue
		}
		if reply.Accepted {
			return reply, fmt.Errorf("%w: %s", ErrOutcomeUnknown, reply.Error)
		}
		return reply, fmt.Errorf("submission rejected: %s", reply.Error)
	}
	r := GenerateReply{Error: "leader discovery timed out"}
	return r, fmt.Errorf("%s", r.Error)
}
