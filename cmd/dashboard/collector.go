package main

import (
	"context"
	"sync"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

func (d *dashboard) collectLoop() {
	defer d.wg.Done()
	for {
		d.collectRound()
		timer := time.NewTimer(d.opts.Interval)
		select {
		case <-d.ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
		}
	}
}

func (d *dashboard) collectRound() {
	d.mu.Lock()
	s, gen := d.active, d.generation
	prior := d.snap
	cursors := make(map[int]eventCursor, len(d.eventCursors))
	for id, c := range d.eventCursors {
		cursors[id] = c
	}
	d.mu.Unlock()
	if s == nil {
		return
	}
	ctx, cancel := context.WithTimeout(d.ctx, 2*time.Second)
	defer cancel()
	peers, _ := s.Config.Peers()
	identity, _ := config.FixedIdentity(s.Config.ClusterID, peers)
	started := time.Now().UTC()
	samples := make([]nodeSample, len(s.Config.Nodes))
	nodeEvents := make([]wire.EventReply, len(samples))
	eventErrors := make([]string, len(samples))
	jobs := make(chan int, len(samples))
	// Rotate the first worker batch so a slow prefix cannot starve later members.
	start := 0
	if len(samples) > 0 {
		start = int(prior.Seq%uint64(len(samples))) * 8 % len(samples)
	}
	for i := range samples {
		jobs <- (start + i) % len(samples)
	}
	close(jobs)
	var wg sync.WaitGroup
	for i := 0; i < min(8, len(samples)); i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				node := s.Config.Nodes[i]
				item := nodeSample{ID: node.ID, SampledAt: time.Now().UTC()}
				if ctx.Err() != nil {
					item.Error = "本轮采样预算已耗尽，未尝试连接"
					samples[i] = item
					continue
				}
				var status wire.StatusReply
				d.monitorRPCs.Add(1)
				err := wire.CallContext(ctx, node.Addr, "RaftNode.Status", &wire.StatusArgs{Summary: true}, &status, 500*time.Millisecond)
				item.SampledAt = time.Now().UTC()
				if err != nil {
					item.Error = err.Error()
				} else {
					item.Reachable = true
					item.IdentityOK = status.ID == node.ID && status.ClusterID == identity.ClusterID && status.MembershipHash == identity.MembershipHash()
					if !item.IdentityOK {
						item.Error = "节点/集群/成员身份不匹配"
					} else {
						status.ProcessID = 0
						item.Status = &status
						item.Error = status.Error
					}
				}
				if item.IdentityOK && status.EventSeq > 0 {
					var after uint64
					if cursor := cursors[node.ID]; cursor.Instance == status.InstanceID {
						after = cursor.Seq
					}
					if after < status.EventSeq && ctx.Err() == nil {
						var events wire.EventReply
						d.monitorRPCs.Add(1)
						if e := wire.CallContext(ctx, node.Addr, "RaftNode.EventRange", &wire.EventArgs{After: after, Limit: 256}, &events, 300*time.Millisecond); e == nil && events.NodeID == node.ID && events.ClusterID == identity.ClusterID && events.InstanceID == status.InstanceID {
							nodeEvents[i] = events
						} else {
							eventErrors[i] = "事件读取失败或身份不符；消费游标未推进"
						}
					}
				}
				samples[i] = item
			}
		}()
	}
	wg.Wait()
	d.mu.Lock()
	defer d.mu.Unlock()
	if d.active == nil || d.active.ID != s.ID || d.generation != gen {
		return
	}
	var signature []any
	for i := range samples {
		n := &samples[i]
		p := d.processes[n.ID]
		n.Owned = p != nil && p.running
		if n.Status != nil {
			signature = append(signature, []any{n.ID, n.Error, n.Status.InstanceID, n.Status.Term, n.Status.Revision, n.Status.CommittedHash})
		} else {
			signature = append(signature, []any{n.ID, n.Error})
		}
		for _, old := range prior.Nodes {
			if old.ID == n.ID && (old.Reachable != n.Reachable || old.IdentityOK != n.IdentityOK) {
				d.emitLocked(consoleEvent{Source: "observation", NodeID: n.ID, Name: "reachability_changed", Message: "可达性观测发生变化；不等同于进程退出确认"})
			}
		}
		batch := nodeEvents[i]
		if eventErrors[i] != "" {
			d.emitLocked(consoleEvent{Source: "observation", NodeID: n.ID, Name: "node_event_read_failed", Message: eventErrors[i]})
		}
		if batch.Gap {
			d.emitLocked(consoleEvent{Source: "observation", NodeID: n.ID, Name: "node_event_gap", Message: "节点事件环存在缺口"})
		}
		for _, e := range batch.Events {
			e := e
			d.emitLocked(consoleEvent{Source: "node", NodeID: n.ID, Name: e.Name, Message: e.Message, NodeEvent: &e})
			d.eventCursors[n.ID] = eventCursor{Instance: batch.InstanceID, Seq: e.Seq}
		}
	}
	d.snap = snapshot{SessionID: s.ID, Generation: gen, Seq: d.snap.Seq + 1, StartedAt: started, CompletedAt: time.Now().UTC(), Nodes: samples, Fingerprint: digestJSON(signature), MonitorRPCs: d.monitorRPCs.Load()}
	if d.currentCheck.State == "passed" && d.currentCheck.Fingerprint != d.snap.Fingerprint {
		d.currentCheck.State = "stale"
	}
	if d.historyCheck.State == "passed" && d.historyCheck.Fingerprint != d.snap.Fingerprint {
		d.historyCheck.State = "stale"
	}
	d.broadcastLocked()
}
