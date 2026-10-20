package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestExperimentReadPreservesPublishedRows(t *testing.T) {
	dir := t.TempDir()
	previous := experimentResult{
		Rows: []map[string]any{{"platform": "published", "source_sha256": "published-source"}},
	}
	// The runner may be in the middle of replacing results.json. Its last
	// published result is still being serialized for an SSE subscriber.
	if err := os.WriteFile(filepath.Join(dir, "results.json"), []byte("["), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "environment.json"), []byte(`{"platform":"new-environment"}`), 0600); err != nil {
		t.Fatal(err)
	}
	next := readExperiment(dir, previous)
	if previous.Rows[0]["platform"] != "published" || previous.Rows[0]["source_sha256"] != "published-source" {
		t.Fatal("refresh mutated rows already published to HTTP/SSE")
	}
	if next.Rows[0]["platform"] != "new-environment" {
		t.Fatal("new snapshot did not receive its environment")
	}
}
