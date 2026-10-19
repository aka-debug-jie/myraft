package raft

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	wire "myraft/rpc"
)

func TestNodeStorageExclusive(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	n := testNode(t, 1, peers, dir)
	seedNode(t, n, 1, []wire.LogEntry{entry(1, 1, "add", 7)}, 1)
	before, err := os.ReadFile(n.wal.Name())
	if err != nil {
		t.Fatal(err)
	}
	duplicate, err := NewNode(Options{ID: 1, Peers: peers, DataDir: dir, Logger: log.New(io.Discard, "", 0)})
	if err == nil {
		duplicate.Stop()
		t.Fatal("same node storage opened twice")
	}
	after, err := os.ReadFile(n.wal.Name())
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("rejected open changed WAL")
	}
	other := testNode(t, 2, peers, dir)
	other.Stop() // Different IDs may share a directory.
	n.Stop()
	reopened := testNode(t, 1, peers, dir)
	if s := snapshot(reopened); s.CommitIndex != 1 || s.X != 7 {
		t.Fatalf("recovery: %+v", s)
	}
	n.Stop() // A repeated old Stop must not release the new instance's ownership.
	duplicate, err = NewNode(Options{ID: 1, Peers: peers, DataDir: dir})
	if err == nil {
		duplicate.Stop()
		t.Fatal("old Stop released new instance")
	}
}

func TestNodeStorageLockReleasedAfterLoadError(t *testing.T) {
	for _, damaged := range []string{"state", "wal"} {
		t.Run(damaged, func(t *testing.T) {
			peers, dir := testPeers(t, 3), t.TempDir()
			n := testNode(t, 1, peers, dir)
			seedNode(t, n, 1, []wire.LogEntry{entry(1, 1, "add", 7)}, 1)
			path := n.statePath
			if damaged == "wal" {
				path = n.wal.Name()
			}
			n.Stop()
			original, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte("corrupt"), 0600); err != nil {
				t.Fatal(err)
			}
			bad, err := NewNode(Options{ID: 1, Peers: peers, DataDir: dir})
			if err == nil {
				bad.Stop()
				t.Fatal("corrupt storage accepted")
			}
			if err := os.WriteFile(path, original, 0600); err != nil {
				t.Fatal(err)
			}
			if s := snapshot(testNode(t, 1, peers, dir)); s.CommitIndex != 1 || s.X != 7 {
				t.Fatalf("recovery: %+v", s)
			}
		})
	}
}

func TestNodeStorageLockLifetime(t *testing.T) {
	peers, dir := testPeers(t, 1), t.TempDir()
	n := testNode(t, 1, peers, dir)
	listener, err := net.Listen("tcp", peers[1])
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	if n.Start() == nil {
		t.Fatal("occupied listener accepted")
	}
	duplicate, err := NewNode(Options{ID: 1, Peers: peers, DataDir: dir})
	if err == nil {
		duplicate.Stop()
		t.Fatal("failed Start released live node's lock")
	}
	listener.Close()
	if err := n.Start(); err != nil {
		t.Fatal(err)
	}
	var stopped sync.WaitGroup
	for i := 0; i < 8; i++ {
		stopped.Add(1)
		go func() { defer stopped.Done(); n.Stop() }()
	}
	stopped.Wait()
	testNode(t, 1, peers, dir)
	// Ownership is per node and directory, not globally per node ID.
	testNode(t, 1, peers, t.TempDir())
}

type storageStopConn struct {
	net.Conn
	entered, release chan struct{}
}

func (c *storageStopConn) Close() error {
	close(c.entered)
	<-c.release
	return nil
}

func TestConcurrentStopWaitsForStorageRelease(t *testing.T) {
	peers, dir := testPeers(t, 1), t.TempDir()
	n := testNode(t, 1, peers, dir)
	c := &storageStopConn{entered: make(chan struct{}), release: make(chan struct{})}
	var release sync.Once
	defer release.Do(func() { close(c.release) })
	n.connections[c] = true
	first, second := make(chan struct{}), make(chan struct{})
	go func() { n.Stop(); close(first) }()
	<-c.entered // First Stop has marked the node stopped but still owns storage.
	go func() { n.Stop(); close(second) }()
	select {
	case <-second:
		t.Fatal("second Stop returned before storage was released")
	case <-time.After(50 * time.Millisecond):
	}
	release.Do(func() { close(c.release) })
	for _, done := range []chan struct{}{first, second} {
		select {
		case <-done:
		case <-time.After(2 * time.Second):
			t.Fatal("Stop did not finish after connection closed")
		}
	}
	testNode(t, 1, peers, dir)
}

func TestNodeStorageLockDirectoryAlias(t *testing.T) {
	dir, link := t.TempDir(), filepath.Join(t.TempDir(), "data-alias")
	if err := os.Symlink(dir, link); err != nil {
		t.Skipf("directory symlink unavailable: %v", err)
	}
	peers := testPeers(t, 1)
	testNode(t, 1, peers, dir)
	duplicate, err := NewNode(Options{ID: 1, Peers: peers, DataDir: link})
	if err == nil {
		duplicate.Stop()
		t.Fatal("directory alias bypassed lock")
	}
	if !strings.Contains(err.Error(), "lock node") {
		t.Fatalf("wrong rejection: %v", err)
	}
}

func TestNodeStorageLockProcess(t *testing.T) {
	if dir := os.Getenv("MYRAFT_STORAGE_LOCK_DIR"); dir != "" {
		n := testNode(t, 1, map[int]string{1: "127.0.0.1:1"}, dir)
		seedNode(t, n, 1, []wire.LogEntry{entry(1, 1, "add", 7)}, 1)
		fmt.Println("storage locked")
		io.Copy(io.Discard, os.Stdin)
		return
	}
	dir, peers := t.TempDir(), testPeers(t, 1)
	cmd := exec.Command(os.Args[0], "-test.run=^TestNodeStorageLockProcess$")
	cmd.Env = append(os.Environ(), "MYRAFT_STORAGE_LOCK_DIR="+dir)
	input, err := cmd.StdinPipe()
	if err != nil {
		t.Fatal(err)
	}
	defer input.Close()
	output, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if cmd.ProcessState == nil {
			cmd.Process.Kill()
			cmd.Wait()
		}
	})
	ready := make(chan string, 1)
	go func() { line, _ := bufio.NewReader(output).ReadString('\n'); ready <- strings.TrimSpace(line) }()
	select {
	case line := <-ready:
		if line != "storage locked" {
			t.Fatalf("child not ready: %q", line)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("child storage initialization timed out")
	}
	duplicate, err := NewNode(Options{ID: 1, Peers: peers, DataDir: dir})
	if err == nil {
		duplicate.Stop()
		t.Fatal("child process storage opened twice")
	}
	if err := cmd.Process.Kill(); err != nil {
		t.Fatal(err)
	}
	if err := cmd.Wait(); err == nil {
		t.Fatal("expected forced child exit")
	}
	if _, err := os.Stat(filepath.Join(dir, "node-1.lock")); err != nil {
		t.Fatalf("lock file should survive: %v", err)
	}
	if s := snapshot(testNode(t, 1, peers, dir)); s.CommitIndex != 1 || s.X != 7 {
		t.Fatalf("crash recovery: %+v", s)
	}
}

func TestOversizedAppendRejectedBeforeWALWrite(t *testing.T) {
	peers, dir := testPeers(t, 3), t.TempDir()
	n := testNode(t, 1, peers, dir)
	seedNode(t, n, 1, []wire.LogEntry{entry(1, 1, "add", 7)}, 1)
	before, err := os.ReadFile(n.wal.Name())
	if err != nil {
		t.Fatal(err)
	}
	entries := make([]wire.LogEntry, 600000)
	for i := range entries {
		entries[i] = entry(i+2, 1, "add", 1)
	}
	var reply wire.AppendEntriesReply
	err = n.AppendEntries(&wire.AppendEntriesArgs{Term: 1, LeaderID: 2, PrevLogIndex: 1, PrevLogTerm: 1, Entries: entries, LeaderCommit: len(entries) + 1}, &reply)
	if err == nil || reply.Success {
		t.Fatalf("oversized frame acknowledged: %+v %v", reply, err)
	}
	after, err := os.ReadFile(n.wal.Name())
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("rejected frame changed WAL")
	}
	if s := snapshot(n); s.Error != "" || s.LastLogIndex != 1 || s.CommitIndex != 1 || s.LastApplied != 1 || s.X != 7 {
		t.Fatalf("rejected frame changed state: %+v", s)
	}
	// An input limit error must leave the node usable and its WAL recoverable.
	err = n.AppendEntries(&wire.AppendEntriesArgs{Term: 1, LeaderID: 2, PrevLogIndex: 1, PrevLogTerm: 1, Entries: []wire.LogEntry{entry(2, 1, "add", 2)}, LeaderCommit: 2}, &reply)
	if err != nil || !reply.Success {
		t.Fatalf("valid append: %+v %v", reply, err)
	}
	n.Stop()
	recovered := testNode(t, 1, peers, dir)
	if s := snapshot(recovered); s.CommitIndex != 2 || s.X != 9 {
		t.Fatalf("recovery: %+v", s)
	}
}
