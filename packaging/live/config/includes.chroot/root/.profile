# Beamo Wipe live session — kiosk. Never drop to a shell with nwipe.
beamo_wipe_ui() {
  if command -v startx >/dev/null 2>&1; then
    # Wait up to 90s for X to listen. Do not timeout a running wizard or wipe.
    startx /usr/local/bin/beamo-wipe -- -nolisten tcp &
    spid=$!
    n=0
    while [ "$n" -lt 90 ]; do
      if [ -S /tmp/.X11-unix/X0 ]; then
        wait "$spid"
        return $?
      fi
      if ! kill -0 "$spid" 2>/dev/null; then
        wait "$spid" || true
        break
      fi
      n=$((n + 1))
      sleep 1
    done
    if [ ! -S /tmp/.X11-unix/X0 ]; then
      kill "$spid" 2>/dev/null || true
      wait "$spid" 2>/dev/null || true
      /usr/local/bin/beamo-wipe --console
      return $?
    fi
    wait "$spid"
    return $?
  fi
  /usr/local/bin/beamo-wipe --console
}

if [ "$(tty 2>/dev/null)" = "/dev/tty1" ] && [ -z "${DISPLAY:-}" ]; then
  while true; do
    beamo_wipe_ui || true
    sleep 1
  done
fi
