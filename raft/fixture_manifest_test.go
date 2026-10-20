package raft

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"testing"
)

func TestDivergenceInitialManifest(t *testing.T) {
	for _, count := range []int{10, 20, 50, 100} {
		t.Run(strconv.Itoa(count), func(t *testing.T) {
			peers, dir := testPeers(t, count), t.TempDir()
			if err := PrepareDivergence(peers, dir, 256, 42, "test-cluster"); err != nil {
				t.Fatal(err)
			}
			b, err := os.ReadFile(filepath.Join(dir, "fixture.json"))
			if err != nil {
				t.Fatal(err)
			}
			var m struct {
				CommonHash string `json:"common_hash"`
				Nodes      []struct {
					ID            int    `json:"id"`
					LastIndex     int    `json:"last_log_index"`
					LastTerm      int    `json:"last_log_term"`
					Hash          string `json:"log_hash"`
					Commit        int    `json:"commit_index"`
					CommittedHash string `json:"committed_hash"`
				} `json:"nodes"`
			}
			if err = json.Unmarshal(b, &m); err != nil {
				t.Fatal(err)
			}
			if len(m.Nodes) != count {
				t.Fatalf("need %d initial node records, got %d", count, len(m.Nodes))
			}
			lengths := map[int]bool{}
			for _, s := range m.Nodes {
				if lengths[s.LastIndex] {
					t.Fatalf("initial lengths not distinct: %d", s.LastIndex)
				}
				lengths[s.LastIndex] = true
				if s.Commit != 129 || s.CommittedHash != m.CommonHash {
					t.Fatal("committed prefix differs")
				}
				n := testNode(t, s.ID, peers, dir)
				actual := snapshot(n)
				n.Stop()
				if s.LastIndex != actual.LastLogIndex || s.LastTerm != actual.LastLogTerm || s.Hash != actual.LogHash {
					t.Fatal("manifest does not match persisted log")
				}
			}
		})
	}
}
