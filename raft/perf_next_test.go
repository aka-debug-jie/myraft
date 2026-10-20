package raft

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math"
	"sync"
	"testing"

	wire "myraft/rpc"
)

func TestHashEncodingRemainsJSONLines(t *testing.T) {
	entries := []wire.LogEntry{
		entry(1, 1, "noop", 0), entry(2, 1, "add", math.MinInt64),
		entry(3, 2, "sub", math.MaxInt64), entry(4, 2, "mul", -3),
		entry(5, 2, "div", -1), entry(6, 3, "mod", 7),
	}
	for count := range len(entries) + 1 {
		h := sha256.New()
		for _, e := range entries[:count] {
			b, err := json.Marshal(e)
			if err != nil {
				t.Fatal(err)
			}
			h.Write(b)
			h.Write([]byte{'\n'})
		}
		if got := logHash(entries[:count]); got != hex.EncodeToString(h.Sum(nil)) {
			t.Fatalf("JSON line definition changed at %d: %s", count, got)
		}
		batched := sha256.New()
		for start := 0; start < count; start += 2 {
			appendLogHash(batched, entries[start:min(start+2, count)])
		}
		if hex.EncodeToString(batched.Sum(nil)) != hex.EncodeToString(h.Sum(nil)) {
			t.Fatalf("incremental batch boundary changed hash at %d", count)
		}
	}
}

func TestStatusDiagnosticModes(t *testing.T) {
	for _, mode := range []string{"current", "pending"} {
		n := statusFixture(2101, mode)
		var reply wire.StatusReply
		for _, target := range []int{12, 0, n.commitIndex, n.commitIndex + 1, -1} {
			if err := n.Status(&wire.StatusArgs{TargetIndex: target}, &reply); err != nil {
				t.Fatal(err)
			}
			if reply.LogHash != logHash(n.log[1:]) || reply.Revision != n.revision {
				t.Fatal("diagnostic reply does not describe its snapshot")
			}
			if target == 0 {
				target = n.commitIndex
			}
			if available := target >= 0 && target <= n.commitIndex; reply.TargetAvailable != available {
				t.Fatal("incorrect target availability")
			} else if available {
				if reply.TargetHash != logHash(n.log[1:target+1]) {
					t.Fatal("incorrect target hash")
				}
			} else if reply.TargetHash != "" || reply.TargetX != 0 {
				t.Fatal("reused reply retained historical values")
			}
		}
		if err := n.Status(&wire.StatusArgs{Summary: true}, &reply); err != nil || reply.LogHash != "" || reply.TargetAvailable || reply.TargetHash != "" {
			t.Fatalf("summary carried diagnostic fields: %+v %v", reply, err)
		}
		if err := n.Status(&wire.StatusArgs{Summary: true, TargetIndex: 1}, &reply); err == nil {
			t.Fatal("summary must not accept a historical target")
		}
	}
}

func TestStatusSnapshotDuringSuffixReplacement(t *testing.T) {
	n := statusFixture(2101, "pending")
	prefix := n.commitIndex
	a := append([]wire.LogEntry(nil), n.log...)
	b := append([]wire.LogEntry(nil), n.log...)
	for i := prefix + 1; i < len(b); i++ {
		b[i].Term++
		b[i].Command = wire.Command{Op: "sub", Value: int64(i)}
	}
	wantA, wantB := logHash(a[1:]), logHash(b[1:])
	history := prefix / 2
	wantHistory := logHash(a[1 : history+1])
	var wantX int64
	for _, e := range a[1 : history+1] {
		wantX = applyCommand(wantX, e.Command)
	}
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 500; i++ {
			n.mu.Lock()
			source := a
			if i%2 == 0 {
				source = b
			}
			// Reuse the backing array, just as truncation followed by append can.
			copy(n.log[prefix+1:], source[prefix+1:])
			n.revision++
			n.mu.Unlock()
		}
	}()
	defer wg.Wait()
	for range 40 {
		var reply wire.StatusReply
		if err := n.Status(&wire.StatusArgs{TargetIndex: history}, &reply); err != nil {
			t.Fatal(err)
		}
		expected := wantA
		if reply.Revision%2 == 1 {
			expected = wantB
		}
		if reply.LogHash != expected {
			t.Fatal("Status mixed different suffix revisions")
		}
		if reply.TargetHash != wantHistory || reply.TargetX != wantX || reply.CommitIndex != prefix {
			t.Fatalf("Status changed the committed snapshot: %+v", reply)
		}
	}
}

// Both variants encode precisely the same JSON lines. This isolates interface
// boxing from disk, replication and state-machine work.
func BenchmarkEntryHashEncoding(b *testing.B) {
	entries := benchmarkEntries(21010)
	for _, pointer := range []bool{false, true} {
		name := "value"
		if pointer {
			name = "pointer"
		}
		b.Run(name, func(b *testing.B) {
			b.ReportAllocs()
			for range b.N {
				h := sha256.New()
				enc := json.NewEncoder(h)
				for i := range entries {
					if pointer {
						_ = enc.Encode(&entries[i])
					} else {
						_ = enc.Encode(entries[i])
					}
				}
			}
		})
	}
}
