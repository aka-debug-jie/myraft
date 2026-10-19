package raft

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash"
	"math/rand"

	wire "myraft/rpc"
)

func validateCommand(c wire.Command) error {
	switch c.Op {
	case "noop", "add", "sub", "mul":
	case "div", "mod":
		if c.Value == 0 {
			return fmt.Errorf("%s by zero", c.Op)
		}
	default:
		return fmt.Errorf("unknown operation %q", c.Op)
	}
	return nil
}

func applyCommand(x int64, c wire.Command) int64 {
	// Go signed integer division truncates toward zero; remainder has x's sign.
	switch c.Op {
	case "add":
		return x + c.Value
	case "sub":
		return x - c.Value
	case "mul":
		return x * c.Value
	case "div":
		return x / c.Value
	case "mod":
		return x % c.Value
	default:
		return x // internal no-op, validated before entering the log
	}
}

func generateCommands(count int, seed int64) []wire.Command {
	r := rand.New(rand.NewSource(seed))
	commands := make([]wire.Command, count)
	ops := []string{"add", "sub", "mul", "div", "mod"}
	for i := range commands {
		if i%16 == 0 {
			commands[i] = wire.Command{Op: "mod", Value: 997}
			continue
		}
		op := ops[r.Intn(len(ops))]
		value := int64(r.Intn(9) + 1)
		if op == "mul" {
			value = int64(r.Intn(3) + 1)
		}
		commands[i] = wire.Command{Op: op, Value: value}
	}
	return commands
}

func logHash(entries []wire.LogEntry) string {
	// Struct field order and integer JSON encoding make this portable and deterministic.
	h := sha256.New()
	appendLogHash(h, entries)
	return hex.EncodeToString(h.Sum(nil))
}

func appendLogHash(h hash.Hash, entries []wire.LogEntry) {
	enc := json.NewEncoder(h)
	for _, e := range entries {
		_ = enc.Encode(e)
	}
}

func (n *Node) applyLocked() {
	first := n.lastApplied + 1
	for n.lastApplied < n.commitIndex {
		n.lastApplied++
		cmd := n.log[n.lastApplied].Command
		n.x = applyCommand(n.x, cmd)
		if cmd.Op != "noop" {
			n.appliedCommands++
		}
	}
	if n.lastApplied >= first {
		n.eventLocked("state_applied from=%d index=%d commands=%d x=%d", first, n.lastApplied, n.appliedCommands, n.x)
	}
}
