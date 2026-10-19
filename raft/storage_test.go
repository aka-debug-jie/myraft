package raft

import (
	"encoding/binary"
	"hash/crc32"
	wire "myraft/rpc"
	"os"
	"testing"
)

func TestRecoveryOnlyAppliesCommittedPrefix(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	n := testNode(t, 1, peers, dir)
	seedNode(t, n, 3, []wire.LogEntry{entry(1, 2, "add", 5), entry(2, 3, "mul", 9)}, 1)
	n.Stop()
	n = testNode(t, 1, peers, dir)
	s := snapshot(n)
	if s.LastLogIndex != 2 || s.CommitIndex != 1 || s.LastApplied != 1 || s.X != 5 {
		t.Fatalf("bad recovery %+v", s)
	}
	for i := 0; i < 2; i++ {
		if err := n.commitLocked(2); err != nil {
			t.Fatal(err)
		}
	}
	if s = snapshot(n); s.X != 45 || s.AppliedCommands != 2 {
		t.Fatal("repeated application")
	}
}
func TestWALIncompleteTailAndCorruption(t *testing.T) {
	for _, mode := range []string{"header", "payload", "corrupt"} {
		t.Run(mode, func(t *testing.T) {
			peers, dir := testPeers(t, 3), t.TempDir()
			n := testNode(t, 1, peers, dir)
			seedNode(t, n, 3, []wire.LogEntry{entry(1, 3, "add", 5)}, 1)
			path := n.wal.Name()
			n.Stop()
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			original := len(data)
			switch mode {
			case "header":
				data = append(data, 1, 2, 3)
			case "payload":
				h := make([]byte, 12)
				binary.LittleEndian.PutUint32(h, 100)
				binary.LittleEndian.PutUint32(h[8:], crc32.ChecksumIEEE(h[:8]))
				data = append(data, h...)
				data = append(data, 1, 2, 3)
			case "corrupt":
				data[len(data)-1] ^= 0xff
			}
			if err = os.WriteFile(path, data, 0600); err != nil {
				t.Fatal(err)
			}
			if mode == "corrupt" {
				bad, err := NewNode(Options{ID: 1, Peers: peers, DataDir: dir})
				if err == nil {
					bad.Stop()
					t.Fatal("corruption silently accepted")
				}
				return
			}
			n = testNode(t, 1, peers, dir)
			s := snapshot(n)
			if s.X != 5 || s.CommitIndex != 1 {
				t.Fatalf("bad recovery %+v", s)
			}
			info, err := os.Stat(path)
			if err != nil || info.Size() != int64(original) {
				t.Fatal("tail not truncated")
			}
			if err = n.appendEntriesLocked([]wire.LogEntry{entry(2, 3, "add", 2)}); err != nil {
				t.Fatal(err)
			}
			if err = n.commitLocked(2); err != nil {
				t.Fatal(err)
			}
			n.Stop()
			n = testNode(t, 1, peers, dir)
			if snapshot(n).X != 7 {
				t.Fatal("append after recovery lost")
			}
		})
	}
}
func TestStorageFailuresDoNotAcknowledgeOrApply(t *testing.T) {
	for _, mode := range []string{"append", "commit"} {
		t.Run(mode, func(t *testing.T) {
			peers, dir := testPeers(t, 3), t.TempDir()
			n := testNode(t, 1, peers, dir)
			seedNode(t, n, 3, nil, 0)
			if mode == "append" {
				n.wal.Close()
			} else {
				n.statePath = dir
			}
			var r wire.AppendEntriesReply
			err := n.AppendEntries(&wire.AppendEntriesArgs{Term: 3, LeaderID: 2, Entries: []wire.LogEntry{entry(1, 3, "add", 9)}, LeaderCommit: 1}, &r)
			s := snapshot(n)
			if err == nil || r.Success || s.Error == "" || s.CommitIndex != 0 || s.LastApplied != 0 || s.X != 0 {
				t.Fatalf("failure acknowledged %+v %+v %v", r, s, err)
			}
			n.Stop()
			n = testNode(t, 1, peers, dir)
			if s = snapshot(n); s.CommitIndex != 0 || s.X != 0 {
				t.Fatal("failed commit persisted")
			}
		})
	}
}
func TestStateMachineArithmetic(t *testing.T) {
	x := int64(0)
	for _, c := range []wire.Command{{Op: "add", Value: 7}, {Op: "sub", Value: 10}, {Op: "mul", Value: 3}, {Op: "div", Value: 2}, {Op: "mod", Value: 3}} {
		if err := validateCommand(c); err != nil {
			t.Fatal(err)
		}
		x = applyCommand(x, c)
	}
	if x != -1 {
		t.Fatalf("Go signed arithmetic produced %d", x)
	}
	for _, c := range []wire.Command{{Op: "div"}, {Op: "mod"}, {Op: "invalid"}} {
		if validateCommand(c) == nil {
			t.Fatal("bad command accepted")
		}
	}
}

func TestCommittedReplacementCannotResurrectOldTail(t *testing.T) {
	for _, damage := range []string{"length", "missing_record", "torn_payload", "empty_wal"} {
		t.Run(damage, func(t *testing.T) {
			peers, dir := testPeers(t, 3), t.TempDir()
			n := testNode(t, 1, peers, dir)
			seedNode(t, n, 3, []wire.LogEntry{entry(1, 1, "add", 5), entry(2, 1, "add", 10), entry(3, 1, "mul", 2), entry(4, 1, "sub", 3), entry(5, 1, "add", 7)}, 1)
			if err := n.replaceLogLocked(2, []wire.LogEntry{entry(2, 2, "mul", 3), entry(3, 2, "add", 4), entry(4, 2, "mod", 7)}); err != nil {
				t.Fatal(err)
			}
			if err := n.commitLocked(4); err != nil {
				t.Fatal(err)
			}
			path := n.wal.Name()
			n.Stop()
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			second := 16 + 12 + int(binary.LittleEndian.Uint32(data[16:20]))
			switch damage {
			case "length":
				binary.LittleEndian.PutUint32(data[second:second+4], 1<<20)
			case "missing_record":
				data = data[:second]
			case "torn_payload":
				data = data[:len(data)-5]
			case "empty_wal":
				data = nil
			}
			if err = os.WriteFile(path, data, 0600); err != nil {
				t.Fatal(err)
			}
			bad, err := NewNode(Options{ID: 1, Peers: peers, DataDir: dir})
			if err == nil {
				bad.Stop()
				t.Fatal("corrupt committed replacement resurrected old entries")
			}
			after, readErr := os.ReadFile(path)
			if readErr != nil || string(after) != string(data) {
				t.Fatal("rejected recovery modified the damaged WAL")
			}
		})
	}
}
