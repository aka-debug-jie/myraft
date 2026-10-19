package raft

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"hash/crc32"
	"io"
	"os"
	"path/filepath"

	"myraft/config"
	wire "myraft/rpc"
)

type persistentState struct {
	NodeID      int             `json:"node_id"`
	Term        int             `json:"term"`
	VotedFor    int             `json:"voted_for"`
	CommitIndex int             `json:"commit_index"`
	CommitHash  string          `json:"commit_hash"`
	Identity    config.Identity `json:"identity"`
}
type logRecord struct {
	From    int             `json:"from"`
	Entries []wire.LogEntry `json:"entries"`
}

const maxWALPayload = 32 << 20

func (n *Node) loadState() (err error) {
	if err := os.MkdirAll(n.options.DataDir, 0755); err != nil {
		return err
	}
	lockPath := filepath.Join(n.options.DataDir, fmt.Sprintf("node-%d.lock", n.id))
	if n.storageLock, err = lockStorage(lockPath); err != nil {
		return fmt.Errorf("lock node %d storage (another instance may be using it): %w", n.id, err)
	}
	defer func() {
		if err != nil {
			if n.wal != nil {
				n.wal.Close()
			}
			n.storageLock.Close()
		}
	}()
	n.statePath = filepath.Join(n.options.DataDir, fmt.Sprintf("node-%d-state.json", n.id))
	savedHash := ""
	b, err := os.ReadFile(n.statePath)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	if os.IsNotExist(err) {
		if _, statErr := os.Stat(filepath.Join(n.options.DataDir, fmt.Sprintf("node-%d-log.wal", n.id))); !os.IsNotExist(statErr) {
			return fmt.Errorf("legacy data requires explicit original-configuration claim before recovery")
		}
		if err = n.saveState(n.diskState(0, -1, 0, n.committedHash)); err != nil {
			return err
		}
	} else if err == nil {
		var s persistentState
		if err = json.Unmarshal(b, &s); err != nil {
			return fmt.Errorf("invalid persistent state: %w", err)
		}
		if s.Identity.ClusterID == "" {
			return fmt.Errorf("legacy data requires explicit original-configuration claim before recovery")
		}
		if !n.identity.Equal(s.Identity) {
			return fmt.Errorf("stored cluster/member identity differs; use the original configuration or a new data directory")
		}
		if s.NodeID != n.id || s.Term < 0 || (s.VotedFor != -1 && s.VotedFor < 1) || s.CommitIndex < 0 {
			return fmt.Errorf("invalid persistent state in %s", n.statePath)
		}
		n.term, n.votedFor, n.commitIndex = s.Term, s.VotedFor, s.CommitIndex
		savedHash = s.CommitHash
	}
	if err = n.loadLog(false); err != nil {
		return err
	}
	if n.commitIndex > n.lastIndexLocked() || n.log[n.lastIndexLocked()].Term > n.term {
		return fmt.Errorf("persistent metadata does not cover the recovered log")
	}
	n.commitDigest = sha256.New()
	appendLogHash(n.commitDigest, n.log[1:n.commitIndex+1])
	n.committedHash = hex.EncodeToString(n.commitDigest.Sum(nil))
	if (n.commitIndex > 0 || savedHash != "") && savedHash != n.committedHash {
		return fmt.Errorf("committed log hash mismatch: refusing inconsistent recovery")
	}
	if n.recoveryTruncate > 0 {
		if err := n.trimWAL(n.recoveryTruncate); err != nil {
			return err
		}
	}
	n.applyLocked()
	n.eventLocked("node_recovered index=%d commit=%d applied=%d x=%d", n.lastIndexLocked(), n.commitIndex, n.lastApplied, n.x)
	return nil
}

func (n *Node) loadLog(readOnly bool) error {
	p := filepath.Join(n.options.DataDir, fmt.Sprintf("node-%d-log.wal", n.id))
	flags := os.O_RDWR
	if n.commitIndex == 0 {
		flags |= os.O_CREATE
	}
	if readOnly {
		flags = os.O_RDONLY
	}
	f, err := os.OpenFile(p, flags, 0644)
	if readOnly && os.IsNotExist(err) && n.commitIndex == 0 {
		return nil
	}
	if err != nil {
		return err
	}
	n.wal = f
	header := make([]byte, 16)
	copy(header, "RAFTLOG2")
	binary.LittleEndian.PutUint64(header[8:], uint64(n.id))
	info, err := f.Stat()
	if err != nil {
		return err
	}
	if info.Size() == 0 {
		if n.commitIndex > 0 {
			return fmt.Errorf("empty WAL cannot recover committed entries")
		}
		if readOnly {
			return nil
		}
		if _, err = f.Write(header); err != nil {
			return err
		}
		return f.Sync()
	}
	got := make([]byte, len(header))
	if _, err = io.ReadFull(f, got); err != nil {
		return fmt.Errorf("invalid WAL header: %w", err)
	}
	if !bytes.Equal(got, header) {
		return fmt.Errorf("invalid WAL version or node identity")
	}
	offset := int64(len(header))
	for {
		var frame [12]byte
		read, e := io.ReadFull(f, frame[:])
		if e == io.EOF && read == 0 {
			break
		}
		if e == io.ErrUnexpectedEOF {
			n.recoveryTruncate = offset
			return nil
		}
		if e != nil {
			return e
		}
		if crc32.ChecksumIEEE(frame[:8]) != binary.LittleEndian.Uint32(frame[8:]) {
			return fmt.Errorf("WAL frame header checksum mismatch at %d", offset)
		}
		size := binary.LittleEndian.Uint32(frame[:4])
		if size == 0 || size > maxWALPayload {
			return fmt.Errorf("invalid WAL frame length at %d", offset)
		}
		payload := make([]byte, int(size))
		if _, e = io.ReadFull(f, payload); e == io.EOF || e == io.ErrUnexpectedEOF {
			n.recoveryTruncate = offset
			return nil
		}
		if e != nil {
			return e
		}
		if crc32.ChecksumIEEE(payload) != binary.LittleEndian.Uint32(frame[4:8]) {
			return fmt.Errorf("WAL checksum mismatch at %d", offset)
		}
		var record logRecord
		if e = json.Unmarshal(payload, &record); e != nil {
			return fmt.Errorf("invalid WAL record: %w", e)
		}
		if e = n.validateSuffix(record.From, record.Entries); e != nil {
			return e
		}
		// The JSON checkpoint is the latest commit, not the commit at this historical record.
		n.log = append(n.log[:record.From], record.Entries...)
		offset += 12 + int64(size)
	}
	_, err = f.Seek(0, io.SeekEnd)
	return err
}

func (n *Node) trimWAL(offset int64) error {
	if err := n.wal.Truncate(offset); err != nil {
		return err
	}
	if err := n.wal.Sync(); err != nil {
		return err
	}
	_, err := n.wal.Seek(offset, io.SeekStart)
	return err
}

func (n *Node) validateSuffix(from int, entries []wire.LogEntry) error {
	if from < 1 || from > len(n.log) || len(entries) == 0 {
		return fmt.Errorf("invalid log suffix at %d", from)
	}
	previous := n.log[from-1].Term
	for i, e := range entries {
		if e.Index != from+i || e.Term < previous || e.Term < 1 {
			return fmt.Errorf("invalid log entry index/term at %d", from+i)
		}
		if err := validateCommand(e.Command); err != nil {
			return err
		}
		previous = e.Term
	}
	return nil
}

func (n *Node) replaceLogLocked(from int, entries []wire.LogEntry) error {
	if from <= n.commitIndex {
		err := fmt.Errorf("attempt to replace committed index %d", from)
		n.failLocked(err)
		return err
	}
	if err := n.validateSuffix(from, entries); err != nil {
		return err
	}
	payload, err := json.Marshal(logRecord{From: from, Entries: entries})
	if err != nil {
		return err
	}
	if len(payload) > maxWALPayload {
		return fmt.Errorf("WAL payload exceeds %d bytes", maxWALPayload)
	}
	frame := make([]byte, 12+len(payload))
	binary.LittleEndian.PutUint32(frame[:4], uint32(len(payload)))
	binary.LittleEndian.PutUint32(frame[4:8], crc32.ChecksumIEEE(payload))
	binary.LittleEndian.PutUint32(frame[8:12], crc32.ChecksumIEEE(frame[:8]))
	copy(frame[12:], payload)
	written, err := n.wal.Write(frame)
	if err == nil && written != len(frame) {
		err = io.ErrShortWrite
	}
	if err == nil {
		err = n.wal.Sync()
	}
	if err != nil {
		err = fmt.Errorf("persist command log: %w", err)
		n.failLocked(err)
		return err
	}
	n.log = append(n.log[:from], entries...)
	n.revision++
	return nil
}

func (n *Node) appendEntriesLocked(entries []wire.LogEntry) error {
	return n.replaceLogLocked(len(n.log), entries)
}

func (n *Node) persistLocked(term, vote int) error {
	if err := n.saveState(n.diskState(term, vote, n.commitIndex, n.committedHash)); err != nil {
		err = fmt.Errorf("persist election state: %w", err)
		n.failLocked(err)
		return err
	}
	n.term, n.votedFor = term, vote
	n.revision++
	return nil
}

func (n *Node) commitLocked(index int) error {
	if err := n.availableLocked(); err != nil {
		return err
	}
	if index <= n.commitIndex {
		return nil
	}
	if index > n.lastIndexLocked() {
		return fmt.Errorf("commit index beyond log")
	}
	// Committed entries never change. On storage failure the node fails closed;
	// the advanced digest cannot be reused until recovery rebuilds it from disk.
	appendLogHash(n.commitDigest, n.log[n.commitIndex+1:index+1])
	hash := hex.EncodeToString(n.commitDigest.Sum(nil))
	if err := n.saveState(n.diskState(n.term, n.votedFor, index, hash)); err != nil {
		err = fmt.Errorf("persist commit: %w", err)
		n.failLocked(err)
		return err
	}
	n.commitIndex = index
	n.revision++
	n.committedHash = hash
	n.eventLocked("log_committed index=%d", index)
	n.applyLocked()
	n.notifyLocked()
	return nil
}

func (n *Node) diskState(term, vote, commit int, digest string) persistentState {
	return persistentState{NodeID: n.id, Term: term, VotedFor: vote, CommitIndex: commit, CommitHash: digest, Identity: n.identity}
}

// File replacement is used for process-crash recovery; whole-machine power loss is not qualified.
func (n *Node) saveState(s persistentState) error {
	b, err := json.Marshal(s)
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(n.options.DataDir, fmt.Sprintf(".node-%d-*.tmp", n.id))
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(append(b, '\n')); err != nil {
		f.Close()
		return err
	}
	if err = f.Sync(); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), n.statePath)
}
