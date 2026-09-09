// SPDX-License-Identifier: GPL-3.0-or-later
package main

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"runtime"
	"strings"
	"sync"
	"time"
)

//go:embed web/*
var assets embed.FS

var version = "development"
var sourceCommit = "unknown"
var sourceDirty = "false"

type view struct {
	Ready   bool   `json:"ready"`
	Preview bool   `json:"preview"`
	Title   string `json:"title"`
	Detail  string `json:"detail"`
	Version string `json:"version"`
}

func planView(p Plan, preview bool) view {
	v := view{Ready: p.Direct, Preview: preview, Version: version, Title: "Ready for a guided restart", Detail: "Save your work and close your applications. Keep the Beamo USB connected. After restarting, choose and confirm the disk. Nothing is erased by this launcher."}
	if !p.Direct {
		v.Title = "Use the computer's boot menu"
		v.Detail = map[string]string{
			"legacy":     "This computer does not offer the supported automatic restart path. Keep the USB connected and follow the boot instructions below.",
			"timeout":    "The compatibility check took too long. Wait a moment, then choose Check again, or use the boot instructions below.",
			"media":      "Open this application from the original Beamo USB. A copied application or an unidentified USB cannot request a direct restart.",
			"unattended": "Automated installation files were found on this USB. Beamo Wipe will not request a guided restart. Review those files, then use the boot menu.",
			"pending":    "Another application has already requested a special next startup. Beamo will not replace it. Complete that startup before trying again.",
			"entry":      "The computer has not provided one exact boot entry for this USB. You can still choose the USB from its boot menu.",
			"firmware":   "The computer's boot settings could not be read. You can still use the boot menu. Administrator permission may be required for a guided restart.",
			"platform":   "This launcher supports Intel/AMD 64-bit Windows and Linux PCs. This USB does not support Apple Silicon or Chromebooks.",
			"live":       "You are already in the Beamo USB environment. Use the Beamo Wipe window to choose and confirm a disk.",
		}[p.Problem]
		if v.Detail == "" {
			v.Detail = "Automatic startup could not be checked. Nothing has been changed. Follow the boot instructions below."
		}
	}
	return v
}

// A deadline is inconclusive evidence, not evidence of the wrong USB.
func inspectPlan(ctx context.Context, probe func(context.Context) Snapshot) Plan {
	s := probe(ctx)
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return Plan{Problem: "timeout"}
	}
	if ctx.Err() != nil {
		return Plan{Problem: "cancelled"}
	}
	return makePlan(s)
}

type app struct {
	mu          sync.Mutex
	token, host string
	preview     bool
	busy        bool
	p           Plan
	current     view
	probe       func(context.Context) Snapshot
	restart     func(context.Context, string) error
	close       chan struct{}
	closeOnce   sync.Once
	lastSeen    time.Time
}

func (a *app) serve(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	w.Header().Set("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
	if r.Host != a.host {
		http.Error(w, "Invalid host", 403)
		return
	}
	if strings.HasPrefix(r.URL.Path, "/api/") {
		if r.Method != "POST" || r.Header.Get("Origin") != "http://"+a.host || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-Beamo-Token")), []byte(a.token)) != 1 {
			http.Error(w, "Request not authorized", 403)
			return
		}
		if r.Header.Get("Content-Type") != "application/json" {
			http.Error(w, "JSON required", 415)
			return
		}
		var body struct {
			Confirm bool `json:"confirm"`
		}
		dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 256))
		dec.DisallowUnknownFields()
		if dec.Decode(&body) != nil || dec.Decode(&struct{}{}) != io.EOF {
			http.Error(w, "Invalid request", 400)
			return
		}
		a.mu.Lock()
		a.lastSeen = time.Now()
		if r.URL.Path == "/api/state" {
			v := a.current
			a.mu.Unlock()
			sendJSON(w, v)
			return
		}
		if a.busy {
			a.mu.Unlock()
			http.Error(w, "Another action is in progress", 409)
			return
		}
		switch r.URL.Path {
		case "/api/close":
			a.mu.Unlock()
			sendJSON(w, map[string]bool{"closed": true})
			if flusher, ok := w.(http.Flusher); ok {
				flusher.Flush()
			}
			a.closeOnce.Do(func() { close(a.close) })
			return
		case "/api/check":
			a.busy = true
			a.mu.Unlock()
			ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
			defer cancel()
			p := inspectPlan(ctx, a.probe)
			a.mu.Lock()
			a.p = p
			a.current = planView(p, a.preview)
			a.busy = false
			v := a.current
			a.mu.Unlock()
			sendJSON(w, v)
			return
		case "/api/restart":
			if !body.Confirm || !a.p.Direct {
				a.mu.Unlock()
				http.Error(w, "Check readiness and confirm first", 409)
				return
			}
			if a.preview {
				a.mu.Unlock()
				sendJSON(w, map[string]string{"message": "Preview complete. No restart was requested and nothing was erased."})
				return
			}
			p := a.p
			a.busy = true
			a.p = Plan{}
			a.mu.Unlock()
			// Ignore browser disconnect after permission is requested. The helper
			// owns cleanup. A new request cannot race it or reuse the old plan.
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
			defer cancel()
			err := a.restart(ctx, p.Fingerprint)
			a.mu.Lock()
			a.busy = false
			a.current = planView(Plan{}, false)
			a.mu.Unlock()
			if err != nil {
				http.Error(w, "Restart was not confirmed. No erasure was requested. If permission was declined, check readiness and try again. If a firmware request could not be cleared, use the normal boot menu at your next startup.", 503)
				return
			}
			sendJSON(w, map[string]string{"message": "Restart requested. Keep the USB connected. You must still choose and confirm the disk after restarting."})
			return
		default:
			a.mu.Unlock()
			http.NotFound(w, r)
			return
		}
	}
	if r.Method != "GET" {
		w.WriteHeader(405)
		return
	}
	names := map[string]string{"/": "web/index.html", "/app.js": "web/app.js", "/style.css": "web/style.css"}
	name, ok := names[r.URL.Path]
	if !ok {
		http.NotFound(w, r)
		return
	}
	b, err := assets.ReadFile(name)
	if err != nil {
		http.Error(w, "Unavailable", 500)
		return
	}
	contentType := map[string]string{"/": "text/html; charset=utf-8", "/app.js": "text/javascript; charset=utf-8", "/style.css": "text/css; charset=utf-8"}
	w.Header().Set("Content-Type", contentType[r.URL.Path])
	_, _ = w.Write(b)
}

func sendJSON(w http.ResponseWriter, value any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(value)
}

func run() error {
	preview := false
	if len(os.Args) == 2 && os.Args[1] == "--version" {
		fmt.Println(version, sourceCommit, "dirty="+sourceDirty)
		return nil
	}
	if len(os.Args) == 2 && os.Args[1] == "--help" {
		fmt.Println("Start Beamo Wipe [--preview | --check-json | --version]\nThis launcher never erases a disk. A guided restart needs confirmation.")
		return nil
	}
	if len(os.Args) == 2 && strings.HasPrefix(os.Args[1], "--restart-helper=") {
		want := strings.TrimPrefix(os.Args[1], "--restart-helper=")
		if b, err := hex.DecodeString(want); err != nil || len(b) != 32 {
			return errors.New("invalid restart request")
		}
		return platformRestart(want)
	}
	if len(os.Args) == 2 && os.Args[1] == "--check-json" {
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		return json.NewEncoder(os.Stdout).Encode(planView(inspectPlan(ctx, platformProbe), false))
	}
	if len(os.Args) == 2 && os.Args[1] == "--preview" {
		preview = true
	} else if len(os.Args) != 1 {
		return errors.New("unsupported argument")
	}
	if !preview {
		if relaunched, err := prepareDesktop(); err != nil || relaunched {
			return err
		}
	}
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return err
	}
	defer ln.Close()
	tokenBytes := make([]byte, 32)
	if _, err := rand.Read(tokenBytes); err != nil {
		return err
	}
	a := &app{token: hex.EncodeToString(tokenBytes), host: ln.Addr().String(), preview: preview, probe: platformProbe, restart: platformElevate, close: make(chan struct{}), lastSeen: time.Now()}
	if preview {
		a.probe = func(context.Context) Snapshot { return Snapshot{} }
	}
	a.current = view{Preview: preview, Version: version, Title: "Check before restarting", Detail: "The check reads compatibility information. It does not erase anything or change boot settings."}
	if preview {
		// Preview injects a plan without ever reading devices or firmware.
		a.p = Plan{Direct: true, Fingerprint: strings.Repeat("0", 64)}
		a.current = planView(a.p, true)
		a.probe = func(context.Context) Snapshot { return Snapshot{Problem: "entry"} }
	}
	srv := &http.Server{Handler: http.HandlerFunc(a.serve), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 4 * time.Minute, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 8192}
	go func() { _ = srv.Serve(ln) }()
	url := "http://" + a.host + "/#" + a.token
	if err := func() error {
		if preview && os.Getenv("BEAMO_PREVIEW_NO_OPEN") == "1" {
			return nil
		}
		return openBrowser(url)
	}(); err != nil {
		fmt.Fprintln(os.Stderr, "Open this address in your browser:", url)
		notifyFailure("Your browser could not open. Open START-HERE.html on the USB for boot instructions.")
	}
	if preview {
		fmt.Println(url)
	}
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	defer srv.Close()
	for {
		select {
		case <-a.close:
			return nil
		case <-ticker.C:
			a.mu.Lock()
			idle := time.Since(a.lastSeen) > 5*time.Minute && !a.busy
			a.mu.Unlock()
			if idle {
				return nil
			}
		}
	}
}

func main() {
	if runtime.GOARCH != "amd64" && !(len(os.Args) == 2 && (os.Args[1] == "--preview" || os.Args[1] == "--version" || os.Args[1] == "--help" || os.Args[1] == "--check-json")) {
		notifyFailure("This launcher supports Intel/AMD 64-bit Windows and Linux PCs.")
		os.Exit(2)
	}
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "Beamo Wipe:", err)
		notifyFailure("Beamo could not complete the request. Nothing was erased by this launcher. Open START-HERE.html for boot instructions.")
		os.Exit(1)
	}
}
