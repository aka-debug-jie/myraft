//go:build !linux && !darwin && !dragonfly && !freebsd && !netbsd && !openbsd && !windows

package raft

import (
	"fmt"
	"os"
	"runtime"
)

func lockStorage(path string) (*os.File, error) {
	return nil, fmt.Errorf("node storage locking is not supported on %s", runtime.GOOS)
}
