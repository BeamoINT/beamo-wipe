// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func testApp() *app {
	return &app{host: "127.0.0.1:12345", token: strings.Repeat("a", 64), p: Plan{Direct: true, Fingerprint: strings.Repeat("b", 64)}, close: make(chan struct{}), lastSeen: time.Now()}
}
func request(a *app, path, body string) *httptest.ResponseRecorder {
	r := httptest.NewRequest("POST", "http://"+a.host+path, strings.NewReader(body))
	r.Header.Set("Origin", "http://"+a.host)
	r.Header.Set("X-Beamo-Token", a.token)
	r.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	a.serve(w, r)
	return w
}
func TestRestartRequiresExplicitConfirmationAndIsSingleUse(t *testing.T) {
	a := testApp()
	var calls atomic.Int32
	a.restart = func(context.Context, string) error { calls.Add(1); return nil }
	if request(a, "/api/restart", `{"confirm":false}`).Code != 409 {
		t.Fatal("confirmation not required")
	}
	if request(a, "/api/restart", `{"confirm":true}`).Code != 200 {
		t.Fatal("confirmed action failed")
	}
	if request(a, "/api/restart", `{"confirm":true}`).Code != 409 || calls.Load() != 1 {
		t.Fatal("plan reused")
	}
}
func TestUnauthorizedRequestsCannotRestart(t *testing.T) {
	for _, variant := range []string{"host", "origin", "token", "method", "type"} {
		t.Run(variant, func(t *testing.T) {
			a := testApp()
			a.restart = func(context.Context, string) error { t.Fatal("unauthorized restart"); return nil }
			r := httptest.NewRequest("POST", "http://"+a.host+"/api/restart", strings.NewReader(`{"confirm":true}`))
			r.Header.Set("Origin", "http://"+a.host)
			r.Header.Set("X-Beamo-Token", a.token)
			r.Header.Set("Content-Type", "application/json")
			switch variant {
			case "host":
				r.Host = "example.com"
			case "origin":
				r.Header.Set("Origin", "https://example.com")
			case "token":
				r.Header.Set("X-Beamo-Token", "wrong")
			case "method":
				r.Method = "GET"
			case "type":
				r.Header.Set("Content-Type", "text/plain")
			}
			w := httptest.NewRecorder()
			a.serve(w, r)
			if w.Code < 400 {
				t.Fatal("unauthorized request accepted")
			}
		})
	}
}
func TestPreviewNeverInvokesPlatformMutation(t *testing.T) {
	a := testApp()
	a.preview = true
	a.restart = func(context.Context, string) error { t.Fatal("preview invoked mutation"); return nil }
	if w := request(a, "/api/restart", `{"confirm":true}`); w.Code != 200 || !strings.Contains(w.Body.String(), "Preview complete") {
		t.Fatal(w.Body.String())
	}
}
func TestMalformedRequestsCannotRestart(t *testing.T) {
	for _, body := range []string{``, `null`, `{"confirm":true,"target":"/dev/sda"}`, `{"confirm":"true"}`, `{"confirm":true}{}`, strings.Repeat(" ", 300) + `{}`} {
		a := testApp()
		a.restart = func(context.Context, string) error { t.Fatal("malformed request invoked mutation"); return nil }
		if request(a, "/api/restart", body).Code < 400 {
			t.Fatal("accepted", body)
		}
	}
}
func TestBusyRejectsCloseAndRepeatedRestart(t *testing.T) {
	a := testApp()
	a.busy = true
	for _, path := range []string{"/api/restart", "/api/close", "/api/check"} {
		if request(a, path, `{"confirm":true}`).Code != 409 {
			t.Fatal(path)
		}
	}
}
func TestAssetsHaveNoPrivilegeTokenOrExternalResources(t *testing.T) {
	a := testApp()
	for _, path := range []string{"/", "/app.js", "/style.css"} {
		r := httptest.NewRequest("GET", "http://"+a.host+path, nil)
		w := httptest.NewRecorder()
		a.serve(w, r)
		if w.Code != 200 || strings.Contains(w.Body.String(), a.token) || !strings.Contains(w.Header().Get("Content-Security-Policy"), "frame-ancestors 'none'") {
			t.Fatal(path)
		}
	}
}
