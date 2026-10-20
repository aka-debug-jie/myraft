//go:build ignore

// Build explicitly from the measured source checkout. No write is retried.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

func main() {
	path := flag.String("config", "", "fixed cluster configuration")
	samples := flag.Int("samples", 200, "measured requests")
	warmup := flag.Int("warmup", 20, "warmup requests")
	entries := flag.Int("entries", 64, "commands per independent request")
	seed := flag.Int64("seed", 42, "first deterministic seed")
	output := flag.String("output", "", "new JSONL attempt journal")
	flag.Parse()
	var journal *json.Encoder
	if *output != "" {
		f, err := os.OpenFile(*output, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		defer f.Close()
		journal = json.NewEncoder(f)
	}
	c, err := config.Load(*path)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	leader, err := wire.DiscoverLeader(context.Background(), c, time.Now().Add(10*time.Second))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	type sample struct {
		Warmup    bool    `json:"warmup"`
		Seconds   float64 `json:"seconds"`
		Accepted  bool    `json:"accepted"`
		Committed bool    `json:"committed"`
		Error     string  `json:"error,omitempty"`
	}
	results := make([]sample, 0, *samples+*warmup)
	peers, _ := c.Peers()
	for i := 0; i < *samples+*warmup; i++ {
		begin := time.Now()
		var reply wire.GenerateReply
		// Include connection establishment and Generate, but exclude leader discovery,
		// CLI startup, polling, and all-replica verification.
		err := wire.Call(peers[leader.ID], "RaftNode.Generate",
			&wire.GenerateArgs{ClusterID: c.ClusterID, Count: *entries, Seed: *seed + int64(i), TimeoutMS: 10000}, &reply, 11*time.Second)
		r := sample{Warmup: i < *warmup, Seconds: time.Since(begin).Seconds(), Accepted: reply.Accepted, Committed: reply.Committed, Error: reply.Error}
		if err != nil {
			r.Error = "outcome unknown; not retried: " + err.Error()
		}
		results = append(results, r)
		if journal != nil {
			if err := journal.Encode(r); err != nil {
				fmt.Fprintln(os.Stderr, "attempt journal:", err)
				os.Exit(1)
			}
		}
		if r.Error != "" || !r.Committed {
			break
		}
	}
	json.NewEncoder(os.Stdout).Encode(map[string]any{"leader": leader.ID, "term": leader.Term, "planned": *samples, "warmup": *warmup, "entries": *entries, "attempts": results})
}
