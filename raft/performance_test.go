package raft

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"testing"

	wire "myraft/rpc"
)

func benchmarkEntries(count int) []wire.LogEntry {
	entries := make([]wire.LogEntry, count)
	for i, c := range generateCommands(count, 42) {
		entries[i] = entry(i+1, 1, c.Op, c.Value)
	}
	return entries
}

// Identical JSON.Encode bytes; separates hashing from synchronous metadata writes.
func BenchmarkHashPrefixes(b *testing.B) {
	for _, count := range []int{2101, 21010} {
		entries := benchmarkEntries(count)
		for _, incremental := range []bool{false, true} {
			b.Run(fmt.Sprintf("%d/incremental_%t", count, incremental), func(b *testing.B) {
				b.ReportAllocs()
				for i := 0; i < b.N; i++ {
					h := sha256.New()
					enc := json.NewEncoder(h)
					for start := 0; start < count; start += 128 {
						end := min(start+128, count)
						if incremental {
							for _, e := range entries[start:end] {
								_ = enc.Encode(e)
							}
							_ = hex.EncodeToString(h.Sum(nil))
						} else {
							_ = logHash(entries[:end])
						}
					}
				}
			})
		}
	}
}

func BenchmarkCommitBatches(b *testing.B) {
	for _, count := range []int{2101, 21010} {
		for _, mode := range []string{"sync-only", "commit"} {
			b.Run(fmt.Sprintf("%d/%s", count, mode), func(b *testing.B) {
				b.ReportAllocs()
				for i := 0; i < b.N; i++ {
					b.StopTimer()
					n, err := NewNode(Options{ID: 1, Peers: map[int]string{1: "127.0.0.1:1"}, DataDir: b.TempDir(), Logger: log.New(io.Discard, "", 0)})
					if err != nil {
						b.Fatal(err)
					}
					if err = n.persistLocked(1, -1); err != nil {
						b.Fatal(err)
					}
					if err = n.appendEntriesLocked(benchmarkEntries(count)); err != nil {
						b.Fatal(err)
					}
					digest := logHash(n.log[1:])
					b.StartTimer()
					for end := min(128, count); ; end = min(end+128, count) {
						if mode == "commit" {
							err = n.commitLocked(end)
						} else {
							err = n.saveState(persistentState{1, 1, -1, end, digest})
						}
						if err != nil {
							b.Fatal(err)
						}
						if end == count {
							break
						}
					}
					b.StopTimer()
					n.Stop()
					b.StartTimer()
				}
			})
		}
	}
}
