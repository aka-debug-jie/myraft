//go:build windows

package main

import (
	"fmt"
	"syscall"
	"unsafe"
)

func setNodeTitle(id int) {
	title, _ := syscall.UTF16PtrFromString(fmt.Sprintf("MyRaft Node %d", id))
	syscall.NewLazyDLL("kernel32.dll").NewProc("SetConsoleTitleW").Call(uintptr(unsafe.Pointer(title)))
}
