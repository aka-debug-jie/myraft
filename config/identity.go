package config

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"slices"
	"strings"
)

type Identity struct {
	ClusterID string `json:"cluster_id"`
	MemberIDs []int  `json:"member_ids"`
}

func NewClusterID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b[:])
}

func FixedIdentity(clusterID string, peers map[int]string) (Identity, error) {
	i := Identity{ClusterID: clusterID}
	if len(clusterID) < 1 || len(clusterID) > 64 || strings.IndexFunc(clusterID, func(r rune) bool {
		return !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_')
	}) >= 0 {
		return i, fmt.Errorf("explicit cluster_id required (1..64 letters, digits, '-' or '_')")
	}
	for id := range peers {
		if id < 1 {
			return i, fmt.Errorf("member IDs must be positive")
		}
		i.MemberIDs = append(i.MemberIDs, id)
	}
	if len(i.MemberIDs) == 0 {
		return i, fmt.Errorf("empty membership")
	}
	slices.Sort(i.MemberIDs)
	return i, nil
}

func (i Identity) Equal(other Identity) bool {
	return i.ClusterID == other.ClusterID && slices.Equal(i.MemberIDs, other.MemberIDs)
}

func (i Identity) MembershipHash() string {
	b, _ := json.Marshal(i.MemberIDs)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
