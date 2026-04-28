// Copyright (c) 2024 Tencent Inc.
// SPDX-License-Identifier: Apache-2.0
//

package service

import (
	"net"
	"os"
	"testing"

	"github.com/tencentcloud/CubeSandbox/CubeNet/cubevs"
	"github.com/vishvananda/netlink"
)

// TestNewLocalServiceMissingEthNameFails verifies that an empty eth_name causes
// NewLocalService to return an error immediately, before any kernel interaction.
func TestNewLocalServiceMissingEthNameFails(t *testing.T) {
	t.Parallel()

	_, err := NewLocalService(DefaultConfig())
	if err == nil {
		t.Fatal("NewLocalService error=nil, want missing eth_name error")
	}
}

// TestEnsureNetworkIdempotentSameSandboxID verifies that calling EnsureNetwork
// twice with the same sandbox ID returns the same response without creating a
// second TAP device (idempotent re-entry path).
func TestEnsureNetworkIdempotentSameSandboxID(t *testing.T) {
	oldNewTap := newTapFunc
	oldRestore := restoreTapFunc
	oldAddTap := cubevsAddTAPDevice
	oldDelTap := cubevsDelTAPDevice
	oldAddPort := cubevsAddPortMap
	oldRouteList := netlinkRouteListFiltered
	oldRouteReplace := netlinkRouteReplace
	t.Cleanup(func() {
		newTapFunc = oldNewTap
		restoreTapFunc = oldRestore
		cubevsAddTAPDevice = oldAddTap
		cubevsDelTAPDevice = oldDelTap
		cubevsAddPortMap = oldAddPort
		netlinkRouteListFiltered = oldRouteList
		netlinkRouteReplace = oldRouteReplace
	})

	tapCreations := 0
	newTapFunc = func(ip net.IP, _ string, _ int, _ int) (*tapDevice, error) {
		tapCreations++
		return &tapDevice{
			Name:  tapName(ip.String()),
			Index: 12,
			IP:    ip,
			File:  newTestTapFile(t),
		}, nil
	}
	restoreTapFunc = func(tap *tapDevice, _ int, _ string, _ int) (*tapDevice, error) {
		if tap.File == nil {
			tap.File = newTestTapFile(t)
		}
		return tap, nil
	}
	cubevsAddTAPDevice = func(uint32, net.IP, string, uint32, cubevs.MVMOptions) error { return nil }
	cubevsDelTAPDevice = func(uint32, net.IP) error { return nil }
	cubevsAddPortMap = func(uint32, uint16, uint16) error { return nil }
	netlinkRouteListFiltered = func(_ int, _ *netlink.Route, _ uint64) ([]netlink.Route, error) {
		return nil, nil
	}
	netlinkRouteReplace = func(_ *netlink.Route) error { return nil }

	store, err := newStateStore(t.TempDir())
	if err != nil {
		t.Fatalf("newStateStore error=%v", err)
	}
	allocator, err := newIPAllocator("192.168.0.0/18")
	if err != nil {
		t.Fatalf("newIPAllocator error=%v", err)
	}
	svc := &localService{
		store:             store,
		allocator:         allocator,
		ports:             &portAllocator{min: 20000, max: 29999, next: 20000, assigned: make(map[uint16]struct{})},
		cfg:               Config{CIDR: "192.168.0.0/18", MVMInnerIP: "169.254.68.6", MVMMacAddr: "20:90:6f:fc:fc:fc", MvmGwDestIP: "169.254.68.5", MvmMask: 30, MvmMtu: 1300},
		cubeDev:           &cubeDev{Index: 16},
		states:            make(map[string]*managedState),
		destroyFailedTaps: make(map[string]*tapDevice),
	}

	req := &EnsureNetworkRequest{SandboxID: "sandbox-idem"}

	first, err := svc.EnsureNetwork(t.Context(), req)
	if err != nil {
		t.Fatalf("EnsureNetwork first error=%v", err)
	}
	if tapCreations != 1 {
		t.Fatalf("tapCreations after first EnsureNetwork=%d, want 1", tapCreations)
	}

	// Second call, same sandbox ID — must return identical handle, create no new TAP.
	second, err := svc.EnsureNetwork(t.Context(), req)
	if err != nil {
		t.Fatalf("EnsureNetwork second error=%v", err)
	}
	if tapCreations != 1 {
		t.Fatalf("tapCreations after second EnsureNetwork=%d, want still 1 (idempotent)", tapCreations)
	}
	if first.NetworkHandle != second.NetworkHandle {
		t.Fatalf("NetworkHandle changed on idempotent call: first=%q second=%q", first.NetworkHandle, second.NetworkHandle)
	}
	if first.PersistMetadata["sandbox_ip"] != second.PersistMetadata["sandbox_ip"] {
		t.Fatalf("sandbox_ip changed on idempotent call: first=%q second=%q",
			first.PersistMetadata["sandbox_ip"], second.PersistMetadata["sandbox_ip"])
	}

	// Confirm only one entry in the state map.
	svc.mu.Lock()
	stateCount := len(svc.states)
	svc.mu.Unlock()
	if stateCount != 1 {
		t.Fatalf("state map len=%d after two EnsureNetwork for same sandbox, want 1", stateCount)
	}

	// Third call after stashing a nil to simulate a re-used variable — still idempotent.
	var stateFile *os.File
	_ = stateFile
	third, err := svc.EnsureNetwork(t.Context(), &EnsureNetworkRequest{SandboxID: "sandbox-idem"})
	if err != nil {
		t.Fatalf("EnsureNetwork third error=%v", err)
	}
	if third.NetworkHandle != first.NetworkHandle {
		t.Fatalf("NetworkHandle diverged on third call: first=%q third=%q", first.NetworkHandle, third.NetworkHandle)
	}
}
