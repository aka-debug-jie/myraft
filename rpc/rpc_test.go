package rpc

import (
	"net"
	stdrpc "net/rpc"
	"sync/atomic"
	"testing"
	"time"
)

type echoService struct{}

func (*echoService) Echo(v *int, r *int) error { *r = *v; return nil }
func TestPeerClientSurvivesIdleDeadline(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := stdrpc.NewServer()
	if err = server.RegisterName("Echo", new(echoService)); err != nil {
		t.Fatal(err)
	}
	var connections atomic.Int32
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			conn, err := l.Accept()
			if err != nil {
				return
			}
			connections.Add(1)
			go func() { defer conn.Close(); server.ServeConn(conn) }()
		}
	}()
	defer func() { l.Close(); <-done }()
	var client PeerClient
	defer client.Close()
	in, out := 7, 0
	if err = client.Call(l.Addr().String(), "Echo.Echo", &in, &out, 100*time.Millisecond); err != nil || out != 7 {
		t.Fatalf("first call %v %d", err, out)
	}
	time.Sleep(200 * time.Millisecond)
	if err = client.Call(l.Addr().String(), "Echo.Echo", &in, &out, 100*time.Millisecond); err != nil || connections.Load() != 1 {
		t.Fatalf("idle connection failed %v connections=%d", err, connections.Load())
	}
	client.Close()
	if err = client.Call(l.Addr().String(), "Echo.Echo", &in, &out, 100*time.Millisecond); err != nil || connections.Load() != 2 {
		t.Fatalf("reconnection failed %v", err)
	}
}

type slowService struct{ release chan struct{} }

func (s *slowService) Echo(v *int, r *int) error {
	if *v == 1 {
		<-s.release
	}
	*r = *v
	return nil
}
func TestPeerTimeoutReconnectsWithoutLateReply(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	receiver := &slowService{release: make(chan struct{})}
	server := stdrpc.NewServer()
	if err = server.RegisterName("Echo", receiver); err != nil {
		t.Fatal(err)
	}
	var count atomic.Int32
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			conn, err := l.Accept()
			if err != nil {
				return
			}
			count.Add(1)
			go func() { defer conn.Close(); server.ServeConn(conn) }()
		}
	}()
	defer func() { l.Close(); <-done }()
	var client PeerClient
	defer client.Close()
	first, out := 1, 0
	if err = client.Call(l.Addr().String(), "Echo.Echo", &first, &out, 60*time.Millisecond); err == nil {
		close(receiver.release)
		t.Fatal("blocked request did not time out")
	}
	close(receiver.release)
	second := 2
	if err = client.Call(l.Addr().String(), "Echo.Echo", &second, &out, time.Second); err != nil || out != 2 || count.Load() != 2 {
		t.Fatalf("late reply affected new connection: out=%d conns=%d err=%v", out, count.Load(), err)
	}
}
