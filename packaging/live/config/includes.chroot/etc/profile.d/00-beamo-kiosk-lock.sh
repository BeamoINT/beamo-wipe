# Sourced from /etc/profile before later profile.d scripts (name sorts first).
# Disable job control so Ctrl+Z / Ctrl+C cannot drop to a root shell that
# can exec /usr/lib/beamo-wipe/nwipe and skip the confirm gates.
if [ "$(tty 2>/dev/null)" = "/dev/tty1" ]; then
  set +m
  stty susp undef 2>/dev/null || true
  stty quit undef 2>/dev/null || true
  stty intr undef 2>/dev/null || true
  trap '' TSTP INT QUIT
fi
