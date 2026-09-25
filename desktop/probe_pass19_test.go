// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"sync/atomic"
	"testing"
	"time"
)

func TestInspectPlanTimesOutWhenProbeCannotReturnPass19(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	release := make(chan struct{})
	stop := time.AfterFunc(600*time.Millisecond, func() { close(release) })
	defer func() {
		if stop.Stop() {
			close(release)
		}
	}()
	started := time.Now()
	plan := inspectPlan(ctx, func(context.Context) Snapshot {
		<-release // Simulate an uninterruptible filesystem or firmware read.
		return Snapshot{Problem: "media"}
	})
	if elapsed := time.Since(started); elapsed > 300*time.Millisecond {
		t.Fatalf("expired readiness probe held request for %s", elapsed)
	}
	if plan.Direct || plan.Problem != "timeout" {
		t.Fatalf("incomplete probe yielded plan: %+v", plan)
	}
	// A repeat click while the first read is still blocked must not create a
	// second blocked worker or use an old snapshot for a restart request.
	retryCtx, retryCancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer retryCancel()
	var retryStarted atomic.Bool
	retry := inspectPlan(retryCtx, func(context.Context) Snapshot {
		retryStarted.Store(true)
		return Snapshot{Problem: "media"}
	})
	if retry.Problem != "timeout" || retryStarted.Load() {
		t.Fatalf("overlapping probe was started: plan=%+v started=%t", retry, retryStarted.Load())
	}
}
