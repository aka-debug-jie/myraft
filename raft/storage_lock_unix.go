//go:build linux || darwin || dragonfly || freebsd || netbsd || openbsd

package raft

import (
	"os"
	"syscall"
)

func lockStorage(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, err
	}
	// Keep the inode: unlinking a lock file can let a second owner lock a new file.
	return f, nil
}
