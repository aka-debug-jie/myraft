package main

import (
	"archive/zip"
	"bytes"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"
)

func (d *dashboard) scrub(v any) any {
	switch value := v.(type) {
	case string:
		return redact(value, d.opts.Root, d.opts.Source, d.opts.NodeBinary)
	case []any:
		for i, x := range value {
			value[i] = d.scrub(x)
		}
		return value
	case map[string]any:
		delete(value, "csrf_token")
		delete(value, "process_id")
		for key, x := range value {
			value[key] = d.scrub(x)
		}
		return value
	default:
		return v
	}
}
func (d *dashboard) exportJSON(v any) ([]byte, error) {
	b, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(b))
	decoder.UseNumber()
	var data any
	if err = decoder.Decode(&data); err != nil {
		return nil, err
	}
	return json.MarshalIndent(d.scrub(data), "", "  ")
}

func sourceManifest(root string) map[string]string {
	result := map[string]string{}
	for _, name := range []string{"go.mod", "main.go", "display.go", "config", "raft", "rpc", "cmd/dashboard", "scripts"} {
		filepath.WalkDir(filepath.Join(root, name), func(path string, entry fs.DirEntry, err error) error {
			if err != nil {
				return nil
			}
			if entry.IsDir() {
				return nil
			}
			if !slices.Contains([]string{".go", ".py", ".ps1", ".js", ".css", ".html", ".mod"}, filepath.Ext(path)) {
				return nil
			}
			relative, e := filepath.Rel(root, path)
			if e != nil {
				return e
			}
			if digest, e := fileSHA(path); e == nil {
				result[filepath.ToSlash(relative)] = digest
			}
			return nil
		})
	}
	return result
}

func (d *dashboard) exportEvidence(job operationJob) (any, error) {
	d.mu.Lock()
	s := d.active
	if s == nil || s.ID != job.session.ID {
		d.mu.Unlock()
		return nil, fmt.Errorf("session changed")
	}
	frame := d.frameLocked(0, 0)
	snap := d.snap
	var receipts []operation
	var experiments []string
	var owned []map[string]any
	for _, op := range d.operations {
		if op.SessionID == s.ID && op.ID != job.op.ID {
			receipts = append(receipts, *op)
			if op.Kind == "experiment" {
				experiments = append(experiments, op.ID)
			}
		}
	}
	for id, p := range d.processes {
		owned = append(owned, map[string]any{"node_id": id, "program": filepath.Base(p.path), "started_at": p.startedAt, "arguments": append([]string(nil), p.args...), "running": p.running, "ownership": "live controller process handle; not reconstructed from PID"})
	}
	d.mu.Unlock()
	dir := filepath.Join(d.opts.Root, "exports")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	path := filepath.Join(dir, job.op.ID+".zip")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return nil, err
	}
	writer := zip.NewWriter(f)
	write := func(name string, data []byte) error {
		out, e := writer.Create(name)
		if e != nil {
			return e
		}
		_, e = out.Write(data)
		return e
	}
	writeJSON := func(name string, value any) error {
		b, e := d.exportJSON(value)
		if e != nil {
			return e
		}
		return write(name, b)
	}
	manifest := map[string]any{"source": "REAL_RPC_AND_CONTROLLER_RECORDS", "export_id": job.op.ID, "captured_at": time.Now().UTC(), "session_id": s.ID, "cluster_id": s.Config.ClusterID, "config": s.Config, "managed_node_binary_sha256": s.BinarySHA256, "local_source_sha256": sourceManifest(d.opts.Source), "source_binding": "local source snapshot and actual binary digest recorded separately; attached external binaries are unrecorded", "window": "latest 128 controller tasks; latest 512 received events; snapshot is an observation, not a linearizable read", "redactions": "controller/source absolute paths, CSRF token, OS process IDs"}
	for _, item := range []struct {
		name  string
		value any
	}{{"manifest.json", manifest}, {"snapshot.json", frame}, {"receipts.json", receipts}, {"owned-processes.json", owned}} {
		if err = writeJSON(item.name, item.value); err != nil {
			writer.Close()
			f.Close()
			return nil, err
		}
	}
	var table bytes.Buffer
	csvOut := csv.NewWriter(&table)
	csvOut.Write([]string{"node_id", "reachable", "role_local", "term", "last", "commit", "applied", "x", "error", "sampled_at"})
	for _, n := range snap.Nodes {
		row := []string{strconv.Itoa(n.ID), strconv.FormatBool(n.Reachable), "unknown", "", "", "", "", "", redact(n.Error, d.opts.Root, d.opts.Source), n.SampledAt.Format(time.RFC3339Nano)}
		if st := n.Status; st != nil {
			row[2] = st.State
			row[3] = strconv.Itoa(st.Term)
			row[4] = strconv.Itoa(st.LastLogIndex)
			row[5] = strconv.Itoa(st.CommitIndex)
			row[6] = strconv.Itoa(st.LastApplied)
			row[7] = strconv.FormatInt(st.X, 10)
		}
		csvOut.Write(row)
	}
	csvOut.Flush()
	if err = csvOut.Error(); err == nil {
		err = write("nodes.csv", table.Bytes())
	}
	if err != nil {
		writer.Close()
		f.Close()
		return nil, err
	}
	allowed := []string{"environment.json", "results.json", "results.csv", "summary.json", "run-status.json", "events.json", "result.json", "last-status.json", "nodes.json", "query-nodes.json", "fixture.json"}
	for _, id := range experiments {
		root := filepath.Join(d.opts.Root, "experiments", id)
		err = filepath.WalkDir(root, func(file string, entry fs.DirEntry, e error) error {
			if os.IsNotExist(e) {
				return nil
			}
			if e != nil {
				return e
			}
			if entry.IsDir() {
				return nil
			}
			if !slices.Contains(allowed, entry.Name()) {
				return nil
			}
			b, e := os.ReadFile(file)
			if e != nil {
				return e
			}
			relative, _ := filepath.Rel(root, file)
			name := "experiments/" + id + "/" + filepath.ToSlash(relative)
			if strings.HasSuffix(file, ".json") {
				decoder := json.NewDecoder(bytes.NewReader(b))
				decoder.UseNumber()
				var value any
				if e = decoder.Decode(&value); e != nil {
					return fmt.Errorf("invalid retained experiment JSON: %w", e)
				}
				return writeJSON(name, value)
			}
			return write(name, []byte(redact(string(b), d.opts.Root, d.opts.Source, d.opts.NodeBinary)))
		})
		if err != nil {
			writer.Close()
			f.Close()
			return nil, err
		}
	}
	if err = writer.Close(); err == nil {
		err = f.Sync()
	}
	ce := f.Close()
	if err == nil {
		err = ce
	}
	if err != nil {
		return nil, err
	}
	digest, err := fileSHA(path)
	if err != nil {
		return nil, err
	}
	d.mu.Lock()
	d.exports[job.op.ID] = path
	d.mu.Unlock()
	return map[string]any{"export_id": job.op.ID, "sha256": digest, "filename": "myraft-evidence.zip", "url": "/api/exports/" + job.op.ID}, nil
}
