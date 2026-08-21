# Beamo Wipe live session — kiosk. Never drop to a shell with nwipe.
beamo_wipe_ui() {
  if command -v startx >/dev/null 2>&1; then
    # Wait up to 90s for X to listen. Do not timeout a running wizard or wipe.
    startx /usr/local/bin/beamo-wipe -- -nolisten tcp &
    spid=$!
    n=0
    while [ "$n" -lt 90 ]; do
      if ! kill -0 "$spid" 2>/dev/null; then
        wait "$spid" || true
        # A leftover socket after startx died would skip console forever
        # and make the next startx fail with "display already active".
        rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock 2>/dev/null || true
        /usr/local/bin/beamo-wipe --console
        return $?
      fi
      if [ -S /tmp/.X11-unix/X0 ]; then
        wait "$spid"
        return $?
      fi
      n=$((n + 1))
      sleep 1
    done
    if ! kill -0 "$spid" 2>/dev/null; then
      wait "$spid" || true
      rm -f /tmp/.X11-unix/X0 /tmp/.X0-lock 2>/dev/null || true
      /usr/local/bin/beamo-wipe --console
      return $?
    fi
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
  # Interactive bash job control would otherwise let Ctrl+Z drop to a root
  # shell that can exec /usr/lib/beamo-wipe/nwipe and skip every confirm gate.
  set +m
  stty susp undef 2>/dev/null || true
  stty quit undef 2>/dev/null || true
  stty intr undef 2>/dev/null || true
  trap '' TSTP INT QUIT
  while true; do
    beamo_wipe_ui || true
    sleep 1
  done
fi
