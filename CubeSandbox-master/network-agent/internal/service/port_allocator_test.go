// Copyright (c) 2024 Tencent Inc.
// SPDX-License-Identifier: Apache-2.0
//

package service

import (
	"testing"
)

func TestPortAllocatorExhaustion(t *testing.T) {
	t.Parallel()

	// Range of exactly 3 ports.
	alloc := &portAllocator{
		min:      30000,
		max:      30002,
		next:     30000,
		assigned: make(map[uint16]struct{}),
	}

	p1, err := alloc.Allocate()
	if err != nil {
		t.Fatalf("Allocate 1 error=%v", err)
	}
	p2, err := alloc.Allocate()
	if err != nil {
		t.Fatalf("Allocate 2 error=%v", err)
	}
	p3, err := alloc.Allocate()
	if err != nil {
		t.Fatalf("Allocate 3 error=%v", err)
	}
	if p1 == p2 || p2 == p3 || p1 == p3 {
		t.Fatalf("allocated duplicate ports: %d %d %d", p1, p2, p3)
	}

	// 4th allocation must fail.
	_, err = alloc.Allocate()
	if err == nil {
		t.Fatal("Allocate 4 error=nil, want exhaustion error")
	}
}

func TestPortAllocatorReleaseAndReuse(t *testing.T) {
	t.Parallel()

	alloc := &portAllocator{
		min:      40000,
		max:      40001,
		next:     40000,
		assigned: make(map[uint16]struct{}),
	}

	p1, _ := alloc.Allocate()
	p2, _ := alloc.Allocate()
	if p1 == p2 {
		t.Fatalf("p1==p2==%d, expected distinct ports", p1)
	}

	// Exhausted — release p1 and confirm it can be reallocated.
	alloc.Release(p1)
	p3, err := alloc.Allocate()
	if err != nil {
		t.Fatalf("Allocate after release error=%v", err)
	}
	if p3 != p1 {
		t.Fatalf("reallocated port=%d, want=%d (released port)", p3, p1)
	}
}

func TestPortAllocatorAssignPreventsReallocation(t *testing.T) {
	t.Parallel()

	alloc := &portAllocator{
		min:      50000,
		max:      50001,
		next:     50000,
		assigned: make(map[uint16]struct{}),
	}

	// Pre-assign 50000 as if recovered from persistent state.
	alloc.Assign(50000)

	p, err := alloc.Allocate()
	if err != nil {
		t.Fatalf("Allocate error=%v", err)
	}
	if p == 50000 {
		t.Fatalf("allocated pre-assigned port 50000")
	}
	if p != 50001 {
		t.Fatalf("allocated port=%d, want 50001", p)
	}
}

func TestPortAllocatorConflictWithPreAssignedFull(t *testing.T) {
	t.Parallel()

	// Range of 2 ports, both pre-assigned. Every Allocate call must fail.
	alloc := &portAllocator{
		min:      60000,
		max:      60001,
		next:     60000,
		assigned: map[uint16]struct{}{60000: {}, 60001: {}},
	}

	_, err := alloc.Allocate()
	if err == nil {
		t.Fatal("Allocate error=nil, want conflict/exhaustion error when all ports pre-assigned")
	}
}
