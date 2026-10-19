package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"
)

type stalledBrowser struct {
	header   http.Header
	entered  chan struct{}
	deadline time.Time
}

func (w *stalledBrowser) Header() http.Header { return w.header }
func (w *stalledBrowser) WriteHeader(int)     {}
func (w *stalledBrowser) Flush()              {}
func (w *stalledBrowser) SetWriteDeadline(deadline time.Time) error {
	w.deadline = deadline
	return nil
}
func (w *stalledBrowser) Write(p []byte) (int, error) {
	close(w.entered)
	<-time.After(time.Until(w.deadline))
	return 0, os.ErrDeadlineExceeded
}

func TestSlowSSEWriteDoesNotBlockCollectorAndExpires(t *testing.T) {
	d, _, p := testConsole(t)
	w := &stalledBrowser{header: make(http.Header), entered: make(chan struct{})}
	finished := make(chan struct{})
	go func() { d.eventsHTTP(w, httptest.NewRequest("GET", "/api/events", nil)); close(finished) }()
	select {
	case <-w.entered:
	case <-time.After(time.Second):
		t.Fatal("SSE never attempted write")
	}
	before := p.calls.Load()
	collected := make(chan struct{})
	go func() { d.collectRound(); close(collected) }()
	select {
	case <-collected:
	case <-time.After(time.Second):
		t.Fatal("slow browser blocked shared collector")
	}
	if p.calls.Load() != before+1 {
		t.Fatal("collector did not query node")
	}
	d.mu.Lock()
	for i := 0; i < 100; i++ {
		d.broadcastLocked()
	}
	for sub := range d.subs {
		if len(sub.notify) != 1 || sub.dropped < 99 {
			d.mu.Unlock()
			t.Fatal("slow client queue unbounded or loss hidden")
		}
	}
	d.mu.Unlock()
	select {
	case <-finished:
	case <-time.After(3 * time.Second):
		t.Fatal("slow SSE write did not expire")
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	if len(d.subs) != 0 {
		t.Fatal("expired SSE retained subscription")
	}
}
