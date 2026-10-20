package main

import (
	"crypto/subtle"
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"myraft/config"
	wire "myraft/rpc"
)

//go:embed static/*
var assets embed.FS

func respond(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}
func failure(w http.ResponseWriter, status int, err error) {
	respond(w, status, map[string]string{"error": err.Error()})
}

func (d *dashboard) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/session", d.sessionHTTP)
	mux.HandleFunc("GET /api/snapshot", func(w http.ResponseWriter, r *http.Request) {
		d.mu.Lock()
		v := d.frameLocked(0, 0)
		d.mu.Unlock()
		respond(w, 200, v)
	})
	mux.HandleFunc("GET /api/events", d.eventsHTTP)
	mux.HandleFunc("GET /api/nodes/{id}/logs", d.logsHTTP)
	mux.HandleFunc("GET /api/operations/{id}", func(w http.ResponseWriter, r *http.Request) {
		d.mu.Lock()
		for _, op := range d.operations {
			if op.ID == r.PathValue("id") {
				copy := *op
				d.mu.Unlock()
				respond(w, 200, copy)
				return
			}
		}
		d.mu.Unlock()
		failure(w, 404, fmt.Errorf("operation not found"))
	})
	mux.HandleFunc("POST /api/operations", d.operationsHTTP)
	mux.HandleFunc("GET /api/exports/{id}", d.exportsHTTP)
	sub, _ := fs.Sub(assets, "static")
	mux.Handle("GET /", http.FileServer(http.FS(sub)))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host != d.opts.Host {
			http.Error(w, "invalid Host", 403)
			return
		}
		origin := r.Header.Get("Origin")
		if origin != "" && origin != "http://"+d.opts.Host {
			http.Error(w, "invalid Origin", 403)
			return
		}
		if r.Method == http.MethodPost && (origin != "http://"+d.opts.Host || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-CSRF-Token")), []byte(d.csrf)) != 1) {
			http.Error(w, "same-origin CSRF token required", 403)
			return
		}
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
		mux.ServeHTTP(w, r)
	})
}

func (d *dashboard) sessionHTTP(w http.ResponseWriter, r *http.Request) {
	d.mu.Lock()
	list := make([]session, 0, len(d.sessions))
	for _, s := range d.sessions {
		list = append(list, *s)
	}
	sort.Slice(list, func(i, j int) bool { return list[i].CreatedAt.Before(list[j].CreatedAt) })
	view := map[string]any{"controller_id": d.controllerID, "mode": "REAL", "csrf_token": d.csrf, "session": d.active, "sessions": list, "generation": d.generation, "control_allowed": d.opts.AllowControl, "control_enabled": d.control, "poll_ms": d.opts.Interval.Milliseconds(), "network_partition_supported": false, "experiment_dependencies": d.experimentDependencyReport()}
	d.mu.Unlock()
	respond(w, 200, view)
}

func (d *dashboard) frameLocked(after, dropped uint64) any {
	events := make([]consoleEvent, 0)
	gap := false
	if after > d.eventSeq {
		after = 0
		gap = true
	}
	if len(d.events) > 0 {
		gap = gap || after+1 < d.events[0].Seq
		for _, e := range d.events {
			if e.Seq > after {
				events = append(events, e)
			}
		}
	}
	ops := make([]operation, 0, len(d.operations))
	for _, op := range d.operations {
		if d.active != nil && op.SessionID != "" && op.SessionID != d.active.ID {
			continue
		}
		ops = append(ops, *op)
	}
	if len(ops) > 20 {
		ops = ops[len(ops)-20:]
	}
	return map[string]any{"controller_id": d.controllerID, "mode": "REAL", "session": d.active, "generation": d.generation, "snapshot": d.snap, "events": events, "event_seq": d.eventSeq, "gap": gap, "stream_dropped": dropped, "operations": ops, "current_verification": d.currentCheck, "history_verification": d.historyCheck, "checkpoint": d.checkpoint, "target": d.target, "control_enabled": d.control, "busy": d.busy}
}

func (d *dashboard) eventsHTTP(w http.ResponseWriter, r *http.Request) {
	after, _ := strconv.ParseUint(r.Header.Get("Last-Event-ID"), 10, 64)
	sub := &subscription{notify: make(chan struct{}, 1)}
	d.mu.Lock()
	if len(d.subs) >= 64 {
		d.mu.Unlock()
		failure(w, 429, fmt.Errorf("subscriber limit reached"))
		return
	}
	d.subs[sub] = true
	sub.notify <- struct{}{}
	d.mu.Unlock()
	defer func() { d.mu.Lock(); delete(d.subs, sub); d.mu.Unlock() }()
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Accel-Buffering", "no")
	response := http.NewResponseController(w)
	keepalive := time.NewTicker(10 * time.Second)
	defer keepalive.Stop()
	for {
		select {
		case <-d.ctx.Done():
			return
		case <-r.Context().Done():
			return
		case <-keepalive.C:
			response.SetWriteDeadline(time.Now().Add(2 * time.Second))
			if _, err := fmt.Fprint(w, ": keepalive\n\n"); err != nil {
				return
			}
			if err := response.Flush(); err != nil {
				return
			}
		case <-sub.notify:
			d.mu.Lock()
			frame := d.frameLocked(after, sub.dropped)
			seq := d.eventSeq
			d.mu.Unlock()
			b, err := json.Marshal(frame)
			if err != nil {
				return
			}
			response.SetWriteDeadline(time.Now().Add(2 * time.Second))
			if _, err = fmt.Fprintf(w, "id: %d\nevent: frame\ndata: %s\n\n", seq, b); err != nil {
				return
			}
			if err = response.Flush(); err != nil {
				return
			}
			after = seq
		}
	}
}

func (d *dashboard) logsHTTP(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.Atoi(r.PathValue("id"))
	if err != nil {
		failure(w, 400, err)
		return
	}
	from, err := strconv.Atoi(r.URL.Query().Get("from"))
	if err != nil {
		failure(w, 400, fmt.Errorf("positive from required"))
		return
	}
	limit := 128
	if raw := r.URL.Query().Get("limit"); raw != "" {
		limit, err = strconv.Atoi(raw)
	}
	if err != nil || from < 1 || limit < 1 || limit > 256 {
		failure(w, 400, fmt.Errorf("range must have positive from and limit 1..256"))
		return
	}
	d.mu.Lock()
	s, gen := d.active, d.generation
	d.mu.Unlock()
	if s == nil || r.URL.Query().Get("session_id") != s.ID || r.URL.Query().Get("generation") != strconv.FormatUint(gen, 10) {
		failure(w, 409, fmt.Errorf("session changed"))
		return
	}
	peers, _ := s.Config.Peers()
	addr, ok := peers[id]
	if !ok {
		failure(w, 404, fmt.Errorf("unregistered node"))
		return
	}
	var result wire.LogRangeReply
	d.monitorRPCs.Add(1)
	if err := wire.CallContext(r.Context(), addr, "RaftNode.LogRange", &wire.LogRangeArgs{From: from, Limit: limit}, &result, time.Second); err != nil {
		failure(w, 502, err)
		return
	}
	d.mu.Lock()
	current := d.active != nil && d.active.ID == s.ID && d.generation == gen
	d.mu.Unlock()
	if !current {
		failure(w, 409, fmt.Errorf("session changed"))
		return
	}
	identity, _ := config.FixedIdentity(s.Config.ClusterID, peers)
	if result.NodeID != id || result.ClusterID != s.Config.ClusterID || result.MembershipHash != identity.MembershipHash() {
		failure(w, 502, fmt.Errorf("node identity mismatch"))
		return
	}
	respond(w, 200, map[string]any{"session_id": s.ID, "generation": gen, "range": result})
}

func (d *dashboard) exportsHTTP(w http.ResponseWriter, r *http.Request) {
	d.mu.Lock()
	path := d.exports[r.PathValue("id")]
	d.mu.Unlock()
	if path == "" {
		failure(w, 404, fmt.Errorf("export not registered"))
		return
	}
	w.Header().Set("Content-Disposition", "attachment; filename=\"myraft-evidence.zip\"")
	w.Header().Set("Content-Type", "application/zip")
	http.ServeFile(w, r, path)
}

func redact(text string, paths ...string) string {
	for _, p := range paths {
		if p != "" {
			text = strings.ReplaceAll(text, p, "<local-path>")
		}
	}
	return text
}
