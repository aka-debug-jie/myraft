package raft

import (
	"fmt"
	wire "myraft/rpc"
	"runtime"
	"sync/atomic"
	"testing"
	"time"
)

func statusFixture(count int, mode string) *Node {
	entries := benchmarkEntries(count)
	commit := count
	if mode == "pending" || mode == "summary" {
		commit -= 128
	}
	n := &Node{id: 1, term: 1, state: Leader, leaderID: 1, log: append([]wire.LogEntry{{}}, entries...), commitIndex: commit, lastApplied: commit, appliedCommands: commit, committedHash: logHash(entries[:commit])}
	for _, e := range entries[:commit] {
		n.x = applyCommand(n.x, e.Command)
	}
	return n
}
func BenchmarkStatusRead(b *testing.B) {
	for _, count := range []int{2101, 21010} {
		for _, mode := range []string{"current", "pending", "history", "summary"} {
			b.Run(fmt.Sprintf("%d/%s", count, mode), func(b *testing.B) {
				n := statusFixture(count, mode)
				args := wire.StatusArgs{Summary: mode == "summary"}
				if mode == "history" {
					args.TargetIndex = count / 2
				}
				var reply wire.StatusReply
				b.ReportAllocs()
				b.ResetTimer()
				for i := 0; i < b.N; i++ {
					n.Status(&args, &reply)
				}
			})
		}
	}
}

// A minimal writer measures lock admission only, not disk or RPC write latency.
func BenchmarkStatusContention(b *testing.B)  { benchmarkStatusContention(b, false) }
func BenchmarkSummaryContention(b *testing.B) { benchmarkStatusContention(b, true) }
func benchmarkStatusContention(b *testing.B, summary bool) {
	n := statusFixture(21010, "pending")
	stop, done := make(chan struct{}), make(chan struct{})
	var waitNS, writes atomic.Int64
	go func() {
		defer close(done)
		for {
			select {
			case <-stop:
				return
			default:
			}
			start := time.Now()
			n.mu.Lock()
			waitNS.Add(time.Since(start).Nanoseconds())
			n.mu.Unlock()
			writes.Add(1)
			runtime.Gosched()
		}
	}()
	var reply wire.StatusReply
	b.ReportAllocs()
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		n.Status(&wire.StatusArgs{Summary: summary}, &reply)
	}
	b.StopTimer()
	close(stop)
	<-done
	if writes.Load() > 0 {
		b.ReportMetric(float64(waitNS.Load())/float64(writes.Load()), "writer-wait-ns")
	}
}
