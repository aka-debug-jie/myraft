// Package config reads the shared, fixed membership of an election cluster.
package config

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"strconv"
)

type Node struct {
	ID   int    `json:"id"`
	Addr string `json:"addr"`
}

type Config struct {
	ClusterID string `json:"cluster_id,omitempty"`
	Nodes     []Node `json:"nodes"`
}

func (c Config) Peers() (map[int]string, error) {
	if len(c.Nodes) == 0 {
		return nil, fmt.Errorf("configuration must contain at least one node")
	}
	peers := make(map[int]string, len(c.Nodes))
	addresses := make(map[string]bool, len(c.Nodes))
	for _, n := range c.Nodes {
		if n.ID < 1 {
			return nil, fmt.Errorf("node ID must be positive: %d", n.ID)
		}
		if _, ok := peers[n.ID]; ok {
			return nil, fmt.Errorf("duplicate node ID: %d", n.ID)
		}
		host, port, err := net.SplitHostPort(n.Addr)
		if err != nil || host == "" {
			return nil, fmt.Errorf("invalid address for node %d: %q", n.ID, n.Addr)
		}
		p, err := strconv.Atoi(port)
		if err != nil || p < 1 || p > 65535 {
			return nil, fmt.Errorf("invalid port for node %d: %q", n.ID, port)
		}
		if addresses[n.Addr] {
			return nil, fmt.Errorf("duplicate address: %s", n.Addr)
		}
		addresses[n.Addr] = true
		peers[n.ID] = n.Addr
	}
	if c.ClusterID != "" {
		if _, err := FixedIdentity(c.ClusterID, peers); err != nil {
			return nil, err
		}
	}
	return peers, nil
}

func Load(path string) (Config, error) {
	var c Config
	b, err := os.ReadFile(path)
	if err != nil {
		return c, err
	}
	if err = json.Unmarshal(b, &c); err != nil {
		return c, fmt.Errorf("read config: %w", err)
	}
	_, err = c.Peers()
	return c, err
}

// Generate uses one common base port for every node's view of the cluster.
func Generate(count, basePort int) (Config, error) {
	var c Config
	if count < 1 || basePort < 1 || basePort > 65535 || count > 65536-basePort {
		return c, fmt.Errorf("invalid node count/base port: %d/%d", count, basePort)
	}
	for i := 1; i <= count; i++ {
		c.Nodes = append(c.Nodes, Node{ID: i, Addr: fmt.Sprintf("127.0.0.1:%d", basePort+i-1)})
	}
	return c, nil
}

func (c Config) Save(path string) error {
	if _, err := c.Peers(); err != nil {
		return err
	}
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0644)
}
