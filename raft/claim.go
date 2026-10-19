package raft

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

type ClaimReport struct {
	NodeID            int               `json:"node_id"`
	Identity          config.Identity   `json:"identity"`
	Backup            string            `json:"backup"`
	AlreadyBound      bool              `json:"already_bound"`
	CommitIndex       int               `json:"commit_index"`
	RecoveryTruncate  int64             `json:"recovery_truncate"`
	OriginalSHA256    map[string]string `json:"original_sha256"`
	OriginallyMissing []string          `json:"originally_missing,omitempty"`
	ClaimedAt         time.Time         `json:"claimed_at"`
}

// ClaimLegacy is an explicit operator assertion of the original fixed membership.
// It audits read-only, syncs original bytes and a manifest, then binds metadata.
func ClaimLegacy(o Options) (ClaimReport, error) {
	report := ClaimReport{NodeID: o.ID, ClaimedAt: time.Now().UTC()}
	identity, err := config.FixedIdentity(o.ClusterID, o.Peers)
	if err != nil {
		return report, err
	}
	if o.Peers[o.ID] == "" || o.DataDir == "" {
		return report, fmt.Errorf("node/config/data directory required")
	}
	report.Identity = identity
	lock, err := lockStorage(filepath.Join(o.DataDir, fmt.Sprintf("node-%d.lock", o.ID)))
	if err != nil {
		return report, err
	}
	defer lock.Close()
	statePath := filepath.Join(o.DataDir, fmt.Sprintf("node-%d-state.json", o.ID))
	b, err := os.ReadFile(statePath)
	missingState := os.IsNotExist(err)
	if err != nil && !missingState {
		return report, fmt.Errorf("read original metadata: %w", err)
	}
	s := persistentState{NodeID: o.ID, VotedFor: -1}
	if !missingState {
		if err := json.Unmarshal(b, &s); err != nil {
			return report, err
		}
	} else if _, err := os.Stat(filepath.Join(o.DataDir, fmt.Sprintf("node-%d-log.wal", o.ID))); err != nil {
		return report, fmt.Errorf("original state and WAL unavailable: %w", err)
	}
	if s.Identity.ClusterID != "" {
		if !s.Identity.Equal(identity) {
			return report, fmt.Errorf("identity already bound to a different cluster or membership")
		}
		report.AlreadyBound = true
		return report, nil
	}
	if s.NodeID != o.ID || s.Term < 0 || s.CommitIndex < 0 || (s.VotedFor != -1 && o.Peers[s.VotedFor] == "") {
		return report, fmt.Errorf("invalid original metadata or vote outside original membership")
	}
	n := &Node{id: o.ID, options: o, statePath: statePath, identity: identity, term: s.Term, commitIndex: s.CommitIndex, log: []wire.LogEntry{{}}}
	defer func() {
		if n.wal != nil {
			n.wal.Close()
		}
	}()
	if err := n.loadLog(true); err != nil {
		return report, err
	}
	if n.commitIndex > n.lastIndexLocked() || n.log[n.lastIndexLocked()].Term > n.term {
		return report, fmt.Errorf("metadata does not cover original WAL")
	}
	digest := logHash(n.log[1 : n.commitIndex+1])
	if (s.CommitIndex > 0 || s.CommitHash != "") && s.CommitHash != digest {
		return report, fmt.Errorf("original committed hash mismatch")
	}
	report.CommitIndex, report.RecoveryTruncate = s.CommitIndex, n.recoveryTruncate
	backup, err := os.MkdirTemp(o.DataDir, fmt.Sprintf("node-%d-claim-", o.ID))
	if err != nil {
		return report, err
	}
	report.Backup, report.OriginalSHA256 = filepath.Base(backup), make(map[string]string)
	for _, name := range []string{filepath.Base(statePath), fmt.Sprintf("node-%d-log.wal", o.ID)} {
		f, e := os.Open(filepath.Join(o.DataDir, name))
		if os.IsNotExist(e) {
			report.OriginallyMissing = append(report.OriginallyMissing, name)
			continue
		}
		if e != nil {
			return report, e
		}
		out, e := os.OpenFile(filepath.Join(backup, name), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e != nil {
			f.Close()
			return report, e
		}
		h := sha256.New()
		_, e = io.Copy(io.MultiWriter(out, h), f)
		f.Close()
		if e == nil {
			e = out.Sync()
		}
		closeErr := out.Close()
		if e == nil {
			e = closeErr
		}
		if e != nil {
			return report, e
		}
		report.OriginalSHA256[name] = hex.EncodeToString(h.Sum(nil))
		copyFile, e := os.Open(filepath.Join(backup, name))
		if e != nil {
			return report, e
		}
		check := sha256.New()
		_, e = io.Copy(check, copyFile)
		copyFile.Close()
		if e != nil || hex.EncodeToString(check.Sum(nil)) != report.OriginalSHA256[name] {
			return report, fmt.Errorf("backup verification failed for %s", name)
		}
	}
	audit, _ := json.MarshalIndent(report, "", "  ")
	f, err := os.OpenFile(filepath.Join(backup, "claim.json"), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return report, err
	}
	_, err = f.Write(append(audit, '\n'))
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err == nil {
		err = closeErr
	}
	if err != nil {
		return report, err
	}
	s.Identity = identity
	return report, n.saveState(s)
}
