package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestReadOnlyCreateScopeRejections(t *testing.T) {
	for _, attached := range []bool{false, true} {
		name := "empty"
		if attached {
			name = "attached"
		}
		t.Run(name, func(t *testing.T) {
			var d *dashboard
			var server *httptest.Server
			if attached {
				d, server, _ = testConsole(t)
			} else {
				var err error
				// Server permission alone must not bypass the explicit control opt-in.
				d, err = newDashboard(settings{Root: filepath.Join(t.TempDir(), "dashboard"), Interval: time.Hour, AllowControl: true})
				if err != nil {
					t.Fatal(err)
				}
				server = httptest.NewUnstartedServer(d.handler())
				d.opts.Host = server.Listener.Addr().String()
				server.Start()
				t.Cleanup(func() { d.Close(); server.Close() })
			}
			for _, field := range []string{"valid", "controller_id", "generation", "session_id", "missing"} {
				t.Run(field, func(t *testing.T) {
					d.mu.Lock()
					active, generation, sessions := d.active, d.generation, len(d.sessions)
					req := map[string]any{"kind": "create_session", "name": "rejected", "nodes": []int{3}, "batch": 128,
						"controller_id": d.controllerID, "generation": generation, "session_id": ""}
					if active != nil {
						req["session_id"] = active.ID
					}
					token, host := d.csrf, d.opts.Host
					d.mu.Unlock()
					want, reason := 409, "session generation changed"
					switch field {
					case "valid":
						want, reason = 403, "console is read-only"
					case "generation":
						req[field] = generation + 1
					case "missing":
						delete(req, "controller_id")
						delete(req, "generation")
						delete(req, "session_id")
					default:
						req[field] = "stale"
					}
					body, _ := json.Marshal(req)
					r, _ := http.NewRequest(http.MethodPost, server.URL+"/api/operations", strings.NewReader(string(body)))
					r.Header.Set("Origin", "http://"+host)
					r.Header.Set("X-CSRF-Token", token)
					r.Header.Set("Content-Type", "application/json")
					response, err := server.Client().Do(r)
					if err != nil {
						t.Fatal(err)
					}
					defer response.Body.Close()
					var result map[string]string
					if err = json.NewDecoder(response.Body).Decode(&result); err != nil {
						t.Fatal(err)
					}
					if response.StatusCode != want || result["error"] != reason {
						t.Fatalf("status=%d result=%v; want %d %q", response.StatusCode, result, want, reason)
					}
					d.mu.Lock()
					defer d.mu.Unlock()
					if d.active != active || d.generation != generation || len(d.sessions) != sessions || len(d.operations) != 0 || len(d.jobs) != 0 || len(d.processes) != 0 || d.control || d.busy {
						t.Fatal("rejected create changed session, control, task or process state")
					}
				})
			}
		})
	}
}
