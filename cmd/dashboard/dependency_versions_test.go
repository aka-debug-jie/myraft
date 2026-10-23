package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

// The test binary doubles as a tool without requiring a second Python install.
func init() {
	if os.Getenv("MYRAFT_VERSION_TEST_HELPER") != "1" {
		return
	}
	name := filepath.Base(os.Args[0])
	if (name == "go" || name == "go.exe") && os.Getenv("GOTOOLCHAIN") != "local" {
		os.Exit(2)
	}
	if log := os.Getenv("MYRAFT_TEST_PROBE_LOG"); log != "" {
		f, err := os.OpenFile(log, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
		if err != nil {
			os.Exit(2)
		}
		fmt.Fprintln(f, name)
		f.Close()
	}
	if os.Getenv("MYRAFT_TEST_PROBE_BLOCK") == name {
		if err := os.WriteFile(os.Getenv("MYRAFT_TEST_PROBE_STARTED"), []byte("started"), 0600); err != nil {
			os.Exit(2)
		}
		time.Sleep(time.Minute)
	}
	if os.Getenv("MYRAFT_TEST_PROBE_FAIL") == name {
		os.Exit(1)
	}
	if name == "go" || name == "go.exe" {
		fmt.Println("go version " + os.Getenv("MYRAFT_TEST_GO_VERSION") + " test/amd64")
	} else {
		fmt.Println("Python " + os.Getenv("MYRAFT_TEST_PYTHON_VERSION"))
	}
	os.Exit(0)
}

func versionFixture(t *testing.T, goVersion, pythonVersion string) *dashboard {
	t.Helper()
	root := t.TempDir()
	source := filepath.Join(root, "source")
	bin := filepath.Join(root, "bin")
	for _, dir := range []string{filepath.Join(source, "scripts"), bin} {
		if err := os.MkdirAll(dir, 0700); err != nil {
			t.Fatal(err)
		}
	}
	for name, data := range map[string]string{"go.mod": "module fixture\n\ngo 1.26.3\n", "scripts/benchmark.py": "# fixture\n"} {
		if err := os.WriteFile(filepath.Join(source, name), []byte(data), 0600); err != nil {
			t.Fatal(err)
		}
	}
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(executable)
	if err != nil {
		t.Fatal(err)
	}
	suffix := ""
	if runtime.GOOS == "windows" {
		suffix = ".exe"
		t.Setenv("PATHEXT", ".EXE")
	}
	for _, name := range []string{"go", "python"} {
		if err := os.WriteFile(filepath.Join(bin, name+suffix), data, 0700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", bin)
	t.Setenv("MYRAFT_VERSION_TEST_HELPER", "1")
	t.Setenv("MYRAFT_TEST_GO_VERSION", goVersion)
	t.Setenv("MYRAFT_TEST_PYTHON_VERSION", pythonVersion)
	return &dashboard{opts: settings{Source: source, Python: "python"}, ctx: context.Background()}
}

func TestDependencyRejectsPython310(t *testing.T) {
	d := versionFixture(t, "go1.26.3", "3.10.11")
	report := d.experimentDependencyReport(false)
	if report.Ready || report.Python.Ready {
		t.Fatalf("unsupported interpreter accepted: %+v", report)
	}
}

func TestDependencyVersionRequirements(t *testing.T) {
	tests := []struct{ name, goVersion, pythonVersion, goState, pythonState string }{
		{"minimum", "go1.26.3", "3.12.0", "ready", "ready"},
		{"newer", "go1.27.2", "3.13.12", "ready", "ready"},
		{"old go patch", "go1.26.2", "3.12.9", "unsupported", "ready"},
		{"old python", "go1.26.3", "3.10.11", "ready", "unsupported"},
		{"bad go output", "unknown", "3.12.9", "error", "ready"},
		{"bad python output", "go1.26.3", "unknown", "ready", "error"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			d := versionFixture(t, tt.goVersion, tt.pythonVersion)
			r := d.experimentDependencyReport(false)
			if r.Go.State != tt.goState || r.Python.State != tt.pythonState {
				t.Fatalf("unexpected versions: %+v", r)
			}
			if r.Ready != (tt.goState == "ready" && tt.pythonState == "ready") {
				t.Fatalf("wrong ready: %+v", r)
			}
		})
	}
}

func TestDependencyUsesSourceGoMinimum(t *testing.T) {
	d := versionFixture(t, "go1.27.2", "3.13.12")
	if err := os.WriteFile(filepath.Join(d.opts.Source, "go.mod"), []byte("module fixture\ngo 1.28.1\n"), 0600); err != nil {
		t.Fatal(err)
	}
	r := d.experimentDependencyReport(false)
	if r.Go.State != "unsupported" || r.Go.Required != "1.28.1" {
		t.Fatalf("ignored source minimum: %+v", r)
	}
}

func TestDependencyCacheSharesConcurrentRefresh(t *testing.T) {
	d := versionFixture(t, "go1.26.3", "3.12.9")
	log := filepath.Join(t.TempDir(), "probes.txt")
	t.Setenv("MYRAFT_TEST_PROBE_LOG", log)
	wave := func() {
		var wg sync.WaitGroup
		for range 10 {
			wg.Go(func() {
				if !d.experimentDependencyReport(false).Ready {
					t.Error("probe failed")
				}
			})
		}
		wg.Wait()
	}
	count := func(want int) {
		t.Helper()
		b, err := os.ReadFile(log)
		if err != nil {
			t.Fatal(err)
		}
		if got := len(strings.Fields(string(b))); got != want {
			t.Fatalf("probes=%d want %d", got, want)
		}
	}
	wave()
	count(2)
	wave()
	count(2)
	d.dependencies.mu.Lock()
	d.dependencies.report.ExpiresAt = time.Time{}
	d.dependencies.mu.Unlock()
	wave()
	count(4)
	d.experimentDependencyReport(true)
	count(6)
}

func TestSlowVersionProbeDoesNotHoldSnapshotLock(t *testing.T) {
	d := versionFixture(t, "go1.26.3", "3.12.9")
	ctx, cancel := context.WithCancel(context.Background())
	d.ctx = ctx
	defer cancel()
	name := "go"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	started := filepath.Join(t.TempDir(), "started")
	t.Setenv("MYRAFT_TEST_PROBE_BLOCK", name)
	t.Setenv("MYRAFT_TEST_PROBE_STARTED", started)
	done := make(chan struct{})
	recorder := httptest.NewRecorder()
	go func() { defer close(done); d.sessionHTTP(recorder, httptest.NewRequest("GET", "/api/session", nil)) }()
	defer func() { cancel(); <-done }()
	deadline := time.Now().Add(5 * time.Second)
	for {
		if _, err := os.Stat(started); err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("version helper never started")
		}
		time.Sleep(5 * time.Millisecond)
	}
	if !d.mu.TryLock() {
		t.Fatal("version subprocess holds the snapshot lock")
	}
	d.frameLocked(0, 0)
	d.mu.Unlock()
	cancel()
	<-done
	var response struct {
		Dependencies experimentDependencies `json:"experiment_dependencies"`
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if response.Dependencies.Ready || response.Dependencies.Go.State != "error" {
		t.Fatalf("canceled probe accepted: %+v", response.Dependencies)
	}
}

func TestVersionProbeFailureIsNotUnsupported(t *testing.T) {
	d := versionFixture(t, "go1.26.3", "3.12.9")
	name := "python"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	t.Setenv("MYRAFT_TEST_PROBE_FAIL", name)
	r := d.experimentDependencyReport(false)
	if r.Python.State != "error" || r.Ready {
		t.Fatalf("wrong failure classification: %+v", r)
	}
}

func TestVersionProbeDeadline(t *testing.T) {
	d := versionFixture(t, "go1.26.3", "3.12.9")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	d.ctx = ctx
	name := "go"
	if runtime.GOOS == "windows" {
		name += ".exe"
	}
	started := filepath.Join(t.TempDir(), "started")
	t.Setenv("MYRAFT_TEST_PROBE_BLOCK", name)
	t.Setenv("MYRAFT_TEST_PROBE_STARTED", started)
	done := make(chan experimentDependencies, 1)
	go func() { done <- d.experimentDependencyReport(false) }()
	select {
	case r := <-done:
		if _, err := os.Stat(started); err != nil {
			t.Fatal("helper did not start", err)
		}
		if r.Ready || r.Go.State != "error" || !strings.Contains(r.Go.Reason, "timed out") {
			t.Fatalf("deadline did not reject probe: %+v", r)
		}
	case <-time.After(10 * time.Second):
		cancel()
		<-done
		t.Fatal("version probe exceeded its deadline")
	}
}

func TestExperimentRefreshRejectsChangedTool(t *testing.T) {
	d := versionFixture(t, "go1.26.3", "3.12.9")
	d.opts.Root = t.TempDir()
	if !d.experimentDependencyReport(false).Ready {
		t.Fatal("initial version check failed")
	}
	t.Setenv("MYRAFT_TEST_PYTHON_VERSION", "3.10.11")
	result, err := d.runExperiment(context.Background(), operationJob{})
	if err == nil || result.(map[string]any)["category"] != "environment_unavailable" {
		t.Fatalf("stale readiness accepted: %v %v", result, err)
	}
	if _, err = os.Stat(filepath.Join(d.opts.Root, "experiments")); !os.IsNotExist(err) {
		t.Fatal("runner directory created for unsupported tool")
	}
}
