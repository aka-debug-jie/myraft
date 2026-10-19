package main

import (
	"context"
	"flag"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"runtime"
	"syscall"
	"time"
)

func main() {
	listen := flag.String("listen", "127.0.0.1:8080", "loopback HTTP address")
	configPath := flag.String("config", "", "attach this shared configuration (read-only by default)")
	root := flag.String("data-root", "dashboard-runs", "controller session and evidence directory")
	binary := flag.String("node-bin", "", "trusted raft-node executable for managed sessions")
	source := flag.String("source-dir", ".", "trusted source directory for independent experiments")
	python := flag.String("python", "python", "Python executable for experiments")
	control := flag.Bool("allow-control", false, "allow explicit browser opt-in to local control")
	interval := flag.Duration("poll", time.Second, "shared collector interval (minimum 200ms)")
	flag.Parse()
	if *binary == "" {
		*binary = "raft-node"
		if runtime.GOOS == "windows" {
			*binary += ".exe"
		}
	}
	host, _, err := net.SplitHostPort(*listen)
	if err != nil || net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback() {
		fmt.Fprintln(os.Stderr, "dashboard: listen must be an explicit loopback IP:port")
		os.Exit(1)
	}
	l, err := net.Listen("tcp", *listen)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	rootAbs, _ := filepath.Abs(*root)
	binaryAbs, _ := filepath.Abs(*binary)
	sourceAbs, _ := filepath.Abs(*source)
	d, err := newDashboard(settings{Root: rootAbs, NodeBinary: binaryAbs, Source: sourceAbs, Python: *python, Config: *configPath, AllowControl: *control, Interval: *interval, Host: l.Addr().String()})
	if err != nil {
		l.Close()
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	server := &http.Server{Handler: d.handler(), ReadHeaderTimeout: 3 * time.Second, IdleTimeout: 30 * time.Second}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		d.Close()
		shutdown, cancel := context.WithTimeout(context.Background(), 3*time.Second)
		defer cancel()
		server.Shutdown(shutdown)
	}()
	fmt.Printf("MyRaft Console REAL: http://%s (read-only; browser closure does not stop nodes)\n", l.Addr())
	if err := server.Serve(l); err != nil && err != http.ErrServerClosed {
		fmt.Fprintln(os.Stderr, err)
	}
	d.Close()
}
