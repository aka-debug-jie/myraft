package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	wire "myraft/rpc"
)

func TestWriteStatusTable(t *testing.T) {
	states := []wire.StatusReply{
		{ID: 8, State: "leader", Term: 4, LeaderID: 8, LastLogIndex: 11, CommitIndex: 9, LastApplied: 8, CommittedCommands: 7, AppliedCommands: 6, X: 42},
		{ID: 3, Error: "offline\tconnection lost\nretry later", Term: 99, LeaderID: 3, LastLogIndex: 90, CommitIndex: 80, LastApplied: 70, CommittedCommands: 60, AppliedCommands: 50, X: 40},
		{ID: 5, State: "follower", Term: 4, LeaderID: 8, LastLogIndex: 11, CommitIndex: 9, LastApplied: 8, CommittedCommands: 7, AppliedCommands: 6, X: 0},
	}
	original := append([]wire.StatusReply(nil), states...)
	var out bytes.Buffer
	if err := writeStatusTable(&out, states); err != nil {
		t.Fatal(err)
	}
	text := out.String()
	for _, want := range []string{
		"ID", "ROLE(local)", "COMMIT", "APPLIED", "COMMANDS", "ERROR",
		"3   -            -     -       -     -       -        -         -   offline connection lost retry later",
		"5   follower     4     8       11    9       8        7/6       0   -",
		"8   leader       4     8       11    9       8        7/6       42  -",
		"Local role and reachability do not mean a write succeeded; only Generate accepted+committed confirms a write.",
	} {
		if !strings.Contains(text, want) {
			t.Errorf("output does not contain %q:\n%s", want, text)
		}
	}
	if states[0] != original[0] || states[1] != original[1] || states[2] != original[2] {
		t.Fatal("input states were modified or reordered")
	}
	if strings.Index(text, "3   -") > strings.Index(text, "5   follower") || strings.Index(text, "5   follower") > strings.Index(text, "8   leader") {
		t.Fatalf("rows are not sorted by ID:\n%s", text)
	}
	if strings.Contains(text, "healthy") || strings.Contains(text, "quorum confirmed") {
		t.Fatalf("output overstates leader status:\n%s", text)
	}
}

type failingWriter struct{}

func (failingWriter) Write([]byte) (int, error) { return 0, errors.New("write failed") }

func TestWriteStatusTablePropagatesWriterError(t *testing.T) {
	err := writeStatusTable(failingWriter{}, nil)
	if err == nil || err.Error() != "write failed" {
		t.Fatalf("writeStatusTable error = %v, want write failed", err)
	}
}

func TestWatchStopsAndPreservesJSON(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	calls := 0
	var out bytes.Buffer
	query := func() []wire.StatusReply {
		calls++
		if calls == 2 {
			cancel()
		}
		return []wire.StatusReply{{ID: 7, State: "Leader", CommitIndex: 3}}
	}
	if err := watchStatuses(ctx, &out, query, time.Millisecond, "json"); err != nil {
		t.Fatal(err)
	}
	if calls != 2 {
		t.Fatalf("queries %d", calls)
	}
	dec := json.NewDecoder(&out)
	for i := 0; i < 2; i++ {
		var rows []wire.StatusReply
		if err := dec.Decode(&rows); err != nil || len(rows) != 1 || rows[0].ID != 7 {
			t.Fatalf("JSON stream %+v %v", rows, err)
		}
	}
	if err := watchStatuses(context.Background(), failingWriter{}, query, time.Millisecond, "table"); err == nil {
		t.Fatal("watch ignored writer failure")
	}
}
