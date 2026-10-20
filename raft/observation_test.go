package raft

import (
	"errors"
	"log"
	"strings"
	"sync"
	"testing"
	"time"

	wire "myraft/rpc"
)

type blockedEventSink struct {
	entered, release chan struct{}
	once             sync.Once
}

func (w *blockedEventSink) Write(b []byte) (int, error) {
	w.once.Do(func() { close(w.entered) })
	<-w.release
	return len(b), nil
}

func TestBlockedOrdinaryOutputDoesNotBlockProtocolOrStop(t *testing.T) {
	w := &blockedEventSink{entered: make(chan struct{}), release: make(chan struct{})}
	defer close(w.release)
	n, err := NewNode(Options{ClusterID: "test-cluster", ID: 1, Peers: testPeers(t, 1), DataDir: t.TempDir(), Logger: log.New(w, "", 0), ElectionMin: 600 * time.Millisecond, ElectionJitter: 200 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	defer n.Stop()
	select {
	case <-w.entered:
	case <-time.After(time.Second):
		t.Fatal("sink not entered")
	}
	// Election and a durable single-member majority commit still run with sink blocked.
	n.mu.Lock()
	n.startElectionLocked()
	for i := 0; i < eventCapacity+20; i++ {
		n.eventLocked("test_event index=%d", i)
	}
	n.mu.Unlock()
	done := make(chan error, 1)
	go func() {
		var r wire.GenerateReply
		e := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 2101, Seed: 42, TimeoutMS: 1000}, &r)
		if e == nil && !r.Committed {
			e = errors.New("not committed")
		}
		done <- e
	}()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("blocked sink stalled commit")
	}
	summary := make(chan wire.StatusReply, 1)
	go func() { var s wire.StatusReply; n.Status(&wire.StatusArgs{Summary: true}, &s); summary <- s }()
	select {
	case s := <-summary:
		if s.DroppedEvents == 0 || s.CommittedCommands != 2101 {
			t.Fatalf("summary %+v", s)
		}
	case <-time.After(100 * time.Millisecond):
		t.Fatal("blocked sink stalled Summary")
	}
	var events wire.EventReply
	if err := n.EventRange(&wire.EventArgs{Limit: 256}, &events); err != nil || !events.Gap || len(events.Events) > 256 {
		t.Fatalf("event bounds %+v %v", events, err)
	}
	stopped := make(chan struct{})
	go func() { n.Stop(); close(stopped) }()
	select {
	case <-stopped:
	case <-time.After(350 * time.Millisecond):
		t.Fatal("Stop waited for ordinary sink")
	}
}

func TestLogRangeCopiesBoundedRevision(t *testing.T) {
	n := testNode(t, 1, testPeers(t, 1), t.TempDir())
	n.startElectionLocked()
	var generated wire.GenerateReply
	if err := n.Generate(&wire.GenerateArgs{ClusterID: "test-cluster", Count: 300, Seed: 42, TimeoutMS: 1000}, &generated); err != nil {
		t.Fatal(err)
	}
	var r wire.LogRangeReply
	if err := n.LogRange(&wire.LogRangeArgs{From: 1}, &r); err != nil || len(r.Entries) != 128 || !r.Truncated || r.ClusterID != "test-cluster" || r.InstanceID == "" || r.Revision == 0 {
		t.Fatalf("range %+v %v", r, err)
	}
	r.Entries[0].Command.Op = "bad"
	if n.log[1].Command.Op != "noop" {
		t.Fatal("range shared mutable log")
	}
	if err := n.LogRange(&wire.LogRangeArgs{From: 1, Limit: 257}, &r); err == nil {
		t.Fatal("unbounded range accepted")
	}
	if err := n.LogRange(&wire.LogRangeArgs{From: 999}, &r); err != nil || len(r.Entries) != 0 {
		t.Fatal("missing range fabricated")
	}
}

type eventRecords chan string

func (w eventRecords) Write(b []byte) (int, error) { w <- string(b); return len(b), nil }

func TestOrdinaryOutputReportsDroppedEvents(t *testing.T) {
	records := make(eventRecords, 512)
	n, err := NewNode(Options{ClusterID: "test-cluster", ID: 1, Peers: testPeers(t, 1), DataDir: t.TempDir(), Logger: log.New(records, "", 0)})
	if err != nil {
		t.Fatal(err)
	}
	defer n.Stop()
	n.logDropped.Add(7)
	n.mu.Lock()
	n.eventLocked("test_after_drop")
	n.mu.Unlock()
	deadline := time.After(time.Second)
	for {
		select {
		case line := <-records:
			if strings.Contains(line, "output_dropped total=7") {
				return
			}
		case <-deadline:
			t.Fatal("terminal/file output omitted drop notice")
		}
	}
}
