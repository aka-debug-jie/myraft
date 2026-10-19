package raft

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"sort"

	wire "myraft/rpc"
)

// PrepareDivergence creates an offline, reachable history in a new experiment directory.
func PrepareDivergence(peers map[int]string, dir string, count int, seed int64, clusterID ...string) error {
	if len(clusterID) != 1 || clusterID[0] == "" {
		return fmt.Errorf("explicit cluster identity required for fixture")
	}
	if len(peers) < 3 || count < 256 || count > 100000 {
		return fmt.Errorf("fixture requires >=3 nodes and 256..100000 commands")
	}
	if files, err := os.ReadDir(dir); err == nil && len(files) != 0 {
		return fmt.Errorf("fixture directory must be empty")
	} else if err != nil && !os.IsNotExist(err) {
		return err
	}
	ids := make([]int, 0, len(peers))
	for id := range peers {
		ids = append(ids, id)
	}
	sort.Ints(ids)
	split := 1 + (len(ids)-1)/2
	commands := generateCommands(count, seed)
	alternate := generateCommands(count, seed+1)
	// Each branch has fewer than a quorum of copies. The neutral node gave the
	// term-3 election its extra vote but never received that leader's suffix.
	commonHash := ""
	var commonX int64
	for rank, id := range ids {
		n, err := NewNode(Options{ClusterID: clusterID[0], ID: id, Peers: peers, DataDir: dir, Logger: log.New(io.Discard, "", 0)})
		if err != nil {
			return err
		}
		vote := -1
		if rank == 0 || rank >= split {
			vote = ids[len(ids)-1]
		}
		if err = n.persistLocked(3, vote); err != nil {
			n.Stop()
			return err
		}
		length := 129
		if rank > 0 {
			length = 131 + (count+2-131)*(rank-1)/(len(ids)-2)
		}
		entries := make([]wire.LogEntry, length)
		for i := range entries {
			index := i + 1
			term := 1
			cmd := wire.Command{Op: "noop"}
			if index >= 2 && index <= 129 {
				cmd = commands[index-2]
			}
			if index >= 130 {
				term = 3
				if rank < split {
					term = 2
				}
				if index > 130 {
					cmd = commands[index-3]
					if rank < split {
						cmd = alternate[index-3]
					}
				}
			}
			entries[i] = wire.LogEntry{Index: index, Term: term, Command: cmd}
		}
		err = n.appendEntriesLocked(entries)
		if err == nil {
			err = n.commitLocked(129)
		}
		if err != nil {
			n.Stop()
			return err
		}
		commonHash = logHash(n.log[1:130])
		commonX = n.x
		n.Stop()
		if err != nil {
			return err
		}
	}
	manifest := map[string]any{"common_commit_index": 129, "common_hash": commonHash, "common_x": commonX, "common_arithmetic_commands": 128, "neutral": ids[0], "term2_branch": ids[1:split], "term3_branch": ids[split:], "latest_node": ids[len(ids)-1], "commands": count, "seed": seed, "history": "term 1 noop and 128 commands committed everywhere; each later branch has less than quorum copies; neutral voted for term 3 but received no suffix"}
	b, err := json.MarshalIndent(manifest, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(dir, "fixture.json"), append(b, '\n'), 0644)
}
