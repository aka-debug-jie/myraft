package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"myraft/config"
	"myraft/raft"
	wire "myraft/rpc"
)

func run() error {
	id := flag.Int("id", 1, "node ID")
	port := flag.Int("port", 8001, "shared BASE port (same on every node); used without -config")
	nodes := flag.Int("nodes", 3, "number of configured nodes; used without -config")
	configPath := flag.String("config", "", "shared JSON configuration file")
	generate := flag.String("generate-config", "", "write configuration using -nodes and -port, then exit")
	dataDir := flag.String("data-dir", "data", "persistent node data directory")
	logDir := flag.String("log-dir", "logs", "node output directory")
	status := flag.Bool("status", false, "query selected node and print JSON, then exit")
	check := flag.Bool("check-config", false, "validate configuration and print JSON, then exit")
	demo := flag.Int("demo", 0, "generate this many arithmetic commands on the leader")
	seed := flag.Int64("seed", 42, "reproducible command seed")
	timeout := flag.Duration("timeout", 60*time.Second, "client operation timeout")
	all := flag.Bool("status-all", false, "query all configured nodes as JSON")
	verify := flag.Bool("verify", false, "verify all configured nodes have identical logs and committed states")
	target := flag.Int("target-index", 0, "fixed committed prefix to inspect")
	prepare := flag.Bool("prepare-divergence", false, "prepare legal offline divergent logs in an empty data directory")
	electionMin := flag.Duration("election-min", 3*time.Second, "minimum election timeout")
	electionJitter := flag.Duration("election-jitter", 3*time.Second, "random election timeout range")
	rpcTimeout := flag.Duration("rpc-timeout", time.Second, "Raft peer RPC timeout")
	heartbeat := flag.Duration("heartbeat", 150*time.Millisecond, "leader heartbeat interval")
	batchSize := flag.Int("batch-size", 128, "maximum entries per replication RPC (1..4096)")
	format := flag.String("format", "json", "status output: json or table (table uses lightweight monitoring)")
	watch := flag.Duration("watch", 0, "repeat -status-all, e.g. 1s; Ctrl+C stops")
	flag.Parse()
	demoSet := false
	flag.Visit(func(f *flag.Flag) {
		if f.Name == "demo" {
			demoSet = true
		}
	})
	if demoSet && *demo <= 0 {
		return fmt.Errorf("-demo must be positive")
	}

	if *timeout <= 0 || *timeout > 10*time.Minute || *demo < 0 || *target < 0 {
		return fmt.Errorf("invalid timeout, command count or target index")
	}
	if *batchSize < 1 || *batchSize > 4096 {
		return fmt.Errorf("-batch-size must be 1..4096")
	}
	if (*format != "json" && *format != "table") || (*format == "table" && (!*status && !*all || *target != 0)) {
		return fmt.Errorf("-format table requires -status or -status-all without -target-index")
	}
	if *watch < 0 || (*watch > 0 && (!*all || *watch < 200*time.Millisecond)) {
		return fmt.Errorf("-watch requires -status-all and an interval of at least 200ms")
	}
	modes := 0
	for _, v := range []bool{*generate != "", *status, *check, *all, *verify, *prepare, *demo > 0 && !*prepare} {
		if v {
			modes++
		}
	}
	if modes > 1 {
		return fmt.Errorf("select one operation")
	}

	if flag.NArg() != 0 {
		return fmt.Errorf("unexpected arguments: %v", flag.Args())
	}

	var c config.Config
	var err error
	if *generate != "" {
		c, err = config.Generate(*nodes, *port)
		if err != nil {
			return err
		}
		if err = c.Save(*generate); err != nil {
			return err
		}
		fmt.Printf("Configuration written: %s (%d nodes)\n", *generate, len(c.Nodes))
		return nil
	}
	if *configPath != "" {
		c, err = config.Load(*configPath)
	} else {
		c, err = config.Generate(*nodes, *port)
	}
	if err != nil {
		return err
	}
	peers, err := c.Peers()
	if err != nil {
		return err
	}
	if *check {
		return json.NewEncoder(os.Stdout).Encode(c)
	}
	if *prepare {
		count := *demo
		if count == 0 {
			count = 2101
		}
		if err := raft.PrepareDivergence(peers, *dataDir, count, *seed); err != nil {
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"prepared": true, "nodes": len(peers), "commands": count, "data_dir": *dataDir})
	}
	deadline := time.Now().Add(*timeout)
	if *watch > 0 {
		ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
		defer stop()
		return watchStatuses(ctx, os.Stdout, func() []wire.StatusReply {
			return queryStatuses(c, wire.StatusArgs{TargetIndex: *target, Summary: *format == "table"}, time.Now().Add(min(*timeout, 2*time.Second)))
		}, *watch, *format)
	}
	if *all || *verify {
		states := queryStatuses(c, wire.StatusArgs{TargetIndex: *target, Summary: *format == "table"}, deadline)
		if *all {
			if *format == "table" {
				return writeStatusTable(os.Stdout, states)
			}
			return json.NewEncoder(os.Stdout).Encode(states)
		}
		err := verifyStatuses(states, *target)
		result := map[string]any{"ok": err == nil, "nodes": states, "target_index": *target}
		if err != nil {
			result["error"] = err.Error()
		}
		if e := json.NewEncoder(os.Stdout).Encode(result); e != nil {
			return e
		}
		return err
	}
	if *demo > 0 {
		reply, err := submitGenerated(c, peers, *demo, *seed, deadline)
		if e := json.NewEncoder(os.Stdout).Encode(reply); e != nil {
			return e
		}
		return err
	}
	addr, ok := peers[*id]
	if !ok {
		return fmt.Errorf("node %d is not in the configuration", *id)
	}
	if *status {
		var reply wire.StatusReply
		if err = wire.Call(addr, "RaftNode.Status", &wire.StatusArgs{TargetIndex: *target, Summary: *format == "table"}, &reply, *timeout); err != nil {
			return err
		}
		if reply.ID != *id {
			return fmt.Errorf("endpoint returned node %d; expected %d", reply.ID, *id)
		}
		if *format == "table" {
			return writeStatusTable(os.Stdout, []wire.StatusReply{reply})
		}
		return json.NewEncoder(os.Stdout).Encode(reply)
	}

	if err = os.MkdirAll(*logDir, 0755); err != nil {
		return err
	}
	output, err := os.OpenFile(filepath.Join(*logDir, fmt.Sprintf("node-%d.log", *id)), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer output.Close()
	logger := log.New(io.MultiWriter(os.Stdout, output), "", log.Ldate|log.Ltime|log.Lmicroseconds)
	node, err := raft.NewNode(raft.Options{ID: *id, Peers: peers, DataDir: *dataDir, Logger: logger, ElectionMin: *electionMin, ElectionJitter: *electionJitter, RPCTimeout: *rpcTimeout, HeartbeatInterval: *heartbeat, BatchSize: *batchSize})
	if err != nil {
		return err
	}
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, os.Interrupt, syscall.SIGTERM)
	defer signal.Stop(signals)
	defer node.Stop()
	if err = node.Start(); err != nil {
		return err
	}
	select {
	case <-signals:
		return nil
	case err = <-node.Errors():
		return err
	}
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "raft:", err)
		os.Exit(1)
	}
}

func queryAll(c config.Config, target int, deadline time.Time) []wire.StatusReply {
	return queryStatuses(c, wire.StatusArgs{TargetIndex: target}, deadline)
}

func queryStatuses(c config.Config, args wire.StatusArgs, deadline time.Time) []wire.StatusReply {
	states := make([]wire.StatusReply, len(c.Nodes))
	jobs := make(chan int, len(c.Nodes))
	for i := range c.Nodes {
		jobs <- i
	}
	close(jobs)
	var wg sync.WaitGroup
	for worker := 0; worker < min(16, len(c.Nodes)); worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := range jobs {
				node := c.Nodes[i]
				s := wire.StatusReply{ID: node.ID}
				left := min(time.Second, time.Until(deadline))
				if left <= 0 {
					s.Error = "status deadline exceeded"
				} else if err := wire.Call(node.Addr, "RaftNode.Status", &args, &s, left); err != nil {
					s = wire.StatusReply{ID: node.ID, Error: err.Error()}
				}
				if s.Error == "" && s.ID != node.ID {
					s = wire.StatusReply{ID: node.ID, Error: fmt.Sprintf("endpoint returned node %d; expected %d", s.ID, node.ID)}
				}
				states[i] = s
			}
		}()
	}
	wg.Wait()
	return states
}

func verifyStatuses(states []wire.StatusReply, target int) error {
	if len(states) == 0 {
		return fmt.Errorf("no nodes")
	}
	first := states[0]
	for _, s := range states {
		if s.Error != "" {
			return fmt.Errorf("node %d: %s", s.ID, s.Error)
		}
		if s.LastApplied != s.CommitIndex || s.CommitIndex != s.LastLogIndex {
			return fmt.Errorf("node %d has uncommitted or unapplied entries", s.ID)
		}
		if s.LogHash == "" || s.CommittedHash == "" || s.LastLogIndex != first.LastLogIndex || s.CommitIndex != first.CommitIndex || s.LogHash != first.LogHash || s.CommittedHash != first.CommittedHash || s.X != first.X || s.AppliedCommands != first.AppliedCommands || s.CommittedCommands != first.CommittedCommands {
			return fmt.Errorf("node %d log/state differs", s.ID)
		}
		if target > 0 && (!s.TargetAvailable || s.TargetIndex != target || s.TargetHash != first.TargetHash || s.TargetX != first.TargetX) {
			return fmt.Errorf("node %d has not matched target %d", s.ID, target)
		}
	}
	return nil
}

func submitGenerated(c config.Config, peers map[int]string, count int, seed int64, deadline time.Time) (wire.GenerateReply, error) {
	for time.Until(deadline) > 0 {
		leader, term := 0, -1
		for _, s := range queryAll(c, 0, deadline) {
			if s.Error == "" && s.State == "Leader" && s.LeaderID == s.ID && s.Term > term {
				leader, term = s.ID, s.Term
			}
		}
		if leader == 0 {
			time.Sleep(min(100*time.Millisecond, max(0, time.Until(deadline))))
			continue
		}
		left := time.Until(deadline)
		if left < time.Millisecond {
			break
		}
		var reply wire.GenerateReply
		args := wire.GenerateArgs{Count: count, Seed: seed, TimeoutMS: int(left / time.Millisecond)}
		if err := wire.Call(peers[leader], "RaftNode.Generate", &args, &reply, left); err != nil {
			reply.Error = fmt.Sprintf("submission outcome unknown; do not retry automatically: %v", err)
			return reply, fmt.Errorf("%s", reply.Error)
		}
		if reply.Accepted && reply.Committed && reply.Error == "" {
			return reply, nil
		}
		if !reply.Accepted && reply.Error == "not leader" {
			time.Sleep(min(100*time.Millisecond, max(0, time.Until(deadline))))
			continue
		}
		return reply, fmt.Errorf("submission not confirmed: %s", reply.Error)
	}
	r := wire.GenerateReply{Error: "leader discovery timed out"}
	return r, fmt.Errorf("%s", r.Error)
}
